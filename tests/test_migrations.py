"""Tests for the migration runner."""

import hashlib
from pathlib import Path

import pytest

from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.errors import SqlExecutionError
from transrealm.infrastructure.migrations import (
    Migration,
    MigrationBackupError,
    MigrationChecksumError,
    MigrationExecutionError,
    MigrationRunner,
    discover_migrations,
    run_migrations,
)
from transrealm.infrastructure.migrations.backup import create_pre_upgrade_backup


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    """Return a temporary migrations directory."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


def write_migration(directory: Path, name: str, sql: str) -> Migration:
    """Write a migration file and return its Migration representation."""
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return Migration.from_file(path)


def test_discover_migrations_sorts_by_filename(migrations_dir: Path) -> None:
    """Migrations are discovered and ordered by filename."""
    write_migration(migrations_dir, "002_second.sql", "SELECT 2;")
    write_migration(migrations_dir, "001_first.sql", "SELECT 1;")
    found = discover_migrations(migrations_dir)
    assert [m.migration_id for m in found] == ["001_first", "002_second"]


def test_discover_migrations_empty_directory(tmp_path: Path) -> None:
    """An empty or missing directory yields no migrations."""
    assert discover_migrations(tmp_path / "empty") == []
    existing = tmp_path / "existing"
    existing.mkdir()
    assert discover_migrations(existing) == []


def test_migration_checksum_is_sha256(migrations_dir: Path) -> None:
    """Migration checksum is a SHA-256 of the SQL content."""
    sql = "SELECT 1;"
    migration = write_migration(migrations_dir, "001_test.sql", sql)
    expected = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    assert migration.checksum == expected


def test_runner_applies_migrations(db_path: Path, migrations_dir: Path) -> None:
    """The runner applies pending migrations and records history."""
    write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    applied = run_migrations(db_path, migrations_dir, app_version="0.1.0")
    assert len(applied) == 1

    db = create_database(db_path)
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "items" in tables
    assert "schema_migrations" in tables
    db.close()


def test_runner_is_idempotent(db_path: Path, migrations_dir: Path) -> None:
    """Re-running migrations does not re-apply already-applied scripts."""
    write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    run_migrations(db_path, migrations_dir, app_version="0.1.0")
    applied = run_migrations(db_path, migrations_dir, app_version="0.1.0")
    assert applied == []


def test_runner_rejects_checksum_mismatch(db_path: Path, migrations_dir: Path) -> None:
    """A changed migration file is rejected on re-run."""
    migration = write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    run_migrations(db_path, migrations_dir, app_version="0.1.0")

    # Mutate the file content so the checksum changes.
    migration.path.write_text(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);",
        encoding="utf-8",
    )

    with pytest.raises(MigrationChecksumError):
        run_migrations(db_path, migrations_dir, app_version="0.1.0")


def test_runner_records_history(db_path: Path, migrations_dir: Path) -> None:
    """Applied migrations are recorded with checksum and app version."""
    migration = write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    run_migrations(db_path, migrations_dir, app_version="0.2.0")

    db = create_database(db_path)
    runner = MigrationRunner(db)
    history = runner.history()
    assert len(history) == 1
    assert history[0]["migration_id"] == "001_init"
    assert history[0]["checksum"] == migration.checksum
    assert history[0]["app_version"] == "0.2.0"
    db.close()


def test_runner_reports_execution_errors(db_path: Path, migrations_dir: Path) -> None:
    """A migration with invalid SQL raises MigrationExecutionError."""
    write_migration(
        migrations_dir,
        "001_broken.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY); INVALID SQL;",
    )
    with pytest.raises(MigrationExecutionError):
        run_migrations(db_path, migrations_dir, app_version="0.1.0")


def test_runner_rolls_back_failed_migration(db_path: Path, migrations_dir: Path) -> None:
    """A failed migration does not leave partial schema changes."""
    write_migration(
        migrations_dir,
        "001_broken.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY); INVALID SQL;",
    )
    with pytest.raises(MigrationExecutionError):
        run_migrations(db_path, migrations_dir, app_version="0.1.0")

    db = create_database(db_path)
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "items" not in tables
    db.close()


def test_runner_applies_multiple_migrations_in_order(db_path: Path, migrations_dir: Path) -> None:
    """Multiple pending migrations are applied in filename order."""
    write_migration(
        migrations_dir,
        "001_first.sql",
        "CREATE TABLE first (id INTEGER PRIMARY KEY);",
    )
    write_migration(
        migrations_dir,
        "002_second.sql",
        "CREATE TABLE second (id INTEGER PRIMARY KEY);",
    )
    applied = run_migrations(db_path, migrations_dir, app_version="0.1.0")
    assert [m.migration_id for m in applied] == ["001_first", "002_second"]

    db = create_database(db_path)
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert {"first", "second", "schema_migrations"} <= tables
    db.close()


def test_import_uniqueness_migration_adds_database_constraints(tmp_path: Path) -> None:
    """The real migration rejects duplicate source hashes and stable keys."""
    migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
    db_path = tmp_path / "project.db"
    run_migrations(db_path, migrations_dir, app_version="0.1.0")

    db = create_database(db_path)
    with transaction(db):
        project_id = db.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('P1', 'zh', 'en')",
        ).lastrowid
        document_id = db.execute(
            "INSERT INTO source_documents "
            "(project_id, name, format, encoding, source_hash, parser_version) "
            "VALUES (?, 'a.txt', 'txt', 'utf-8', 'hash', '1.0.0')",
            (project_id,),
        ).lastrowid
        db.execute(
            "INSERT INTO segments "
            "(source_document_id, stable_key, source_text, sequence) "
            "VALUES (?, 'key', 'A', 1)",
            (document_id,),
        )

    with pytest.raises(SqlExecutionError):
        with transaction(db):
            db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 'b.txt', 'txt', 'utf-8', 'hash', '1.0.0')",
                (project_id,),
            )
    with pytest.raises(SqlExecutionError):
        with transaction(db):
            db.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence) "
                "VALUES (?, 'key', 'B', 2)",
                (document_id,),
            )

    index_metadata = {
        row[1]: row[2]
        for row in db.execute("PRAGMA index_list('source_documents')").fetchall()
    }
    segment_index_metadata = {
        row[1]: row[2]
        for row in db.execute("PRAGMA index_list('segments')").fetchall()
    }
    history = MigrationRunner(db).history()
    db.close()
    assert index_metadata["uq_source_documents_project_hash"] == 1
    assert segment_index_metadata["uq_segments_document_stable_key"] == 1
    assert any(record["migration_id"] == "003_add_import_uniqueness" for record in history)


def test_import_uniqueness_migration_preserves_legacy_conflicts(
    tmp_path: Path,
) -> None:
    """A conflicting legacy database is left intact when migration 003 fails."""
    real_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
    migrations = discover_migrations(real_dir)
    db_path = tmp_path / "legacy.db"
    run_migrations(db_path, real_dir, app_version="0.1.0")

    db = create_database(db_path)
    db.execute("DROP INDEX uq_source_documents_project_hash")
    db.execute("DELETE FROM schema_migrations WHERE migration_id = '003_add_import_uniqueness'")
    db.connection.commit()
    with transaction(db):
        project_id = db.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('P1', 'zh', 'en')",
        ).lastrowid
        for name in ("a.txt", "b.txt"):
            db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, ?, 'txt', 'utf-8', 'same-hash', '1.0.0')",
                (project_id, name),
            )
    migration_003 = next(
        m for m in migrations if m.migration_id == "003_add_import_uniqueness"
    )
    runner = MigrationRunner(db)
    with pytest.raises(MigrationExecutionError):
        runner.apply([migration_003], app_version="0.1.0")

    count = db.execute(
        "SELECT COUNT(*) FROM source_documents WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]
    history = {record["migration_id"] for record in runner.history()}
    db.close()
    assert count == 2
    assert "003_add_import_uniqueness" not in history


def test_import_uniqueness_migration_rejects_wrong_named_index(tmp_path: Path) -> None:
    """A same-named non-unique index cannot make migration 003 look successful."""
    real_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
    migrations = discover_migrations(real_dir)
    db_path = tmp_path / "legacy-index.db"
    db = create_database(db_path)
    runner = MigrationRunner(db)
    runner.apply(migrations[:2], app_version="0.1.0")
    db.execute(
        "CREATE INDEX uq_source_documents_project_hash "
        "ON source_documents(project_id, source_hash)",
    )
    db.connection.commit()

    migration_003 = next(
        m for m in migrations if m.migration_id == "003_add_import_uniqueness"
    )

    with pytest.raises(MigrationExecutionError):
        runner.apply([migration_003], app_version="0.1.0")

    metadata = {
        row[1]: row[2]
        for row in db.execute("PRAGMA index_list('source_documents')").fetchall()
    }
    history = {record["migration_id"] for record in runner.history()}
    db.close()
    assert metadata["uq_source_documents_project_hash"] == 0
    assert "003_add_import_uniqueness" not in history


def test_backup_created_when_pending_migrations(db_path: Path, migrations_dir: Path) -> None:
    """A pre-upgrade backup is created before applying pending migrations."""
    write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    runner = MigrationRunner.open(db_path)
    try:
        applied = runner.apply(discover_migrations(migrations_dir), app_version="0.1.0")
        assert len(applied) == 1
        assert runner.last_backup_path is not None
        assert runner.last_backup_path.exists()
        assert runner.last_backup_path.parent == db_path.parent
        assert runner.last_backup_path.name.startswith(db_path.stem)
        assert runner.last_backup_path.name.endswith(".db.bak")

        # The backup is a valid, openable SQLite database captured *before* the
        # new migration ran, so it has the history table but not the new table.
        backup = create_database(runner.last_backup_path)
        cursor = backup.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        backup.close()
        assert "schema_migrations" in tables
        assert "items" not in tables

        # The source database has the new table after migration.
        source = create_database(db_path)
        cursor = source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        source_tables = {row[0] for row in cursor.fetchall()}
        source.close()
        assert "items" in source_tables
    finally:
        runner.close()


def test_backup_not_created_when_no_pending_migrations(
    db_path: Path,
    migrations_dir: Path,
) -> None:
    """No backup is created when all migrations are already applied."""
    write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    run_migrations(db_path, migrations_dir, app_version="0.1.0")

    backups_before = set(db_path.parent.glob("*.bak"))
    applied = run_migrations(db_path, migrations_dir, app_version="0.1.0")
    backups_after = set(db_path.parent.glob("*.bak"))

    assert applied == []
    assert backups_after == backups_before


def test_backup_failure_blocks_migration(db_path: Path, migrations_dir: Path) -> None:
    """If backup creation fails, no migrations are applied."""
    write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )

    def failing_backup() -> Path:
        raise MigrationBackupError("forced backup failure", path=db_path)

    runner = MigrationRunner.open(db_path)
    try:
        runner._create_backup = failing_backup  # type: ignore[method-assign]
        with pytest.raises(MigrationBackupError):
            runner.apply(discover_migrations(migrations_dir), app_version="0.1.0")
    finally:
        runner.close()

    db = create_database(db_path)
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    db.close()
    assert "items" not in tables


def test_backup_preserved_when_migration_fails(db_path: Path, migrations_dir: Path) -> None:
    """A pre-upgrade backup survives a failed migration."""
    write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    run_migrations(db_path, migrations_dir, app_version="0.1.0")

    write_migration(
        migrations_dir,
        "002_broken.sql",
        "CREATE TABLE broken (id INTEGER PRIMARY KEY); INVALID SQL;",
    )

    runner = MigrationRunner.open(db_path)
    try:
        with pytest.raises(MigrationExecutionError):
            runner.apply(discover_migrations(migrations_dir), app_version="0.1.0")

        assert runner.last_backup_path is not None
        assert runner.last_backup_path.exists()

        # Backup still has the original schema and data, not the failed migration.
        backup = create_database(runner.last_backup_path)
        cursor = backup.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        broken_count = backup.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='broken'",
        ).fetchone()[0]
        backup.close()
        assert "items" in tables
        assert broken_count == 0
    finally:
        runner.close()


def test_backup_is_consistent_with_wal_mode(db_path: Path, migrations_dir: Path) -> None:
    """Backup succeeds while the source database uses WAL mode."""
    write_migration(
        migrations_dir,
        "001_init.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);",
    )
    run_migrations(db_path, migrations_dir, app_version="0.1.0")

    db = create_database(db_path)
    journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    db.close()
    assert journal_mode == "wal"

    write_migration(
        migrations_dir,
        "002_second.sql",
        "CREATE TABLE second (id INTEGER PRIMARY KEY);",
    )

    runner = MigrationRunner.open(db_path)
    try:
        runner.apply(discover_migrations(migrations_dir), app_version="0.1.0")
        assert runner.last_backup_path is not None
        backup = create_database(runner.last_backup_path)
        backup.execute("PRAGMA schema_version")
        backup.close()
    finally:
        runner.close()


def test_backup_naming_convention_avoids_collisions(db_path: Path) -> None:
    """Backup paths use a timestamp suffix and avoid collisions."""
    from transrealm.infrastructure.migrations.backup import _generate_backup_path

    first = _generate_backup_path(db_path)
    first.touch()
    second = _generate_backup_path(db_path)
    assert second != first
    assert second.name.startswith(db_path.stem)
    assert second.name.endswith(".db.bak")

    first.unlink()


def test_backup_api_requires_writable_destination(tmp_path: Path) -> None:
    """Backup creation fails with a clear error when the destination is not writable."""
    db_path = tmp_path / "source.db"
    # A file as the parent directory makes any child path impossible to create.
    not_a_directory = tmp_path / "not_a_directory"
    not_a_directory.write_text("not a directory", encoding="utf-8")
    backup_path = not_a_directory / "backup.db.bak"

    db = create_database(db_path)
    try:
        with pytest.raises(MigrationBackupError):
            create_pre_upgrade_backup(db.connection, backup_path)
    finally:
        db.close()
