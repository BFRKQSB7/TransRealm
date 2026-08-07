"""P1-T02-M03: isolated secure ``.aiproject`` import.

A ``.aiproject`` archive is unpacked only into a fresh, isolated staging
directory — never the final target — enforcing per-entry resource limits
(entry count, single size, total size, compression ratio) and the manifest
path/size/SHA-256 checks before anything is used (``04`` §7). Tampered,
missing-attachment, case/Unicode-conflicting, traversal, undeclared-member, and
zip-bomb archives are rejected without touching the target; a successful import
yields a valid open-directory container with the same contract
(``manifest.json`` + ``project.sqlite`` + declared attachments) that reopens as
the same Project.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from transrealm.application.archive_service import (
    ArchiveImportError,
    export_open_directory_archive,
    import_archive_to_staging,
)
from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.open_directory import (
    ATTACHMENT_ENTRY_TYPE,
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_FORMAT_VERSION,
    ArchiveError,
    ArchiveLimitError,
    ArchiveLimits,
    FileIntegrityError,
    ManifestError,
    ManifestInfo,
    PathValidationError,
    compute_entry,
    write_archive,
    write_manifest,
)

APP_VERSION = "0.1.0"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _entry_type(relpath: str) -> str:
    return CRITICAL_ENTRY_TYPE if relpath == DATABASE_FILENAME else ATTACHMENT_ENTRY_TYPE


def _make_valid_db(db_path: Path, *, name: str = "Alpha") -> None:
    """Create a fully-migrated database holding exactly one Project."""
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        service.create_project(name=name, source_language="zh", target_language="en")


def _write_archive(
    archive_path: Path,
    files: dict[str, bytes],
    *,
    manifest: dict[str, object] | None = None,
    manifest_raw: bytes | None = None,
    extra_members: list[tuple[str, bytes]] | None = None,
    compress: bool = False,
) -> None:
    """Write a ZIP with a manifest member and the given file members."""
    if manifest_raw is None:
        if manifest is None:
            manifest = {
                "format_version": MANIFEST_FORMAT_VERSION,
                "schema_version": 1,
                "software": APP_VERSION,
                "files": {
                    relpath: {
                        "type": _entry_type(relpath),
                        "size": len(data),
                        "hash": _sha(data),
                    }
                    for relpath, data in files.items()
                },
            }
        manifest_raw = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    members: list[tuple[str, bytes]] = [(MANIFEST_FILENAME, manifest_raw)]
    members.extend(files.items())
    members.extend(extra_members or [])
    with zipfile.ZipFile(archive_path, "w") as archive:
        for arcname, data in members:
            archive.writestr(
                arcname,
                data,
                compress_type=zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED,
            )


def _make_container_dir(tmp_path: Path, *, name: str = "Alpha") -> Path:
    directory = tmp_path / "proj"
    with create_open_directory_project(
        directory,
        name=name,
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ):
        pass
    return directory


def _refresh_manifest(directory: Path) -> None:
    """Rewrite the manifest from the current database and declared attachments."""
    db_path = directory / DATABASE_FILENAME
    entries = [compute_entry(DATABASE_FILENAME, db_path, entry_type=CRITICAL_ENTRY_TYPE)]
    for entry in directory.rglob("*"):
        if entry.is_file() and entry.name != MANIFEST_FILENAME and entry != db_path:
            relpath = entry.relative_to(directory).as_posix()
            entries.append(compute_entry(relpath, entry, entry_type=ATTACHMENT_ENTRY_TYPE))
    write_manifest(directory, ManifestInfo(MANIFEST_FORMAT_VERSION, 1, APP_VERSION, tuple(entries)))


def _pack_directory(directory: Path, archive_path: Path) -> None:
    """Pack a directory's current files into an archive with a refreshed manifest."""
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{directory / DATABASE_FILENAME}{suffix}")
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass
    _refresh_manifest(directory)
    write_archive(directory, archive_path)


def _real_archive(
    tmp_path: Path,
    *,
    name: str = "Alpha",
    attachments: tuple[tuple[str, bytes], ...] = (),
) -> Path:
    directory = _make_container_dir(tmp_path, name=name)
    for relpath, content in attachments:
        path = directory / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _refresh_manifest(directory)
    archive_path = tmp_path / "out.aiproject"
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    return archive_path


def _import(
    archive_path: Path,
    staging_dir: Path,
    *,
    limits: ArchiveLimits | None = None,
) -> Path:
    return import_archive_to_staging(archive_path, staging_dir, limits=limits)


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


def test_import_produces_same_contract_open_directory(tmp_path: Path) -> None:
    """A valid archive imports to a staging container that reopens as the Project."""
    archive = _real_archive(
        tmp_path,
        name="持久项目",
        attachments=(("attachments/notes.txt", b"hello world"),),
    )
    staging = tmp_path / "staging"
    _import(archive, staging)
    files = {p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()}
    assert files == {MANIFEST_FILENAME, DATABASE_FILENAME, "attachments/notes.txt"}
    with open_open_directory_project(staging, app_version=APP_VERSION) as container:
        assert container.project.name == "持久项目"
        assert container.project.id is not None
        assert {e.relpath for e in container.manifest.entries} == {
            DATABASE_FILENAME,
            "attachments/notes.txt",
        }


def test_import_preserves_attachment_subtree_and_bytes(tmp_path: Path) -> None:
    """Nested attachment paths and their bytes survive the import unchanged."""
    archive = _real_archive(
        tmp_path,
        attachments=(("attachments/translation/config.json", b'{"k": 1}'),),
    )
    staging = tmp_path / "staging"
    _import(archive, staging)
    assert (staging / "attachments/translation/config.json").read_bytes() == b'{"k": 1}'


def test_import_staging_is_isolated_and_clean(tmp_path: Path) -> None:
    """Staging holds only declared entries: no sidecars, temp, or backup files."""
    archive = _real_archive(tmp_path, attachments=(("attachments/notes.txt", b"hello"),))
    staging = tmp_path / "staging"
    _import(archive, staging)
    names = sorted(p.name for p in staging.iterdir())
    assert names == ["attachments", MANIFEST_FILENAME, DATABASE_FILENAME]
    leftovers = [
        p
        for p in staging.rglob("*")
        if p.name.endswith(("-wal", "-shm")) or ".tmp" in p.name or ".bak" in p.name
    ]
    assert leftovers == []


def test_import_into_existing_empty_staging_dir(tmp_path: Path) -> None:
    """A pre-existing empty staging directory is accepted."""
    archive = _real_archive(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    _import(archive, staging)
    assert (staging / MANIFEST_FILENAME).is_file()


def test_import_accepts_wellformed_handbuilt_archive(tmp_path: Path) -> None:
    """A well-formed archive not produced by our exporter also imports."""
    db_path = tmp_path / "db.sqlite"
    _make_valid_db(db_path, name="Hand")
    archive_path = tmp_path / "hand.aiproject"
    _write_archive(
        archive_path,
        {
            DATABASE_FILENAME: db_path.read_bytes(),
            "attachments/a.txt": b"x" * 100,
        },
    )
    staging = tmp_path / "staging"
    _import(archive_path, staging, limits=ArchiveLimits(max_entries=10))
    with open_open_directory_project(staging, app_version=APP_VERSION) as container:
        assert container.project.name == "Hand"
        assert (staging / "attachments/a.txt").read_bytes() == b"x" * 100


def test_import_accepts_compressible_attachment_with_default_limits(tmp_path: Path) -> None:
    """A legitimately highly-compressible attachment is not a false-positive bomb."""
    archive = _real_archive(tmp_path, attachments=(("attachments/repeated.txt", b"A" * 20000),))
    staging = tmp_path / "staging"
    _import(archive, staging)
    assert (staging / "attachments/repeated.txt").read_bytes() == b"A" * 20000


# ---------------------------------------------------------------------------
# Archive / staging orchestration rejections
# ---------------------------------------------------------------------------


def test_import_rejects_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(ArchiveImportError, match="does not exist"):
        _import(tmp_path / "nope.aiproject", tmp_path / "staging")


def test_import_rejects_non_empty_staging(tmp_path: Path) -> None:
    archive = _real_archive(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "precious.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ArchiveImportError, match="not empty"):
        _import(archive, staging)
    assert (staging / "precious.txt").read_text(encoding="utf-8") == "keep me"


def test_import_rejects_not_a_zip(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad.aiproject"
    archive_path.write_bytes(b"this is not a zip file")
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveError):
        _import(archive_path, staging)
    assert not staging.exists()


def test_import_rejects_archive_without_manifest(tmp_path: Path) -> None:
    archive_path = tmp_path / "nomanifest.aiproject"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(DATABASE_FILENAME, b"placeholder")
    staging = tmp_path / "staging"
    with pytest.raises(ManifestError, match="missing"):
        _import(archive_path, staging)
    assert not staging.exists()


def test_import_rejects_invalid_manifest_json(tmp_path: Path) -> None:
    archive_path = tmp_path / "badmanifest.aiproject"
    _write_archive(archive_path, {DATABASE_FILENAME: b"placeholder"}, manifest_raw=b"{not json")
    with pytest.raises(ManifestError, match="not valid JSON"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_duplicate_manifest_key(tmp_path: Path) -> None:
    hash_part = "sha256:" + "0" * 64
    manifest = (
        '{"format_version":1,"schema_version":1,"software":"0.1.0",'
        '"files":{"' + DATABASE_FILENAME + '":{"type":"database","size":11,"hash":"'
        + hash_part + '"}},"files":{}}'
    ).encode("utf-8")
    archive_path = tmp_path / "dupkey.aiproject"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(MANIFEST_FILENAME, manifest)
    with pytest.raises(ManifestError, match="duplicate key"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_unknown_format_version(tmp_path: Path) -> None:
    manifest = {
        "format_version": 2,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {
            DATABASE_FILENAME: {"type": "database", "size": 1, "hash": "sha256:" + "0" * 64},
        },
    }
    archive_path = tmp_path / "fmt.aiproject"
    _write_archive(archive_path, {DATABASE_FILENAME: b"x"}, manifest=manifest)
    with pytest.raises(ManifestError, match="format_version"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_unknown_schema_version(tmp_path: Path) -> None:
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 2,
        "software": APP_VERSION,
        "files": {
            DATABASE_FILENAME: {"type": "database", "size": 1, "hash": "sha256:" + "0" * 64},
        },
    }
    archive_path = tmp_path / "schema.aiproject"
    _write_archive(archive_path, {DATABASE_FILENAME: b"x"}, manifest=manifest)
    with pytest.raises(ManifestError, match="schema_version"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_oversized_manifest(tmp_path: Path) -> None:
    raw = (
        b'{"format_version":1,"schema_version":1,"software":"0.1.0","files":{},"padding":"'
        + b"a" * (1024 * 1024)
        + b'"}'
    )
    archive_path = tmp_path / "bigmanifest.aiproject"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(MANIFEST_FILENAME, raw)
    with pytest.raises(ManifestError, match="manifest is"):
        _import(archive_path, tmp_path / "staging")


# ---------------------------------------------------------------------------
# Tamper / missing attachment / undeclared members
# ---------------------------------------------------------------------------


def test_import_rejects_declared_but_missing_attachment(tmp_path: Path) -> None:
    files = {DATABASE_FILENAME: b"placeholder"}
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {
            DATABASE_FILENAME: {
                "type": "database",
                "size": len(files[DATABASE_FILENAME]),
                "hash": _sha(files[DATABASE_FILENAME]),
            },
            "attachments/notes.txt": {
                "type": "attachment",
                "size": 5,
                "hash": "sha256:" + "0" * 64,
            },
        },
    }
    archive_path = tmp_path / "missing.aiproject"
    _write_archive(archive_path, files, manifest=manifest)
    with pytest.raises(FileIntegrityError, match="does not contain"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_tampered_entry(tmp_path: Path) -> None:
    """A member whose content no longer matches the manifest hash is rejected."""
    declared = b"hello wor"
    actual = b"tamperedX"
    files = {DATABASE_FILENAME: b"placeholder", "attachments/notes.txt": actual}
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {
            DATABASE_FILENAME: {
                "type": "database",
                "size": len(files[DATABASE_FILENAME]),
                "hash": _sha(files[DATABASE_FILENAME]),
            },
            "attachments/notes.txt": {
                "type": "attachment",
                "size": len(declared),
                "hash": _sha(declared),
            },
        },
    }
    archive_path = tmp_path / "tampered.aiproject"
    _write_archive(archive_path, files, manifest=manifest)
    staging = tmp_path / "staging"
    with pytest.raises(FileIntegrityError, match="hash mismatch"):
        _import(archive_path, staging)
    assert not staging.exists()


def test_import_rejects_undeclared_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "extra.aiproject"
    _write_archive(
        archive_path,
        {DATABASE_FILENAME: b"placeholder"},
        extra_members=[("secret.txt", b"do not import")],
    )
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveError, match="not declared"):
        _import(archive_path, staging)
    assert not staging.exists()


def test_import_rejects_duplicate_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "dup.aiproject"
    manifest = json.dumps(
        {
            "format_version": MANIFEST_FORMAT_VERSION,
            "schema_version": 1,
            "software": APP_VERSION,
            "files": {
                DATABASE_FILENAME: {"type": "database", "size": 1, "hash": "sha256:" + "0" * 64},
            },
        },
    ).encode("utf-8")
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(MANIFEST_FILENAME, manifest)
            archive.writestr(MANIFEST_FILENAME, b"again")
    with pytest.raises(ArchiveError, match="duplicate"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_directory_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "dirmember.aiproject"
    _write_archive(
        archive_path,
        {DATABASE_FILENAME: b"placeholder"},
        extra_members=[("attachments/", b"")],
    )
    with pytest.raises(ArchiveError, match="not declared"):
        _import(archive_path, tmp_path / "staging")


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------


def test_import_rejects_traversal_entry(tmp_path: Path) -> None:
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {"../evil.txt": {"type": "attachment", "size": 1, "hash": "sha256:" + "0" * 64}},
    }
    archive_path = tmp_path / "traversal.aiproject"
    _write_archive(archive_path, {}, manifest=manifest)
    with pytest.raises(PathValidationError):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_absolute_or_drive_path(tmp_path: Path) -> None:
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {"C:\\evil.txt": {"type": "attachment", "size": 1, "hash": "sha256:" + "0" * 64}},
    }
    archive_path = tmp_path / "abs.aiproject"
    _write_archive(archive_path, {}, manifest=manifest)
    with pytest.raises(PathValidationError):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_case_collision(tmp_path: Path) -> None:
    files = {
        DATABASE_FILENAME: b"placeholder",
        "attachments/A.txt": b"a",
        "attachments/a.txt": b"b",
    }
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {
            relpath: {"type": _entry_type(relpath), "size": len(data), "hash": _sha(data)}
            for relpath, data in files.items()
        },
    }
    archive_path = tmp_path / "case.aiproject"
    _write_archive(archive_path, files, manifest=manifest)
    with pytest.raises(PathValidationError, match="Duplicate entry"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_unicode_collision(tmp_path: Path) -> None:
    nfc = "attachments/caf\u00e9.txt"
    nfd = "attachments/cafe\u0301.txt"
    files = {DATABASE_FILENAME: b"placeholder", nfc: b"a", nfd: b"b"}
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {
            relpath: {"type": _entry_type(relpath), "size": len(data), "hash": _sha(data)}
            for relpath, data in files.items()
        },
    }
    archive_path = tmp_path / "unicode.aiproject"
    _write_archive(archive_path, files, manifest=manifest)
    with pytest.raises(PathValidationError, match="Duplicate entry"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_manifest_self_alias(tmp_path: Path) -> None:
    files = {DATABASE_FILENAME: b"placeholder"}
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {
            DATABASE_FILENAME: {
                "type": "database",
                "size": len(files[DATABASE_FILENAME]),
                "hash": _sha(files[DATABASE_FILENAME]),
            },
            MANIFEST_FILENAME: {"type": "attachment", "size": 1, "hash": "sha256:" + "0" * 64},
        },
    }
    archive_path = tmp_path / "selfalias.aiproject"
    _write_archive(archive_path, files, manifest=manifest)
    with pytest.raises(PathValidationError, match="aliases the manifest"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_undeclared_traversal_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "extratraversal.aiproject"
    _write_archive(
        archive_path,
        {DATABASE_FILENAME: b"placeholder"},
        extra_members=[("../evil.txt", b"x")],
    )
    with pytest.raises(ArchiveError, match="not declared"):
        _import(archive_path, tmp_path / "staging")


# ---------------------------------------------------------------------------
# Resource limits (zip-bomb / exhaustion)
# ---------------------------------------------------------------------------


def test_import_rejects_too_many_entries(tmp_path: Path) -> None:
    files = {DATABASE_FILENAME: b"placeholder"}
    for i in range(3):
        files[f"attachments/f{i}.txt"] = b"x"
    archive_path = tmp_path / "many.aiproject"
    _write_archive(archive_path, files)
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveLimitError, match="members"):
        _import(archive_path, staging, limits=ArchiveLimits(max_entries=3))
    assert not staging.exists()


def test_import_rejects_entry_over_per_entry_limit(tmp_path: Path) -> None:
    archive_path = tmp_path / "bigentry.aiproject"
    _write_archive(
        archive_path,
        {DATABASE_FILENAME: b"placeholder", "attachments/big.txt": b"z" * 20},
    )
    with pytest.raises(ArchiveLimitError, match="per-entry"):
        _import(
            archive_path,
            tmp_path / "staging",
            limits=ArchiveLimits(max_entry_size=10),
        )


def test_import_rejects_total_over_limit(tmp_path: Path) -> None:
    archive_path = tmp_path / "bigtotal.aiproject"
    _write_archive(
        archive_path,
        {DATABASE_FILENAME: b"x" * 40, "attachments/a.txt": b"y" * 10},
    )
    with pytest.raises(ArchiveLimitError, match="Total"):
        _import(
            archive_path,
            tmp_path / "staging",
            limits=ArchiveLimits(max_total_size=30, max_entry_size=100),
        )


def test_import_rejects_high_compression_ratio(tmp_path: Path) -> None:
    """A deflated member that expands far beyond its stored size is a bomb."""
    archive_path = tmp_path / "bomb.aiproject"
    _write_archive(
        archive_path,
        {DATABASE_FILENAME: b"placeholder", "attachments/bomb.txt": b"A" * 20000},
        compress=True,
    )
    with pytest.raises(ArchiveLimitError, match="compression ratio"):
        _import(
            archive_path,
            tmp_path / "staging",
            limits=ArchiveLimits(max_compression_ratio=50.0),
        )


# ---------------------------------------------------------------------------
# Database identity
# ---------------------------------------------------------------------------


def test_import_rejects_db_with_zero_projects(tmp_path: Path) -> None:
    directory = _make_container_dir(tmp_path, name="Alpha")
    conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        conn.execute("DELETE FROM projects")
        conn.commit()
    finally:
        conn.close()
    archive_path = tmp_path / "zero.aiproject"
    _pack_directory(directory, archive_path)
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveImportError, match="exactly one Project"):
        _import(archive_path, staging)
    assert not staging.exists()


def test_import_rejects_db_with_multiple_projects(tmp_path: Path) -> None:
    directory = _make_container_dir(tmp_path, name="One")
    conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        conn.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('Two', 'a', 'b')",
        )
        conn.commit()
    finally:
        conn.close()
    archive_path = tmp_path / "multi.aiproject"
    _pack_directory(directory, archive_path)
    with pytest.raises(ArchiveImportError, match="exactly one Project"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_db_schema_mismatch(tmp_path: Path) -> None:
    directory = _make_container_dir(tmp_path, name="Alpha")
    conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        conn.execute("UPDATE projects SET schema_version = 2")
        conn.commit()
    finally:
        conn.close()
    archive_path = tmp_path / "schemamismatch.aiproject"
    _pack_directory(directory, archive_path)
    with pytest.raises(ArchiveImportError, match="schema_version"):
        _import(archive_path, tmp_path / "staging")


def test_import_rejects_db_schema_version_not_an_integer(tmp_path: Path) -> None:
    """A non-numeric schema_version is reported as ArchiveImportError, not ValueError."""
    directory = _make_container_dir(tmp_path, name="Alpha")
    conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        conn.execute("UPDATE projects SET schema_version = 'abc'")
        conn.commit()
    finally:
        conn.close()
    archive_path = tmp_path / "schemabad.aiproject"
    _pack_directory(directory, archive_path)
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveImportError, match="not an integer"):
        _import(archive_path, staging)
    assert not staging.exists()


def test_import_rejects_db_not_a_sqlite_file(tmp_path: Path) -> None:
    directory = _make_container_dir(tmp_path)
    (directory / DATABASE_FILENAME).write_bytes(b"this is not a sqlite database")
    archive_path = tmp_path / "notdb.aiproject"
    _pack_directory(directory, archive_path)
    with pytest.raises(ArchiveImportError, match="database"):
        _import(archive_path, tmp_path / "staging")


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_import_failure_leaves_no_staging_artifacts(tmp_path: Path) -> None:
    """A failure after extraction removes the staging directory it created."""
    db_path = tmp_path / "db.sqlite"
    _make_valid_db(db_path)
    files = {DATABASE_FILENAME: db_path.read_bytes(), "attachments/notes.txt": b"tamperedX"}
    manifest = {
        "format_version": MANIFEST_FORMAT_VERSION,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": {
            DATABASE_FILENAME: {
                "type": "database",
                "size": len(files[DATABASE_FILENAME]),
                "hash": _sha(files[DATABASE_FILENAME]),
            },
            "attachments/notes.txt": {"type": "attachment", "size": 9, "hash": _sha(b"hello wor")},
        },
    }
    archive_path = tmp_path / "fail.aiproject"
    _write_archive(archive_path, files, manifest=manifest)
    staging = tmp_path / "staging"
    with pytest.raises(FileIntegrityError):
        _import(archive_path, staging)
    assert not staging.exists()


def test_import_failure_preserves_existing_empty_staging_dir(tmp_path: Path) -> None:
    """A failure clears extracted files but preserves a pre-existing empty directory."""
    directory = _make_container_dir(tmp_path)
    (directory / DATABASE_FILENAME).write_bytes(b"garbage not sqlite")
    archive_path = tmp_path / "bad.aiproject"
    _pack_directory(directory, archive_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(ArchiveImportError):
        _import(archive_path, staging)
    assert staging.is_dir()
    assert list(staging.iterdir()) == []
