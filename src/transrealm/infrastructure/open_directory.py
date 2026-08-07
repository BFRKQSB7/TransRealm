"""Open-directory Project container: manifest, path safety, and file integrity.

A TransRealm Project has two interchangeable forms (see ``03`` §3 and ``04``
§7). The open-directory form is authoritative as ``manifest.json`` +
``project.sqlite`` + declared attachments. This module owns the shared
manifest contract used by both the open directory and the single-file
``.aiproject`` view (P1-T02-M01 foundation):

- the manifest records format/schema/software versions and every controlled
  entry's relative path, type, size, and SHA-256 hash (the manifest itself is
  never self-hashed);
- opening a container is fail-closed: unknown format/schema versions, entries
  outside the root (absolute paths, drives, UNC, ``..``, normalization
  escapes), link/junction entries, case- or Unicode-equivalent duplicate
  paths, duplicate JSON keys, and any size/hash mismatch are rejected before
  the container is used.

M02 wrote the single-file ``.aiproject`` view (``write_archive``) and M03 adds
the isolated import path (``extract_archive``): unpacking only into a staging
root, enforcing resource limits (entry count, per-entry size, total size,
compression ratio) against the ZIP headers before extraction, and rejecting
undeclared members. Secret scanning and the final atomic install belong to the
application/archive-service layer and the M04 milestone.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import unicodedata
import zipfile
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

MANIFEST_FORMAT_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
MANIFEST_FILENAME = "manifest.json"
DATABASE_FILENAME = "project.sqlite"
ARCHIVE_EXTENSION = ".aiproject"
CRITICAL_ENTRY_TYPE = "database"
ATTACHMENT_ENTRY_TYPE = "attachment"
HASH_ALGORITHM = "sha256"
_HASH_PREFIX = f"{HASH_ALGORITHM}:"
_DRIVE_OR_UNC = re.compile(r"^[A-Za-z]:|^(//|\\\\)")
_HASH_RE = re.compile(rf"^{HASH_ALGORITHM}:[0-9a-f]{{64}}$")
_MAX_MANIFEST_BYTES = 1024 * 1024


class OpenDirectoryError(Exception):
    """Base error for open-directory Project container operations."""


class ManifestError(OpenDirectoryError):
    """The manifest is missing, malformed, or declares an unsupported version."""


class PathValidationError(OpenDirectoryError):
    """An entry path escapes the root, is a link, or collides after normalization."""


class FileIntegrityError(OpenDirectoryError):
    """A declared entry is missing, not a regular file, or fails size/hash checks."""


class ArchiveError(OpenDirectoryError):
    """An archive is invalid, corrupt, or contains undeclared/duplicate members."""


class ArchiveLimitError(OpenDirectoryError):
    """An archive exceeds a resource limit (entries, size, or compression ratio)."""


@dataclass(frozen=True)
class ArchiveLimits:
    """Resource limits enforced while unpacking a ``.aiproject`` archive.

    Fixed fixture values (``04`` §7): the Release Gate pins the final numbers,
    and a caller may pass narrower limits per operation. The defaults protect
    against resource exhaustion from zip bombs and oversized containers.
    """

    max_entries: int = 1000
    max_entry_size: int = 256 * 1024 * 1024
    max_total_size: int = 512 * 1024 * 1024
    max_compression_ratio: float = 5000.0


@dataclass(frozen=True)
class ManifestEntry:
    """A controlled entry declared in the manifest."""

    relpath: str
    type: str
    size: int
    hash: str


@dataclass(frozen=True)
class ManifestInfo:
    """Parsed and structurally validated manifest content."""

    format_version: int
    schema_version: int
    software: str
    entries: tuple[ManifestEntry, ...]
    source_id: int | None = None


def build_manifest(manifest: ManifestInfo) -> dict[str, object]:
    """Serialize a ``ManifestInfo`` to the plain manifest structure."""
    payload: dict[str, object] = {
        "format_version": manifest.format_version,
        "schema_version": manifest.schema_version,
        "software": manifest.software,
        "files": {
            entry.relpath: {
                "type": entry.type,
                "size": entry.size,
                "hash": entry.hash,
            }
            for entry in manifest.entries
        },
    }
    if manifest.source_id is not None:
        payload["source_id"] = manifest.source_id
    return payload


def write_manifest(directory: Path, manifest: ManifestInfo) -> None:
    """Atomically write the manifest into ``directory``.

    A temporary file in the same directory is replaced via ``os.replace`` so a
    reader never observes a partially written manifest.
    """
    payload = json.dumps(build_manifest(manifest), indent=2, ensure_ascii=False) + "\n"
    fd, temp_path = _mkstemp_sibling(directory / MANIFEST_FILENAME)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temp_path, directory / MANIFEST_FILENAME)
    except Exception:
        try:
            Path(temp_path).unlink()
        except OSError:
            pass
        raise


def load_manifest(directory: Path) -> ManifestInfo:
    """Read, parse, and structurally validate ``directory/manifest.json``.

    Duplicate JSON keys are rejected so a tampered ``files`` object cannot
    silently shadow a critical entry.
    """
    manifest_path = directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ManifestError(f"Manifest {manifest_path.name} is missing.")
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"Cannot read manifest: {exc}") from exc
    return parse_manifest_text(text)


def parse_manifest_text(text: str) -> ManifestInfo:
    """Parse and structurally validate manifest JSON text.

    Shared by ``load_manifest`` (a container on disk) and archive import (a
    manifest member read from a ``.aiproject`` without touching the filesystem).
    Duplicate JSON keys are rejected so a tampered ``files`` object cannot
    silently shadow a critical entry.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ManifestError:
        raise
    except (ValueError, TypeError) as exc:
        raise ManifestError("Manifest is not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise ManifestError("Manifest root must be an object.")
    return _validate_structure(raw)


def validate_manifest(manifest: ManifestInfo) -> None:
    """Validate cross-field manifest invariants.

    Ensures exactly one critical ``database`` entry named ``project.sqlite`` is
    declared, no entry collides after case/Unicode normalization, and no entry
    aliases the manifest itself.
    """
    _require_exactly_one_critical(manifest)
    manifest_identity = _normalized_identity(MANIFEST_FILENAME)
    identities: dict[str, ManifestEntry] = {}
    for entry in manifest.entries:
        canonical = canonical_relpath(entry.relpath)
        identity = _normalized_identity(canonical)
        if identity == manifest_identity:
            raise PathValidationError(
                f"Entry {entry.relpath!r} aliases the manifest itself.",
            )
        if identity in identities:
            raise PathValidationError(
                f"Duplicate entry after path normalization: {entry.relpath!r} "
                f"collides with {identities[identity].relpath!r}.",
            )
        identities[identity] = entry


def canonical_relpath(relpath: str) -> str:
    """Validate ``relpath`` and return its canonical ``/``-joined form.

    Raises:
        PathValidationError: If the path is empty, absolute, a drive/UNC path,
            or contains ``..`` segments that could escape the root.
    """
    if not isinstance(relpath, str) or not relpath.strip():
        raise PathValidationError("Entry path must be a non-empty relative path.")
    if _DRIVE_OR_UNC.match(relpath):
        raise PathValidationError(f"Entry path must be relative: {relpath!r}.")
    if relpath.startswith("/") or relpath.startswith("\\"):
        raise PathValidationError(f"Entry path must be relative: {relpath!r}.")
    segments: list[str] = []
    for segment in relpath.replace("\\", "/").split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            raise PathValidationError(
                f"Entry path must not contain '..': {relpath!r}.",
            )
        if any(ord(char) < 0x20 for char in segment):
            raise PathValidationError(
                f"Entry path must not contain control characters: {relpath!r}.",
            )
        if segment.endswith(":") or ":" in segment:
            raise PathValidationError(
                f"Entry path must not contain drive segments: {relpath!r}.",
            )
        segments.append(segment)
    if not segments:
        raise PathValidationError(f"Entry path resolves to empty: {relpath!r}.")
    return "/".join(segments)


def resolve_within_root(directory: Path, relpath: str) -> Path:
    """Return the filesystem path for ``relpath``, asserting it stays in root."""
    canonical = canonical_relpath(relpath)
    root = directory.resolve()
    target = (directory / canonical).resolve()
    if target != root and root not in target.parents:
        raise PathValidationError(
            f"Entry path {relpath!r} resolves outside the project root.",
        )
    return target


def is_link(path: Path) -> bool:
    """Return whether ``path`` is a symbolic link or Windows reparse point.

    Junctions and symlinks both carry ``FILE_ATTRIBUTE_REPARSE_POINT`` on
    Windows; the check uses ``lstat`` so the link itself is examined, not its
    target.
    """
    try:
        st = path.lstat()
    except (OSError, ValueError):
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attributes = int(getattr(st, "st_file_attributes", 0))
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def verify_entries(directory: Path, manifest: ManifestInfo) -> None:
    """Verify every declared entry against the filesystem.

    Each entry must resolve inside the root, not be a link, be a regular file,
    and match the declared size and SHA-256 hash. Links are detected on the
    literal path (without following them) so a symlink or junction cannot be
    hidden by path resolution.
    """
    for entry in manifest.entries:
        canonical = canonical_relpath(entry.relpath)
        if is_link(directory / canonical):
            raise PathValidationError(
                f"Entry {entry.relpath!r} is a link; links are not allowed.",
            )
        path = resolve_within_root(directory, canonical)
        try:
            st = path.lstat()
        except OSError as exc:
            raise FileIntegrityError(
                f"Entry {entry.relpath!r} is missing or unreadable: {exc}.",
            ) from exc
        if not stat.S_ISREG(st.st_mode):
            raise FileIntegrityError(
                f"Entry {entry.relpath!r} is not a regular file.",
            )
        if st.st_size != entry.size:
            raise FileIntegrityError(
                f"Entry {entry.relpath!r} size mismatch: manifest {entry.size}, "
                f"actual {st.st_size}.",
            )
        if _sha256_of_file(path) != entry.hash:
            raise FileIntegrityError(
                f"Entry {entry.relpath!r} hash mismatch; file was modified.",
            )


def compute_entry(relpath: str, path: Path, *, entry_type: str) -> ManifestEntry:
    """Compute a manifest entry for an existing regular file."""
    st = path.lstat()
    return ManifestEntry(
        relpath=canonical_relpath(relpath),
        type=entry_type,
        size=st.st_size,
        hash=_sha256_of_file(path),
    )


def check_container_identity(db_path: Path, manifest: ManifestInfo) -> None:
    """Read-only identity check: exactly one Project whose schema matches.

    Raised before any forward migration runs so a tampered or multi-Project
    container is never migrated. Mirrors the isolated-import identity check
    (``04`` §7) with the open-directory error taxonomy.

    Raises:
        OpenDirectoryError: If the database cannot be inspected or does not hold
            exactly one Project.
        ManifestError: If the Project ``schema_version`` is not an integer or
            does not match the manifest.
    """
    db_path = Path(db_path)
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        raise OpenDirectoryError(f"Cannot inspect container database: {exc}") from exc
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute(
            "SELECT name, schema_version FROM projects ORDER BY id",
        ).fetchall()
    except sqlite3.Error as exc:
        raise OpenDirectoryError(f"Cannot inspect container database: {exc}") from exc
    finally:
        conn.close()
    if len(rows) != 1:
        raise OpenDirectoryError(
            f"Container must hold exactly one Project; found {len(rows)}.",
        )
    try:
        schema_version = int(str(rows[0][1]))
    except (TypeError, ValueError) as exc:
        raise ManifestError(
            f"Container database schema_version {rows[0][1]!r} is not an integer.",
        ) from exc
    if schema_version != manifest.schema_version:
        raise ManifestError(
            f"Manifest schema_version {manifest.schema_version} does not match the "
            f"database schema_version {schema_version}.",
        )


def purge_sqlite_sidecars(db_path: Path) -> None:
    """Best-effort removal of WAL/shm sidecars next to ``db_path``.

    Opening a WAL-mode database may create ``-wal``/``-shm`` companion files.
    Containers must hold only their declared entries, so any sidecar left by a
    read-only validation or a closed migration connection is removed.
    """
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{db_path}{suffix}")
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass


def remove_pre_upgrade_backups(directory: Path) -> None:
    """Remove P0-T03-M00 pre-upgrade backups left inside a container.

    A forward migration creates a ``*.pre-upgrade-*.db.bak`` next to the
    database. After a successful migration the container must hold only its
    declared entries, so the transient backup is removed; on failure it is left
    in place as the recovery point.
    """
    pattern = f"{Path(DATABASE_FILENAME).stem}.pre-upgrade-*.db.bak"
    for backup in Path(directory).glob(pattern):
        try:
            backup.unlink()
        except OSError:
            pass


def regenerate_manifest(
    directory: Path,
    *,
    schema_version: int,
    source_id: int | None = None,
) -> ManifestInfo:
    """Rewrite a container's manifest for the current database file.

    Recomputes the critical ``project.sqlite`` entry (its size/hash changed when
    migrations were applied), keeps the declared attachment entries, and writes
    the manifest atomically. ``source_id`` defaults to the existing manifest's
    value so an origin id survives regeneration; pass an explicit value to set
    it during install.

    Returns the newly written manifest.
    """
    directory = Path(directory)
    previous = load_manifest(directory)
    db_entry = compute_entry(
        DATABASE_FILENAME,
        directory / DATABASE_FILENAME,
        entry_type=CRITICAL_ENTRY_TYPE,
    )
    attachments = [entry for entry in previous.entries if entry.type == ATTACHMENT_ENTRY_TYPE]
    manifest = ManifestInfo(
        format_version=previous.format_version,
        schema_version=schema_version,
        software=previous.software,
        entries=(db_entry, *attachments),
        source_id=previous.source_id if source_id is None else source_id,
    )
    validate_manifest(manifest)
    write_manifest(directory, manifest)
    return manifest


def cleanup_after_container_migration(
    directory: Path,
    *,
    schema_version: int,
) -> ManifestInfo:
    """Post-migration container hygiene: sidecars, a fresh manifest, then backups.

    The pre-upgrade backup is removed only after the regenerated manifest is
    durably written, so a manifest write failure (disk full / permission change)
    leaves the backup in place as the container's recovery point. The caller
    re-validates entries so the migrated container is verified before it is
    opened or installed.
    """
    directory = Path(directory)
    db_path = directory / DATABASE_FILENAME
    purge_sqlite_sidecars(db_path)
    manifest = regenerate_manifest(directory, schema_version=schema_version)
    remove_pre_upgrade_backups(directory)
    return manifest


def write_archive(directory: Path, archive_path: Path) -> None:
    """Zip a fully-formed open-directory container into ``archive_path``.

    Every regular file under ``directory`` is stored in the archive at its path
    relative to the container root (including ``manifest.json``), so an
    extracted archive is itself an open directory. The write is atomic: a
    temporary file in the target directory is replaced over ``archive_path``,
    so a failure never leaves a partial archive. Links are refused so a link
    cannot smuggle content outside the container into the archive.

    Args:
        directory: A fully-formed container (``manifest.json`` + entries).
        archive_path: Destination ``.aiproject`` file.

    Raises:
        OpenDirectoryError: If the archive target directory is missing or an
            I/O error occurs while reading the container or writing the archive.
        PathValidationError: If a directory entry is a link.
    """
    directory = Path(directory)
    archive_path = Path(archive_path)
    if not archive_path.parent.is_dir():
        raise OpenDirectoryError(
            f"Archive target directory does not exist: {archive_path.parent}",
        )
    fd, temp_path = _mkstemp_sibling(archive_path)
    os.close(fd)
    try:
        try:
            with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in _iter_container_files(directory):
                    archive.write(
                        path,
                        arcname=path.relative_to(directory).as_posix(),
                    )
            os.replace(temp_path, archive_path)
        except PathValidationError:
            raise
        except OSError as exc:
            raise OpenDirectoryError(f"Cannot write archive: {exc}") from exc
    except Exception:
        try:
            Path(temp_path).unlink()
        except OSError:
            pass
        raise


def extract_archive(
    archive_path: Path,
    target_dir: Path,
    *,
    limits: ArchiveLimits | None = None,
) -> None:
    """Extract a validated ``.aiproject`` archive into ``target_dir``.

    Only the entries declared in the archive's ``manifest.json`` are written to
    ``target_dir`` — never arbitrary members — so path traversal, undeclared
    content, and links cannot escape the staging root. Resource limits (entry
    count, per-entry uncompressed size, total uncompressed size, and
    compression ratio) are enforced against the ZIP headers *before* any member
    is written, so a zip bomb is rejected without exhausting disk. The extracted
    container is then verified with ``verify_entries`` (per-entry size + SHA-256
    + link check).

    Args:
        archive_path: The ``.aiproject`` ZIP to extract.
        target_dir: The (empty) directory to extract into.
        limits: Optional resource limits; defaults to the fixed fixture values.

    Raises:
        ArchiveError: If the archive is not a valid ZIP, is corrupt, or contains
            undeclared or duplicate members.
        ArchiveLimitError: If a resource limit is exceeded.
        ManifestError: If the manifest is missing, invalid, or unsupported.
        PathValidationError: If an entry path escapes the root or collides.
        FileIntegrityError: If an entry is missing or fails size/hash checks.
    """
    limits = limits or ArchiveLimits()
    archive_path = Path(archive_path)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _extract_validated(archive, target_dir, limits)
    except (ManifestError, PathValidationError, FileIntegrityError, ArchiveError,
            ArchiveLimitError):
        raise
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"Archive is not a valid ZIP: {exc}") from exc
    except Exception as exc:
        raise ArchiveError(f"Cannot extract archive: {exc}") from exc


def _extract_validated(
    archive: zipfile.ZipFile,
    target_dir: Path,
    limits: ArchiveLimits,
) -> None:
    names = archive.namelist()
    if MANIFEST_FILENAME not in names:
        raise ManifestError(f"Archive is missing {MANIFEST_FILENAME}.")
    _check_member_duplicates(names)
    if len(names) > limits.max_entries:
        raise ArchiveLimitError(
            f"Archive contains {len(names)} members, exceeding the limit of "
            f"{limits.max_entries}.",
        )
    manifest_member = archive.getinfo(MANIFEST_FILENAME)
    if manifest_member.is_dir():
        raise ManifestError("Archive manifest is not a regular file.")
    if manifest_member.file_size > _MAX_MANIFEST_BYTES:
        raise ManifestError(
            f"Archive manifest is {manifest_member.file_size} bytes, exceeding the "
            f"limit of {_MAX_MANIFEST_BYTES}.",
        )
    raw = archive.read(MANIFEST_FILENAME)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError("Archive manifest is not valid UTF-8.") from exc
    manifest = parse_manifest_text(text)
    validate_manifest(manifest)
    declared = {entry.relpath for entry in manifest.entries}
    allowed = {MANIFEST_FILENAME, *declared}
    _check_undeclared_members(names, allowed)
    _check_size_limits(archive, manifest, limits)
    # The manifest is a controlled entry of the container even though it never
    # declares itself; write the exact bytes we validated so the staging
    # container is complete (manifest.json + project.sqlite + attachments).
    (target_dir / MANIFEST_FILENAME).write_bytes(raw)
    for entry in manifest.entries:
        _extract_entry(archive, entry, target_dir)
    verify_entries(target_dir, manifest)


def _check_member_duplicates(names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ArchiveError(f"Archive contains a duplicate member: {name!r}.")
        seen.add(name)


def _check_undeclared_members(names: list[str], allowed: set[str]) -> None:
    for name in names:
        if name not in allowed:
            raise ArchiveError(
                f"Archive contains a member not declared in the manifest: {name!r}.",
            )


def _check_size_limits(
    archive: zipfile.ZipFile,
    manifest: ManifestInfo,
    limits: ArchiveLimits,
) -> None:
    total = 0
    for entry in manifest.entries:
        try:
            member = archive.getinfo(entry.relpath)
        except KeyError as exc:
            raise FileIntegrityError(
                f"Manifest declares {entry.relpath!r} but the archive does not "
                "contain it.",
            ) from exc
        if member.is_dir():
            raise FileIntegrityError(
                f"Manifest declares {entry.relpath!r} but the archive entry is a "
                "directory.",
            )
        if member.file_size > limits.max_entry_size:
            raise ArchiveLimitError(
                f"Entry {entry.relpath!r} is {member.file_size} bytes, exceeding the "
                f"per-entry limit of {limits.max_entry_size}.",
            )
        _check_compression_ratio(entry.relpath, member, limits)
        total += member.file_size
        if total > limits.max_total_size:
            raise ArchiveLimitError(
                f"Total uncompressed size {total} bytes exceeds the limit of "
                f"{limits.max_total_size}.",
            )


def _check_compression_ratio(
    relpath: str,
    member: zipfile.ZipInfo,
    limits: ArchiveLimits,
) -> None:
    compressed = member.compress_size
    uncompressed = member.file_size
    if compressed > 0:
        ratio = uncompressed / compressed
    elif uncompressed == 0:
        ratio = 0.0
    else:
        ratio = float("inf")
    if ratio > limits.max_compression_ratio:
        raise ArchiveLimitError(
            f"Entry {relpath!r} has compression ratio {ratio:.0f}:1, exceeding the "
            f"limit of {limits.max_compression_ratio}:1.",
        )


def _extract_entry(
    archive: zipfile.ZipFile,
    entry: ManifestEntry,
    target_dir: Path,
) -> None:
    canonical = canonical_relpath(entry.relpath)
    dest = resolve_within_root(target_dir, canonical)
    member = archive.getinfo(entry.relpath)
    with archive.open(member, "r") as source:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as handle:
            shutil.copyfileobj(source, handle, length=64 * 1024)


def _iter_container_files(directory: Path) -> Generator[Path, None, None]:
    """Yield regular files under ``directory``, refusing links before descent.

    A symlink or Windows reparse point (junction) is rejected the moment it is
    listed, before its target is ever traversed, so a link cannot smuggle
    content outside the container into the archive.
    """
    stack = [directory]
    while stack:
        current = stack.pop()
        for child in sorted(current.iterdir(), key=lambda path: path.name):
            if is_link(child):
                raise PathValidationError(
                    f"Cannot archive link entry: {child.name!r}.",
                )
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                yield child


def _require_exactly_one_critical(manifest: ManifestInfo) -> None:
    critical = [entry for entry in manifest.entries if entry.type == CRITICAL_ENTRY_TYPE]
    if len(critical) != 1:
        raise FileIntegrityError(
            f"Manifest must declare exactly one {CRITICAL_ENTRY_TYPE!r} entry "
            f"named {DATABASE_FILENAME!r}; found {len(critical)}.",
        )
    if canonical_relpath(critical[0].relpath) != DATABASE_FILENAME:
        raise FileIntegrityError(
            f"Critical entry must be named {DATABASE_FILENAME!r}; "
            f"found {critical[0].relpath!r}.",
        )


def _validate_structure(raw: dict[str, object]) -> ManifestInfo:
    format_version = _require_int(raw, "format_version")
    if format_version != MANIFEST_FORMAT_VERSION:
        raise ManifestError(
            f"Unsupported manifest format_version {format_version!r}; "
            f"this build supports {MANIFEST_FORMAT_VERSION}.",
        )
    schema_version = _require_int(raw, "schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise ManifestError(
            f"Unsupported schema_version {schema_version!r}; "
            f"this build supports {supported}.",
        )
    software = raw.get("software")
    if not isinstance(software, str) or not software.strip():
        raise ManifestError("Manifest must declare a non-empty 'software' version.")
    files = raw.get("files")
    if not isinstance(files, dict):
        raise ManifestError("Manifest 'files' must be an object.")
    entries: list[ManifestEntry] = []
    for relpath, value in files.items():
        entries.append(_validate_file_entry(relpath, value))
    source_id = raw.get("source_id")
    if source_id is not None and (
        not isinstance(source_id, int)
        or isinstance(source_id, bool)
        or source_id < 1
    ):
        raise ManifestError("Manifest 'source_id' must be a positive integer.")
    return ManifestInfo(
        format_version=format_version,
        schema_version=schema_version,
        software=software,
        entries=tuple(entries),
        source_id=source_id,
    )


def _validate_file_entry(relpath: str, value: object) -> ManifestEntry:
    if not isinstance(value, dict):
        raise ManifestError(f"Entry {relpath!r} must be an object.")
    entry_type = value.get("type")
    if entry_type not in {CRITICAL_ENTRY_TYPE, ATTACHMENT_ENTRY_TYPE}:
        raise ManifestError(
            f"Entry {relpath!r} has unsupported type {entry_type!r}.",
        )
    size = value.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ManifestError(f"Entry {relpath!r} has an invalid 'size'.")
    digest = value.get("hash")
    if not isinstance(digest, str) or not _HASH_RE.match(digest):
        raise ManifestError(f"Entry {relpath!r} has an invalid 'hash'.")
    # Validate the path up front so structural errors surface before open.
    canonical_relpath(relpath)
    return ManifestEntry(relpath=relpath, type=str(entry_type), size=size, hash=digest)


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"Manifest contains a duplicate key: {key!r}.")
        result[key] = value
    return result


def _require_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ManifestError(f"Manifest '{key}' must be an integer.")
    return value


def _normalized_identity(canonical: str) -> str:
    """Return a collision key that folds case, Unicode, and trailing aliases.

    Windows trims trailing dots/spaces from file names (``evil.`` and ``evil``
    alias the same file), so each segment is stripped before NFC + casefold.
    """
    cleaned: list[str] = []
    for segment in canonical.split("/"):
        stripped = segment.rstrip(". ")
        if not stripped:
            raise PathValidationError(
                f"Entry path {canonical!r} contains an empty segment after "
                "normalization.",
            )
        cleaned.append(unicodedata.normalize("NFC", stripped).casefold())
    return "/".join(cleaned)


def _mkstemp_sibling(path: Path) -> tuple[int, str]:
    return tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return f"{_HASH_PREFIX}{digest.hexdigest()}"


__all__ = [
    "ARCHIVE_EXTENSION",
    "ATTACHMENT_ENTRY_TYPE",
    "CRITICAL_ENTRY_TYPE",
    "DATABASE_FILENAME",
    "HASH_ALGORITHM",
    "MANIFEST_FILENAME",
    "MANIFEST_FORMAT_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "ArchiveError",
    "ArchiveLimitError",
    "ArchiveLimits",
    "ManifestEntry",
    "ManifestError",
    "ManifestInfo",
    "OpenDirectoryError",
    "PathValidationError",
    "FileIntegrityError",
    "build_manifest",
    "canonical_relpath",
    "check_container_identity",
    "cleanup_after_container_migration",
    "compute_entry",
    "extract_archive",
    "is_link",
    "load_manifest",
    "parse_manifest_text",
    "purge_sqlite_sidecars",
    "regenerate_manifest",
    "remove_pre_upgrade_backups",
    "resolve_within_root",
    "validate_manifest",
    "verify_entries",
    "write_archive",
    "write_manifest",
]
