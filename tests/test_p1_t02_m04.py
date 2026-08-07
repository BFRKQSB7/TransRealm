"""P1-T02-M04: forward migration and atomic install of project containers.

A Project container (open directory or the M03 staging snapshot) is backed up,
forward-migrated, and validated before it is installed/opened as the new target
(``04`` §7, ``03`` §3). Version, permission, space, migration, and name-conflict
failures preserve the original target and leave recovery artifacts. A Project ID
conflict creates a new local identity while the manifest keeps the source/origin
ID for tracking; a name conflict suggests a deterministic-suffix name and never
overwrites an existing Project without explicit confirmation.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from transrealm.application.archive_service import import_archive_to_staging
from transrealm.application.install_service import (
    InstallError,
    TargetConflictError,
    install_staging_to_target,
    migrate_container,
)
from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.errors import (
    MigrationBackupError,
    MigrationExecutionError,
)
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.open_directory import (
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_FORMAT_VERSION,
    ManifestError,
    ManifestInfo,
    compute_entry,
    load_manifest,
    write_archive,
    write_manifest,
)

APP_VERSION = "0.1.0"
_MIGRATION_008 = "008_add_format_fidelity"


def _apply_old_migrations(db_path: Path) -> None:
    """Apply migrations 001-007 only, simulating an older app version."""
    migs = discover_migrations(ProjectService.MIGRATIONS_DIR)
    old = [m for m in migs if m.migration_id != _MIGRATION_008]
    db = create_database(db_path)
    try:
        runner = MigrationRunner(db)
        runner.apply(old, app_version=APP_VERSION)
    finally:
        db.close()


def _checkpoint_clean(db_path: Path) -> None:
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        raw.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _make_old_schema_db(
    db_path: Path,
    *,
    name: str,
    source_language: str = "zh",
    with_data: bool = False,
) -> int:
    """Create a database with only 001-007 applied plus one Project.

    Returns the inserted Project id.
    """
    _apply_old_migrations(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.execute(
            "INSERT INTO projects (name, source_language, target_language, schema_version) "
            "VALUES (?, ?, 'en', 1)",
            (name, source_language),
        )
        if cur.lastrowid is None:
            raise AssertionError("inserted project id was not assigned")
        project_id = int(cur.lastrowid)
        if with_data:
            doc = conn.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 'src.txt', 'txt', 'utf-8', 'hash', '1.0.0')",
                (project_id,),
            )
            conn.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence, status) "
                "VALUES (?, 'key-1', 'Hello', 0, 'pending')",
                (doc.lastrowid,),
            )
        conn.commit()
    finally:
        conn.close()
    _checkpoint_clean(db_path)
    return project_id


def _make_old_schema_container(
    tmp_path: Path,
    *,
    name: str = "Alpha",
    source_language: str = "zh",
    with_data: bool = False,
) -> Path:
    """Build an old-schema open-directory container (manifest + old DB)."""
    directory = tmp_path / "proj"
    directory.mkdir(parents=True, exist_ok=True)
    _make_old_schema_db(
        tmp_path / "old.sqlite",
        name=name,
        source_language=source_language,
        with_data=with_data,
    )
    shutil.move(str(tmp_path / "old.sqlite"), str(directory / DATABASE_FILENAME))
    entry = compute_entry(
        DATABASE_FILENAME,
        directory / DATABASE_FILENAME,
        entry_type=CRITICAL_ENTRY_TYPE,
    )
    write_manifest(directory, ManifestInfo(MANIFEST_FORMAT_VERSION, 1, APP_VERSION, (entry,)))
    return directory


def _make_current_container(
    tmp_path: Path,
    *,
    name: str = "Alpha",
    source_language: str = "zh",
) -> Path:
    directory = tmp_path / "proj"
    with create_open_directory_project(
        directory,
        name=name,
        source_language=source_language,
        target_language="en",
        app_version=APP_VERSION,
    ):
        pass
    return directory


def _migrated_ids(directory: Path) -> list[str]:
    conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        rows = conn.execute(
            "SELECT migration_id FROM schema_migrations ORDER BY migration_id",
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _archive_from(directory: Path, archive_path: Path) -> Path:
    """Pack a container's current files (including its manifest) into an archive."""
    write_archive(directory, archive_path)
    return archive_path


def _import_to_staging(archive_path: Path, staging_dir: Path) -> Path:
    return import_archive_to_staging(archive_path, staging_dir)


# ---------------------------------------------------------------------------
# Open-directory forward migration (in-place)
# ---------------------------------------------------------------------------


def test_open_migrates_old_schema_container_and_stays_clean(tmp_path: Path) -> None:
    """Opening an old-schema container migrates it and leaves a clean container."""
    directory = _make_old_schema_container(tmp_path, name="Alpha")
    with open_open_directory_project(directory, app_version=APP_VERSION) as container:
        assert container.project.name == "Alpha"
    assert _MIGRATION_008 in _migrated_ids(directory)
    names = sorted(p.name for p in directory.iterdir())
    assert names == [MANIFEST_FILENAME, DATABASE_FILENAME]
    leftovers = [
        p.name
        for p in directory.rglob("*")
        if p.name.endswith(("-wal", "-shm")) or ".bak" in p.name or ".tmp" in p.name
    ]
    assert leftovers == []


def test_open_migrated_old_schema_can_reopen(tmp_path: Path) -> None:
    """Regression: a migrated container must not carry a stale manifest that
    fails the next open's hash check."""
    directory = _make_old_schema_container(tmp_path, name="Alpha")
    for _ in range(2):
        with open_open_directory_project(directory, app_version=APP_VERSION) as container:
            assert container.project.name == "Alpha"


def test_open_migration_preserves_project_data(tmp_path: Path) -> None:
    """Segments and source documents survive the forward migration."""
    directory = _make_old_schema_container(tmp_path, name="Alpha", with_data=True)
    conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM segments JOIN source_documents ON "
            "segments.source_document_id = source_documents.id",
        ).fetchone()[0]
    finally:
        conn.close()
    assert before == 1
    with open_open_directory_project(directory, app_version=APP_VERSION):
        pass
    conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        after = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        text = conn.execute("SELECT source_text FROM segments").fetchone()[0]
    finally:
        conn.close()
    assert after == 1
    assert text == "Hello"


def test_open_current_container_is_not_migrated_or_dirtied(tmp_path: Path) -> None:
    """A same-schema container opens without creating backups or rewriting files."""
    directory = _make_current_container(tmp_path)
    with open_open_directory_project(directory, app_version=APP_VERSION):
        pass
    assert sorted(p.name for p in directory.iterdir()) == [MANIFEST_FILENAME, DATABASE_FILENAME]


def test_migrate_container_is_noop_on_current(tmp_path: Path) -> None:
    """migrate_container on a current container applies nothing and keeps files."""
    directory = _make_current_container(tmp_path)
    manifest_before = load_manifest(directory)
    migrate_container(directory, app_version=APP_VERSION)
    manifest_after = load_manifest(directory)
    assert manifest_before.entries == manifest_after.entries
    assert sorted(p.name for p in directory.iterdir()) == [
        MANIFEST_FILENAME,
        DATABASE_FILENAME,
    ]


def test_open_migration_execution_failure_preserves_container_and_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing migration leaves the old DB intact plus a recovery backup."""
    directory = _make_old_schema_container(tmp_path, name="Alpha")

    def _fail(_self: object, _migration: object, *, app_version: str) -> None:
        raise MigrationExecutionError(
            "injected failure",
            path=Path("x"),
            migration_id=_MIGRATION_008,
        )

    monkeypatch.setattr(MigrationRunner, "_apply_single", _fail)
    with pytest.raises(MigrationExecutionError, match="injected failure"):
        open_open_directory_project(directory, app_version=APP_VERSION)
    monkeypatch.undo()
    assert _MIGRATION_008 not in _migrated_ids(directory)
    backups = list(directory.glob("*.pre-upgrade-*.db.bak"))
    assert len(backups) == 1


def test_open_migration_backup_failure_blocks_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the pre-upgrade backup cannot be created, migration never starts."""
    directory = _make_old_schema_container(tmp_path, name="Alpha")

    def _fail(_self: object) -> None:
        raise MigrationBackupError("cannot backup", path=Path("x"))

    monkeypatch.setattr(MigrationRunner, "_create_backup", _fail)
    with pytest.raises(MigrationBackupError):
        open_open_directory_project(directory, app_version=APP_VERSION)
    monkeypatch.undo()
    assert _MIGRATION_008 not in _migrated_ids(directory)


def test_migration_cleanup_failure_keeps_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If manifest regeneration fails after a successful migration, the pre-upgrade
    backup is retained as the container's recovery point (removed only last)."""
    directory = _make_old_schema_container(tmp_path, name="Alpha")
    from transrealm.infrastructure import open_directory as od

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(od, "write_manifest", _fail)
    with pytest.raises(OSError, match="disk full"):
        open_open_directory_project(directory, app_version=APP_VERSION)
    monkeypatch.undo()
    assert _MIGRATION_008 in _migrated_ids(directory)
    backups = list(directory.glob("*.pre-upgrade-*.db.bak"))
    assert len(backups) == 1


# ---------------------------------------------------------------------------
# Atomic install (staging -> target)
# ---------------------------------------------------------------------------


def test_install_migrates_old_archive_to_fresh_target(tmp_path: Path) -> None:
    """An old-schema archive imports to staging and installs as a migrated container."""
    directory = _make_old_schema_container(tmp_path, name="Alpha")
    archive = _archive_from(directory, tmp_path / "old.aiproject")
    staging = tmp_path / "staging"
    _import_to_staging(archive, staging)
    target = tmp_path / "installed"
    install_staging_to_target(staging, target, app_version=APP_VERSION)
    assert _MIGRATION_008 in _migrated_ids(target)
    with open_open_directory_project(target, app_version=APP_VERSION) as container:
        assert container.project.name == "Alpha"
    assert sorted(p.name for p in target.iterdir()) == [MANIFEST_FILENAME, DATABASE_FILENAME]


def test_install_into_existing_empty_target(tmp_path: Path) -> None:
    directory = _make_old_schema_container(tmp_path, name="Alpha")
    archive = _archive_from(directory, tmp_path / "old.aiproject")
    staging = tmp_path / "staging"
    _import_to_staging(archive, staging)
    target = tmp_path / "installed"
    target.mkdir()
    install_staging_to_target(staging, target, app_version=APP_VERSION)
    with open_open_directory_project(target, app_version=APP_VERSION) as container:
        assert container.project.name == "Alpha"


def test_install_records_source_id_in_manifest(tmp_path: Path) -> None:
    """The installed manifest keeps the source/origin Project id for tracking."""
    directory = _make_old_schema_container(tmp_path, name="Alpha")
    archive = _archive_from(directory, tmp_path / "old.aiproject")
    staging = tmp_path / "staging"
    _import_to_staging(archive, staging)
    conn = sqlite3.connect(str(staging / DATABASE_FILENAME))
    try:
        source_id = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    target = tmp_path / "installed"
    install_staging_to_target(staging, target, app_version=APP_VERSION)
    manifest = load_manifest(target)
    assert manifest.source_id == source_id
    # The source id survives a reopen and a manifest regeneration.
    with open_open_directory_project(target, app_version=APP_VERSION):
        pass
    assert load_manifest(target).source_id == source_id


def test_install_rejects_non_directory_staging(tmp_path: Path) -> None:
    with pytest.raises(InstallError, match="not a directory"):
        install_staging_to_target(
            tmp_path / "nope.sqlite",
            tmp_path / "target",
            app_version=APP_VERSION,
        )


def test_install_rejects_non_container_staging(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "junk.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ManifestError):
        install_staging_to_target(staging, tmp_path / "target", app_version=APP_VERSION)


def test_install_refuses_non_empty_non_container_target(tmp_path: Path) -> None:
    staging_dir = _make_current_container(tmp_path, name="Alpha")
    target = tmp_path / "target"
    target.mkdir()
    (target / "precious.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(InstallError, match="not empty"):
        install_staging_to_target(staging_dir, target, app_version=APP_VERSION)
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep"


def test_install_refuses_target_with_unsupported_version(tmp_path: Path) -> None:
    """A target whose manifest declares an unsupported schema is never clobbered."""
    target = tmp_path / "target"
    target.mkdir()
    (target / MANIFEST_FILENAME).write_text(
        '{"format_version": 1, "schema_version": 2, "software": "0.1.0", "files": {}}',
        encoding="utf-8",
    )
    (target / DATABASE_FILENAME).write_bytes(b"db")
    staging = _make_current_container(Path(str(tmp_path) + "-staging"), name="Alpha")
    with pytest.raises(InstallError, match="not empty"):
        install_staging_to_target(staging, target, app_version=APP_VERSION)
    assert (target / MANIFEST_FILENAME).is_file()
    assert (target / DATABASE_FILENAME).read_bytes() == b"db"


def test_install_create_failure_is_domain_error_and_preserves_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permission/space failure while preparing the install is a clean error."""
    staging = _make_current_container(tmp_path, name="Alpha")
    target = tmp_path / "target"
    target.mkdir()
    target_entries = sorted(p.name for p in target.iterdir())

    def _fail(*_args: object, **_kwargs: object) -> str:
        raise OSError("disk full")

    monkeypatch.setattr(tempfile, "mkdtemp", _fail)
    with pytest.raises(InstallError, match="install staging area"):
        install_staging_to_target(staging, target, app_version=APP_VERSION)
    monkeypatch.undo()
    assert sorted(p.name for p in target.iterdir()) == target_entries


def test_install_name_conflict_suggests_name_and_refuses(tmp_path: Path) -> None:
    """A same-name Project in the target is never overwritten without confirmation."""
    target = _make_current_container(tmp_path, name="Alpha")
    staging = _make_current_container(Path(str(tmp_path) + "-staging"), name="Alpha")
    with pytest.raises(TargetConflictError) as excinfo:
        install_staging_to_target(staging, target, app_version=APP_VERSION)
    assert excinfo.value.suggested_name == "Alpha (2)"
    with open_open_directory_project(target, app_version=APP_VERSION) as container:
        assert container.project.name == "Alpha"


def test_install_different_name_still_refuses_without_confirm(tmp_path: Path) -> None:
    target = _make_current_container(tmp_path, name="Beta")
    staging = _make_current_container(Path(str(tmp_path) + "-staging"), name="Alpha")
    with pytest.raises(TargetConflictError) as excinfo:
        install_staging_to_target(staging, target, app_version=APP_VERSION)
    assert excinfo.value.suggested_name is None
    with open_open_directory_project(target, app_version=APP_VERSION) as container:
        assert container.project.name == "Beta"


def test_install_confirm_overwrite_replaces_and_keeps_recovery(tmp_path: Path) -> None:
    """A confirmed overwrite installs the new Project and preserves the old in a
    recovery backup next to the target."""
    target = _make_current_container(tmp_path, name="Alpha", source_language="zh")
    staging = _make_current_container(
        Path(str(tmp_path) + "-staging"),
        name="Alpha",
        source_language="ja",
    )
    install_staging_to_target(staging, target, app_version=APP_VERSION, confirm_overwrite=True)
    with open_open_directory_project(target, app_version=APP_VERSION) as container:
        assert container.project.source_language == "ja"
    recovery = list(tmp_path.glob(".proj.pre-replace-*.bak"))
    assert len(recovery) == 1
    with open_open_directory_project(recovery[0], app_version=APP_VERSION) as old:
        assert old.project.source_language == "zh"


def test_install_replace_rename_failure_restores_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the install rename fails mid-replace, the previous container is restored."""
    target = _make_current_container(tmp_path, name="Alpha", source_language="zh")
    staging = _make_current_container(
        Path(str(tmp_path) + "-staging"),
        name="Alpha",
        source_language="ja",
    )
    real_rename = os.rename

    def _fail_install_rename(src: str, dst: str) -> None:
        if Path(src).name.startswith(".proj.install-") and Path(dst) == target:
            raise OSError("injected rename failure")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", _fail_install_rename)
    with pytest.raises(OSError, match="injected rename failure"):
        install_staging_to_target(staging, target, app_version=APP_VERSION, confirm_overwrite=True)
    monkeypatch.undo()
    with open_open_directory_project(target, app_version=APP_VERSION) as container:
        assert container.project.source_language == "zh"


def test_install_replace_double_failure_names_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If both the install rename and the restore fail, the recovery path is named."""
    target = _make_current_container(tmp_path, name="Alpha", source_language="zh")
    staging = _make_current_container(
        Path(str(tmp_path) + "-staging"),
        name="Alpha",
        source_language="ja",
    )
    real_rename = os.rename
    real_move = shutil.move

    def _fail_install_rename(src: str, dst: str) -> None:
        if Path(src).name.startswith(".proj.install-") and Path(dst) == target:
            raise OSError("injected rename failure")
        real_rename(src, dst)

    def _fail_restore(src: str, dst: str) -> None:
        if Path(src).name.startswith(".proj.pre-replace-") and Path(dst) == target:
            raise OSError("injected restore failure")
        real_move(src, dst)

    monkeypatch.setattr(os, "rename", _fail_install_rename)
    monkeypatch.setattr(shutil, "move", _fail_restore)
    with pytest.raises(InstallError, match="recover it from"):
        install_staging_to_target(staging, target, app_version=APP_VERSION, confirm_overwrite=True)
    monkeypatch.undo()
    recovery = list(tmp_path.glob(".proj.pre-replace-*.bak"))
    assert len(recovery) == 1


def test_install_migration_failure_leaves_target_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _make_current_container(tmp_path, name="Target")
    directory = _make_old_schema_container(Path(str(tmp_path) + "-old"), name="Old")
    archive = _archive_from(directory, tmp_path / "old.aiproject")
    staging = tmp_path / "staging"
    _import_to_staging(archive, staging)

    def _fail(_self: object, _migration: object, *, app_version: str) -> None:
        raise MigrationExecutionError(
            "injected failure",
            path=Path("x"),
            migration_id=_MIGRATION_008,
        )

    monkeypatch.setattr(MigrationRunner, "_apply_single", _fail)
    with pytest.raises(MigrationExecutionError):
        install_staging_to_target(staging, target, app_version=APP_VERSION)
    monkeypatch.undo()
    with open_open_directory_project(target, app_version=APP_VERSION) as container:
        assert container.project.name == "Target"


# ---------------------------------------------------------------------------
# Manifest source_id and regeneration
# ---------------------------------------------------------------------------


def test_manifest_source_id_roundtrip(tmp_path: Path) -> None:
    directory = tmp_path / "proj"
    directory.mkdir()
    db = directory / DATABASE_FILENAME
    db.write_bytes(b"placeholder")
    entry = compute_entry(DATABASE_FILENAME, db, entry_type=CRITICAL_ENTRY_TYPE)
    write_manifest(directory, ManifestInfo(1, 1, APP_VERSION, (entry,), source_id=7))
    assert load_manifest(directory).source_id == 7


def test_manifest_source_id_optional(tmp_path: Path) -> None:
    directory = tmp_path / "proj"
    directory.mkdir()
    db = directory / DATABASE_FILENAME
    db.write_bytes(b"placeholder")
    entry = compute_entry(DATABASE_FILENAME, db, entry_type=CRITICAL_ENTRY_TYPE)
    write_manifest(directory, ManifestInfo(1, 1, APP_VERSION, (entry,)))
    assert load_manifest(directory).source_id is None


@pytest.mark.parametrize(
    "bad",
    [0, -1, "1", 1.5, True],
)
def test_manifest_source_id_invalid_rejected(tmp_path: Path, bad: object) -> None:
    directory = tmp_path / "proj"
    directory.mkdir()
    db = directory / DATABASE_FILENAME
    db.write_bytes(b"placeholder")
    entry = compute_entry(DATABASE_FILENAME, db, entry_type=CRITICAL_ENTRY_TYPE)
    manifest = {
        "format_version": 1,
        "schema_version": 1,
        "software": APP_VERSION,
        "source_id": bad,
        "files": {
            DATABASE_FILENAME: {
                "type": CRITICAL_ENTRY_TYPE,
                "size": entry.size,
                "hash": entry.hash,
            }
        },
    }
    import json

    (directory / MANIFEST_FILENAME).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(ManifestError, match="source_id"):
        load_manifest(directory)
