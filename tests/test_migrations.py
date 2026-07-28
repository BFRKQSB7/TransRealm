"""Tests for the migration runner."""

import hashlib
from pathlib import Path

import pytest

from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations import (
    Migration,
    MigrationChecksumError,
    MigrationExecutionError,
    MigrationRunner,
    discover_migrations,
    run_migrations,
)


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
