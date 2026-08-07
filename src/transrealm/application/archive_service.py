"""Single-file ``.aiproject`` archive export/import (P1-T02-M02/M03).

A logical Project can be exported to a single-file archive that is the archive
view of the open-directory container (``03`` §3, ``04`` §7): a standard ZIP
holding ``manifest.json``, a consistent SQLite snapshot of the database, and
any declared attachments. The database is snapshotted with the SQLite backup
API (never a raw copy of an active WAL database), the manifest declares every
entry's relative path, type, size and SHA-256 hash so the archive is
re-verifiable, and secrets/logs never enter the package because only
manifest-declared entries are included. Export refuses to silently package a
source holding zero or multiple Projects.

Import (M03) extracts a ``.aiproject`` only into a fresh, isolated staging
directory, enforcing resource limits and the manifest path/size/hash checks
before anything is used; tampered, missing-attachment, conflicting, traversing,
linked, or bomb archives never touch the final target. The validated staging
container is ready for the P1-T02-M04 atomic install.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from transrealm.application.open_directory_service import open_open_directory_project
from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.migrations.backup import create_consistent_snapshot
from transrealm.infrastructure.open_directory import (
    ATTACHMENT_ENTRY_TYPE,
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    ArchiveLimits,
    ManifestEntry,
    ManifestInfo,
    OpenDirectoryError,
    compute_entry,
    extract_archive,
    load_manifest,
    purge_sqlite_sidecars,
    resolve_within_root,
    validate_manifest,
    verify_entries,
    write_archive,
    write_manifest,
)

__all__ = [
    "ArchiveExportError",
    "ArchiveImportError",
    "export_database_archive",
    "export_open_directory_archive",
    "import_archive_to_staging",
]


class ArchiveExportError(OpenDirectoryError):
    """Single-file archive export failed."""


class ArchiveImportError(OpenDirectoryError):
    """Isolated ``.aiproject`` import failed."""


def export_open_directory_archive(
    directory: Path,
    archive_path: Path,
    *,
    app_version: str,
) -> Path:
    """Export an open-directory Project to a single-file ``.aiproject``.

    The source container is validated fail-closed (manifest structure, path
    safety, per-entry size/hash, exactly one Project identity) before the
    archive is built. Returns ``archive_path``.
    """
    directory = Path(directory)
    archive_path = Path(archive_path)
    with open_open_directory_project(directory, app_version=app_version) as container:
        attachments = [
            (entry.relpath, resolve_within_root(directory, entry.relpath))
            for entry in container.manifest.entries
            if entry.type == ATTACHMENT_ENTRY_TYPE
        ]
        _build_archive(
            db_path=container.db_path,
            attachments=attachments,
            archive_path=archive_path,
            app_version=app_version,
        )
    return archive_path


def export_database_archive(
    db_path: Path,
    archive_path: Path,
    *,
    app_version: str,
) -> Path:
    """Export a bare SQLite Project database to a single-file ``.aiproject``.

    A bare database has no manifest and therefore no declared attachments; the
    archive contains only the consistent database snapshot. The source must
    hold exactly one Project; zero or multiple Projects are rejected rather
    than silently packaged. Returns ``archive_path``.
    """
    db_path = Path(db_path)
    archive_path = Path(archive_path)
    with ProjectService(db_path, app_version=app_version) as service:
        projects = service.list_projects()
        if len(projects) != 1:
            raise ArchiveExportError(
                f"Database must contain exactly one Project; found {len(projects)}.",
            )
    _build_archive(
        db_path=db_path,
        attachments=[],
        archive_path=archive_path,
        app_version=app_version,
    )
    return archive_path


def _build_archive(
    db_path: Path,
    attachments: list[tuple[str, Path]],
    archive_path: Path,
    *,
    app_version: str,
) -> None:
    """Build a staging container and zip it into ``archive_path``.

    The staging directory holds a consistent SQLite snapshot, copies of the
    declared attachments, and a freshly computed manifest. The staging
    container is verified (``verify_entries``) before zipping so the archive's
    manifest/hash is re-verifiable by construction.
    """
    with tempfile.TemporaryDirectory(prefix="transrealm-archive-") as tmp:
        staging = Path(tmp)
        snapshot = staging / DATABASE_FILENAME
        create_consistent_snapshot(db_path, snapshot)
        entries: list[ManifestEntry] = [
            compute_entry(DATABASE_FILENAME, snapshot, entry_type=CRITICAL_ENTRY_TYPE),
        ]
        for relpath, source in attachments:
            dest = staging / relpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            entries.append(compute_entry(relpath, dest, entry_type=ATTACHMENT_ENTRY_TYPE))
        manifest = ManifestInfo(
            format_version=1,
            schema_version=1,
            software=app_version,
            entries=tuple(entries),
        )
        validate_manifest(manifest)
        write_manifest(staging, manifest)
        verify_entries(staging, manifest)
        write_archive(staging, archive_path)


def import_archive_to_staging(
    archive_path: Path,
    staging_dir: Path,
    *,
    limits: ArchiveLimits | None = None,
) -> Path:
    """Extract and validate a ``.aiproject`` into an isolated staging container.

    The archive is unpacked only into ``staging_dir`` (a fresh or empty
    directory) — never into the final target. Every declared entry is checked
    against the manifest (structure, path safety, size/SHA-256) and the resource
    limits before use, and the database must hold exactly one Project whose
    ``schema_version`` matches the manifest. A tampered, missing-attachment,
    conflicting, traversing, linked, or bomb archive is rejected without
    touching the target. On success ``staging_dir`` is a valid open-directory
    container ready for the P1-T02-M04 atomic install. Returns ``staging_dir``.

    Raises:
        ArchiveImportError: If the archive is missing, the staging directory is
            not empty, the staging database is unreadable or does not hold
            exactly one Project matching the manifest schema, or the operation
            fails.
        ManifestError / PathValidationError / FileIntegrityError / ArchiveError /
        ArchiveLimitError: Raised by ``extract_archive`` for manifest, path,
            integrity, archive-structure, or resource-limit failures.
    """
    archive_path = Path(archive_path)
    staging_dir = Path(staging_dir)
    if not archive_path.is_file():
        raise ArchiveImportError(f"Archive does not exist: {archive_path}")
    created = _prepare_staging_dir(staging_dir)
    try:
        extract_archive(archive_path, staging_dir, limits=limits)
        manifest = load_manifest(staging_dir)
        _verify_staging_database(staging_dir / DATABASE_FILENAME, manifest)
    except Exception:
        _cleanup_failed_import(staging_dir, created=created)
        raise
    purge_sqlite_sidecars(staging_dir / DATABASE_FILENAME)
    return staging_dir


def _prepare_staging_dir(staging_dir: Path) -> bool:
    """Ensure ``staging_dir`` exists and is empty; return whether we created it."""
    if staging_dir.exists():
        if not staging_dir.is_dir():
            raise ArchiveImportError(f"Staging path is not a directory: {staging_dir}")
        try:
            has_entries = any(staging_dir.iterdir())
        except OSError as exc:
            raise ArchiveImportError(
                f"Cannot inspect staging directory: {exc}",
            ) from exc
        if has_entries:
            raise ArchiveImportError(
                f"Staging directory is not empty; refusing to extract into it: "
                f"{staging_dir}",
            )
        return False
    try:
        staging_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ArchiveImportError(f"Cannot create staging directory: {exc}") from exc
    return True


def _cleanup_failed_import(staging_dir: Path, *, created: bool) -> None:
    """Best-effort removal of artifacts extracted by a failed import.

    The staging directory was empty before the import, so every entry present is
    an artifact of this operation. The directory itself is only removed when
    this import created it.
    """
    try:
        for entry in list(staging_dir.iterdir()):
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError:
                pass
        if created:
            staging_dir.rmdir()
    except OSError:
        pass


def _verify_staging_database(db_path: Path, manifest: ManifestInfo) -> None:
    """Read-only identity check: exactly one Project whose schema matches."""
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        raise ArchiveImportError(f"Cannot open staging database: {exc}") from exc
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute(
            "SELECT name, schema_version FROM projects ORDER BY id",
        ).fetchall()
    except sqlite3.Error as exc:
        raise ArchiveImportError(f"Cannot inspect staging database: {exc}") from exc
    finally:
        conn.close()
    if len(rows) != 1:
        raise ArchiveImportError(
            f"Container database must hold exactly one Project; found {len(rows)}.",
        )
    try:
        schema_version = int(str(rows[0][1]))
    except (TypeError, ValueError) as exc:
        raise ArchiveImportError(
            f"Container database schema_version {rows[0][1]!r} is not an integer.",
        ) from exc
    if schema_version != manifest.schema_version:
        raise ArchiveImportError(
            f"Manifest schema_version {manifest.schema_version} does not match the "
            f"database schema_version {schema_version}.",
        )

