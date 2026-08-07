"""P1-T02-M02: consistent single-file (``.aiproject``) export.

A logical Project is exported from an open-directory container or a bare
active database into a single-file archive that is the archive view of the
container (``04`` §7): a standard ZIP holding ``manifest.json``, a consistent
SQLite snapshot of the database, and any declared attachments. The database is
snapshotted with the SQLite backup API (never a raw copy of an active WAL
database), the manifest declares every entry's size and SHA-256 hash so the
archive is re-verifiable, secrets/logs never enter the package, and a source
holding zero or multiple Projects is rejected rather than silently packaged.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from transrealm.application.archive_service import (
    ArchiveExportError,
    export_database_archive,
    export_open_directory_archive,
)
from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.infrastructure import open_directory as open_directory_module
from transrealm.infrastructure.migrations.backup import create_consistent_snapshot
from transrealm.infrastructure.migrations.errors import MigrationBackupError
from transrealm.infrastructure.open_directory import (
    ATTACHMENT_ENTRY_TYPE,
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_FORMAT_VERSION,
    FileIntegrityError,
    ManifestInfo,
    OpenDirectoryError,
    PathValidationError,
    compute_entry,
    load_manifest,
    write_archive,
    write_manifest,
)

APP_VERSION = "0.1.0"


def _project_dir(tmp_path: Path) -> Path:
    return tmp_path / "proj"


def _create_container(
    tmp_path: Path,
    *,
    name: str = "Alpha",
) -> Path:
    directory = _project_dir(tmp_path)
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


def _add_attachment(
    directory: Path,
    *,
    relpath: str = "attachments/notes.txt",
    content: bytes = b"hello world",
) -> None:
    source = directory / relpath
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    _refresh_manifest(directory)


def _extract(archive_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(dest)


def _archive_names(archive_path: Path) -> list[str]:
    with zipfile.ZipFile(archive_path) as archive:
        return sorted(archive.namelist())


def _archive_bytes(archive_path: Path) -> bytes:
    with zipfile.ZipFile(archive_path) as archive:
        return b"".join(archive.read(name) for name in archive.namelist())


def _db_project_names(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [row[0] for row in conn.execute("SELECT name FROM projects ORDER BY id")]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# export_open_directory_archive — success paths
# ---------------------------------------------------------------------------


def test_export_open_directory_produces_archive_with_all_entries(tmp_path: Path) -> None:
    """The archive is a ZIP holding manifest, snapshot, and declared attachment."""
    directory = _create_container(tmp_path)
    _add_attachment(directory, relpath="attachments/notes.txt", content=b"hello world")
    archive_path = tmp_path / "out.aiproject"
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    assert archive_path.is_file()
    assert _archive_names(archive_path) == [
        "attachments/notes.txt",
        MANIFEST_FILENAME,
        DATABASE_FILENAME,
    ]


def test_export_archive_manifest_hash_reverifiable(tmp_path: Path) -> None:
    """The archive manifest's size/hash match the extracted files byte-for-byte."""
    directory = _create_container(tmp_path)
    _add_attachment(directory, relpath="attachments/sub/notes.txt", content=b"\x00\x01nested")
    archive_path = tmp_path / "out.aiproject"
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    unpacked = tmp_path / "unpacked"
    _extract(archive_path, unpacked)
    manifest = load_manifest(unpacked)
    for entry in manifest.entries:
        path = unpacked / entry.relpath
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert path.stat().st_size == entry.size
        assert digest == entry.hash
        assert entry.type in {CRITICAL_ENTRY_TYPE, ATTACHMENT_ENTRY_TYPE}


def test_export_roundtrip_reopens_as_open_directory(tmp_path: Path) -> None:
    """An extracted archive is itself a valid open-directory container."""
    directory = _create_container(tmp_path, name="持久项目")
    _add_attachment(directory, relpath="attachments/notes.txt")
    with open_open_directory_project(directory, app_version=APP_VERSION) as source:
        project_id = source.project.id
    archive_path = tmp_path / "out.aiproject"
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    unpacked = tmp_path / "unpacked"
    _extract(archive_path, unpacked)
    with open_open_directory_project(unpacked, app_version=APP_VERSION) as reopened:
        assert reopened.project.id == project_id
        assert reopened.project.name == "持久项目"
        assert {e.relpath for e in reopened.manifest.entries} == {
            "attachments/notes.txt",
            DATABASE_FILENAME,
        }


def test_export_preserves_attachment_subdirectory(tmp_path: Path) -> None:
    """Nested attachment paths survive the archive unchanged."""
    directory = _create_container(tmp_path)
    _add_attachment(directory, relpath="attachments/translation/config.json", content=b'{"k": 1}')
    archive_path = tmp_path / "out.aiproject"
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    unpacked = tmp_path / "unpacked"
    _extract(archive_path, unpacked)
    assert (unpacked / "attachments/translation/config.json").read_bytes() == b'{"k": 1}'


def test_export_overwrites_existing_target_atomically(tmp_path: Path) -> None:
    """A successful export replaces an existing target archive."""
    directory = _create_container(tmp_path)
    archive_path = tmp_path / "out.aiproject"
    archive_path.write_bytes(b"old sentinel")
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    data = archive_path.read_bytes()
    assert data.startswith(b"PK")  # valid zip magic, not the sentinel
    assert b"old sentinel" not in data


# ---------------------------------------------------------------------------
# export_open_directory_archive — secret/log exclusion
# ---------------------------------------------------------------------------


def test_export_excludes_undeclared_log_and_secret_files(tmp_path: Path) -> None:
    """Only manifest-declared entries enter the archive; logs/secrets do not."""
    directory = _create_container(tmp_path)
    _add_attachment(directory, relpath="attachments/notes.txt", content=b"hello")
    (directory / "app.log").write_text("debug noise", encoding="utf-8")
    (directory / "debug").mkdir()
    (directory / "debug" / "trace.txt").write_text("trace", encoding="utf-8")
    (directory / "credentials.json").write_text(
        json.dumps({"api_key": "sk-testsecret123"}),
        encoding="utf-8",
    )
    archive_path = tmp_path / "out.aiproject"
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    names = _archive_names(archive_path)
    assert names == ["attachments/notes.txt", MANIFEST_FILENAME, DATABASE_FILENAME]
    assert b"sk-testsecret123" not in _archive_bytes(archive_path)


def test_export_archive_keeps_only_credential_reference(tmp_path: Path) -> None:
    """The packaged database holds references, never raw credential values."""
    directory = _create_container(tmp_path)
    db_path = directory / DATABASE_FILENAME
    with ProviderConnectionService(db_path, app_version=APP_VERSION) as service:
        service.create_connection(
            name="openai",
            provider_type="openai-compatible",
            endpoint="https://example.invalid/v1",
            credential_reference="env:OPENAI_API_KEY",
        )
    _refresh_manifest(directory)
    archive_path = tmp_path / "out.aiproject"
    export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    assert b"sk-liveSecret" not in _archive_bytes(archive_path)
    unpacked = tmp_path / "unpacked"
    _extract(archive_path, unpacked)
    conn = sqlite3.connect(str(unpacked / DATABASE_FILENAME))
    try:
        row = conn.execute(
            "SELECT credential_reference FROM provider_connections WHERE name='openai'",
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "env:OPENAI_API_KEY"


# ---------------------------------------------------------------------------
# export_open_directory_archive — consistency (WAL)
# ---------------------------------------------------------------------------


def test_export_snapshot_excludes_uncommitted_wal_data(tmp_path: Path) -> None:
    """An in-flight uncommitted transaction is not visible in the snapshot."""
    directory = _create_container(tmp_path, name="Orig")
    raw = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        raw.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('Draft', 'x', 'y')",
        )  # deliberately not committed
        archive_path = tmp_path / "out.aiproject"
        export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
        unpacked = tmp_path / "unpacked"
        _extract(archive_path, unpacked)
        assert _db_project_names(unpacked / DATABASE_FILENAME) == ["Orig"]
    finally:
        raw.rollback()
        raw.close()


def test_export_snapshot_includes_committed_wal_data(tmp_path: Path) -> None:
    """Committed data living in the WAL is folded into the snapshot."""
    directory = _create_container(tmp_path, name="Orig")
    raw = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        raw.execute("UPDATE projects SET name='Renamed' WHERE name='Orig'")
        raw.commit()
        # Connection stays open so the committed row lives in the WAL.
        archive_path = tmp_path / "out.aiproject"
        export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
        unpacked = tmp_path / "unpacked"
        _extract(archive_path, unpacked)
        assert _db_project_names(unpacked / DATABASE_FILENAME) == ["Renamed"]
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# export_open_directory_archive — rejection / atomicity
# ---------------------------------------------------------------------------


def test_export_rejects_tampered_container(tmp_path: Path) -> None:
    """A modified attachment is caught by manifest hash verification."""
    directory = _create_container(tmp_path)
    _add_attachment(directory, relpath="attachments/notes.txt", content=b"hello")
    (directory / "attachments/notes.txt").write_bytes(b"tampered")
    with pytest.raises(FileIntegrityError):
        export_open_directory_archive(
            directory,
            tmp_path / "out.aiproject",
            app_version=APP_VERSION,
        )


def test_export_container_with_multiple_projects_rejected(tmp_path: Path) -> None:
    """A container whose database holds multiple Projects is not silently packaged."""
    directory = _create_container(tmp_path)
    raw = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        raw.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('Two', 'a', 'b')",
        )
        raw.commit()
    finally:
        raw.close()
    _refresh_manifest(directory)
    with pytest.raises(OpenDirectoryError, match="exactly one Project"):
        export_open_directory_archive(
            directory,
            tmp_path / "out.aiproject",
            app_version=APP_VERSION,
        )
    assert not (tmp_path / "out.aiproject").exists()


def test_export_missing_directory_rejected(tmp_path: Path) -> None:
    with pytest.raises(OpenDirectoryError):
        export_open_directory_archive(
            tmp_path / "missing",
            tmp_path / "out.aiproject",
            app_version=APP_VERSION,
        )


def test_export_missing_target_directory_rejected(tmp_path: Path) -> None:
    directory = _create_container(tmp_path)
    with pytest.raises(OpenDirectoryError, match="target directory"):
        export_open_directory_archive(
            directory,
            tmp_path / "nope" / "out.aiproject",
            app_version=APP_VERSION,
        )


def test_export_failure_leaves_no_partial_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated archive failure")

    monkeypatch.setattr("transrealm.application.archive_service.write_archive", boom)
    directory = _create_container(tmp_path)
    archive_path = tmp_path / "out.aiproject"
    with pytest.raises(RuntimeError):
        export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    assert not archive_path.exists()


def test_export_failure_preserves_existing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated archive failure")

    monkeypatch.setattr("transrealm.application.archive_service.write_archive", boom)
    directory = _create_container(tmp_path)
    archive_path = tmp_path / "out.aiproject"
    archive_path.write_bytes(b"precious existing archive")
    with pytest.raises(RuntimeError):
        export_open_directory_archive(directory, archive_path, app_version=APP_VERSION)
    assert archive_path.read_bytes() == b"precious existing archive"


# ---------------------------------------------------------------------------
# export_database_archive — bare active database
# ---------------------------------------------------------------------------


def test_export_bare_database_produces_container(tmp_path: Path) -> None:
    """A bare database exports to a container with only the database entry."""
    db_path = tmp_path / "bare.sqlite"
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="Bare",
            source_language="en",
            target_language="ja",
        )
    archive_path = tmp_path / "bare.aiproject"
    export_database_archive(db_path, archive_path, app_version=APP_VERSION)
    assert _archive_names(archive_path) == [MANIFEST_FILENAME, DATABASE_FILENAME]
    unpacked = tmp_path / "unpacked"
    _extract(archive_path, unpacked)
    manifest = load_manifest(unpacked)
    (entry,) = manifest.entries
    assert entry.relpath == DATABASE_FILENAME
    assert entry.type == CRITICAL_ENTRY_TYPE
    assert entry.hash == "sha256:" + hashlib.sha256(
        (unpacked / DATABASE_FILENAME).read_bytes(),
    ).hexdigest()
    with open_open_directory_project(unpacked, app_version=APP_VERSION) as reopened:
        assert reopened.project.id == project.id
        assert reopened.project.name == "Bare"


def test_export_bare_database_rejects_empty_database(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"
    with ProjectService(db_path, app_version=APP_VERSION):
        pass
    with pytest.raises(ArchiveExportError, match="exactly one Project"):
        export_database_archive(db_path, tmp_path / "empty.aiproject", app_version=APP_VERSION)
    assert not (tmp_path / "empty.aiproject").exists()


def test_export_bare_database_rejects_multiple_projects(tmp_path: Path) -> None:
    db_path = tmp_path / "multi.sqlite"
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        service.create_project(name="One", source_language="a", target_language="b")
        service.create_project(name="Two", source_language="c", target_language="d")
    with pytest.raises(ArchiveExportError, match="exactly one Project"):
        export_database_archive(db_path, tmp_path / "multi.aiproject", app_version=APP_VERSION)
    assert not (tmp_path / "multi.aiproject").exists()


def test_export_bare_database_wal_committed_included(tmp_path: Path) -> None:
    """The bare active-database path also snapshots committed WAL data."""
    db_path = tmp_path / "wal.sqlite"
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        service.create_project(name="Orig", source_language="a", target_language="b")
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("UPDATE projects SET name='Renamed' WHERE name='Orig'")
        raw.commit()
        archive_path = tmp_path / "wal.aiproject"
        export_database_archive(db_path, archive_path, app_version=APP_VERSION)
        unpacked = tmp_path / "unpacked"
        _extract(archive_path, unpacked)
        assert _db_project_names(unpacked / DATABASE_FILENAME) == ["Renamed"]
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# shared snapshot / archive mechanics (independent review hardening)
# ---------------------------------------------------------------------------


def test_create_consistent_snapshot_failure_cleans_up_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed snapshot never leaves a partial target file behind."""
    from transrealm.infrastructure.migrations import backup as backup_module

    db_path = tmp_path / "src.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE sample (x INTEGER)")
        conn.commit()
    finally:
        conn.close()

    class _FakeConnection:
        def __init__(self, path: Path) -> None:
            Path(path).touch()  # simulating sqlite creating a partial target

        def backup(self, dest: object) -> None:
            raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            pass

        def __enter__(self) -> _FakeConnection:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    class _FakeSqlite3:
        Error = sqlite3.Error
        OperationalError = sqlite3.OperationalError

        def connect(self, path: str) -> _FakeConnection:
            return _FakeConnection(Path(path))

    monkeypatch.setattr(backup_module, "sqlite3", _FakeSqlite3())
    target = tmp_path / "snap.sqlite"
    with pytest.raises(MigrationBackupError):
        backup_module.create_consistent_snapshot(db_path, target)
    assert not target.exists()


def test_create_consistent_snapshot_missing_source_rejected(tmp_path: Path) -> None:
    """A missing source database is rejected and no target is created."""
    target = tmp_path / "snap.sqlite"
    with pytest.raises(MigrationBackupError, match="does not exist"):
        create_consistent_snapshot(tmp_path / "nope.sqlite", target)
    assert not target.exists()


def test_write_archive_target_directory_rejected(tmp_path: Path) -> None:
    """Writing over an existing directory raises OpenDirectoryError, not a raw OSError."""
    directory = _create_container(tmp_path)
    target = tmp_path / "out.aiproject"
    target.mkdir()
    with pytest.raises(OpenDirectoryError):
        write_archive(directory, target)
    assert target.is_dir()
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f".{target.name}.")]
    assert leftovers == []


def test_write_archive_refuses_link_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A link entry is refused before its target is ever traversed."""
    directory = _create_container(tmp_path)
    (directory / "secret.txt").write_text("sensitive", encoding="utf-8")
    real_is_link = open_directory_module.is_link

    def fake_is_link(path: Path) -> bool:
        if path.name == "secret.txt":
            return True
        return real_is_link(path)

    monkeypatch.setattr(open_directory_module, "is_link", fake_is_link)
    with pytest.raises(PathValidationError, match="link"):
        write_archive(directory, tmp_path / "out.aiproject")
    assert not (tmp_path / "out.aiproject").exists()
