"""Tests for SQLite connection management and transactions."""

from pathlib import Path

import pytest

from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.errors import (
    ConnectionError,
    PermissionDeniedError,
    SqlExecutionError,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


def test_create_database_opens_connection(db_path: Path) -> None:
    """A new database file is created and can execute SQL."""
    db = create_database(db_path)
    assert db_path.exists()
    cursor = db.execute("SELECT 1")
    assert cursor.fetchone() == (1,)
    db.close()


def test_create_database_enables_foreign_keys(db_path: Path) -> None:
    """Foreign keys are enforced by default."""
    db = create_database(db_path)
    db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    db.execute(
        "CREATE TABLE child ("
        "  id INTEGER PRIMARY KEY,"
        "  parent_id INTEGER REFERENCES parent(id)"
        ")",
    )
    db.execute("INSERT INTO parent (id) VALUES (1)")
    with pytest.raises(SqlExecutionError):
        db.execute("INSERT INTO child (parent_id) VALUES (99)")
    db.close()


def test_transaction_commits_on_success(db_path: Path) -> None:
    """A successful transaction block commits changes."""
    db = create_database(db_path)
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    with transaction(db):
        db.execute("INSERT INTO items (id) VALUES (1)")
    cursor = db.execute("SELECT id FROM items")
    assert cursor.fetchall() == [(1,)]
    db.close()


def test_transaction_rolls_back_on_error(db_path: Path) -> None:
    """A transaction block rolls back when an exception is raised."""
    db = create_database(db_path)
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    with pytest.raises(ValueError):
        with transaction(db):
            db.execute("INSERT INTO items (id) VALUES (1)")
            raise ValueError("intentional failure")
    cursor = db.execute("SELECT id FROM items")
    assert cursor.fetchall() == []
    db.close()


def test_transaction_rolls_back_on_sql_error(db_path: Path) -> None:
    """A SQL error inside a transaction causes rollback."""
    db = create_database(db_path)
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    with pytest.raises(SqlExecutionError):
        with transaction(db):
            db.execute("INSERT INTO items (id) VALUES (1)")
            db.execute("INSERT INTO items (id) VALUES ('not-an-integer')")
    cursor = db.execute("SELECT id FROM items")
    assert cursor.fetchall() == []
    db.close()


def test_create_database_rejects_nonexistent_parent_directory(tmp_path: Path) -> None:
    """Opening a database under a missing parent directory raises ConnectionError."""
    missing = tmp_path / "missing" / "test.db"
    with pytest.raises(ConnectionError):
        create_database(missing)


def test_create_database_rejects_readonly_file(db_path: Path) -> None:
    """Opening a read-only database file for writing raises PermissionDeniedError."""
    db_path.write_bytes(b"")
    db_path.chmod(0o444)
    try:
        with pytest.raises(PermissionDeniedError):
            create_database(db_path)
    finally:
        db_path.chmod(0o666)


def test_unicode_path_support(tmp_path: Path) -> None:
    """A database can be created with a Unicode path."""
    db_path = tmp_path / "译境测试.db"
    db = create_database(db_path)
    db.execute("SELECT 1")
    db.close()
    assert db_path.exists()


@pytest.mark.skipif("os.name != 'nt'", reason="Windows-specific long-path test")
def test_long_path_support(tmp_path: Path) -> None:
    """A database can be created with a very long Windows path."""
    # Build a path that exceeds the legacy MAX_PATH limit.
    deep = tmp_path
    for segment in ["a" * 40] * 8:
        deep = deep / segment
    deep.mkdir(parents=True, exist_ok=True)
    db_path = deep / "test.db"
    db = create_database(db_path)
    db.execute("SELECT 1")
    db.close()
    assert db_path.exists()


def test_sql_error_includes_sql_text(db_path: Path) -> None:
    """A SQL execution error preserves the offending SQL text."""
    db = create_database(db_path)
    bad_sql = "SELECT * FROM missing_table"
    with pytest.raises(SqlExecutionError) as exc_info:
        db.execute(bad_sql)
    assert exc_info.value.sql == bad_sql
    db.close()


def test_connection_isolation_between_instances(db_path: Path) -> None:
    """Uncommitted changes from one connection are not visible to another."""
    db1 = create_database(db_path)
    db2 = create_database(db_path)
    db1.execute("CREATE TABLE shared (id INTEGER PRIMARY KEY)")
    db1.execute("BEGIN")
    db1.execute("INSERT INTO shared (id) VALUES (1)")
    # db2 should not see the uncommitted insert from db1.
    rows = db2.execute("SELECT id FROM shared").fetchall()
    assert rows == []
    db1.execute("COMMIT")
    rows = db2.execute("SELECT id FROM shared").fetchall()
    assert rows == [(1,)]
    db1.close()
    db2.close()


def test_create_database_configures_wal_mode(db_path: Path) -> None:
    """The connection configures WAL journal mode."""
    db = create_database(db_path)
    cursor = db.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    assert mode.lower() == "wal"
    db.close()
