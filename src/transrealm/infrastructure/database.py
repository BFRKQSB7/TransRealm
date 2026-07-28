"""SQLite connection management and transaction support."""

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from transrealm.infrastructure.errors import (
    ConnectionError,
    DatabaseError,
    PermissionDeniedError,
    SqlExecutionError,
    TransactionError,
)


def _normalize_path(path: Path) -> Path:
    """Resolve and, on Windows, prefix long paths with \\?\\ when needed."""
    absolute = path.resolve()
    if os.name == "nt" and not absolute.drive.startswith("\\\\"):
        # Windows paths longer than MAX_PATH (260) need the extended path prefix.
        str_path = str(absolute)
        if len(str_path) > 260 and not str_path.startswith("\\\\?\\"):
            return Path("\\\\?\\" + str_path)
    return absolute


def _translate_sqlite_error(
    exc: sqlite3.Error,
    path: Path,
    sql: str | None = None,
) -> DatabaseError:
    """Convert a sqlite3 exception into a domain-friendly DatabaseError."""
    message = str(exc)
    # sqlite3 uses OperationalError for many I/O problems; inspect messages.
    lower = message.lower()
    if isinstance(exc, sqlite3.OperationalError):
        if "unable to open" in lower or "readonly" in lower or "disk i/o" in lower:
            if "readonly" in lower or "attempt to write a readonly" in lower:
                return PermissionDeniedError(
                    "Database is read-only or not writable.",
                    path=path,
                )
            return ConnectionError(
                f"Unable to open database: {message}",
                path=path,
            )
        return SqlExecutionError(
            f"SQL execution failed: {message}",
            path=path,
            sql=sql,
        )
    if isinstance(exc, sqlite3.IntegrityError):
        return SqlExecutionError(
            f"Integrity constraint violated: {message}",
            path=path,
            sql=sql,
        )
    return SqlExecutionError(
        f"Unexpected database error: {message}",
        path=path,
        sql=sql,
    )


class DatabaseConnection:
    """Wraps a sqlite3 connection with our configured PRAGMAs."""

    def __init__(self, connection: sqlite3.Connection, path: Path) -> None:
        self._connection = connection
        self._path = path

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    @property
    def path(self) -> Path:
        return self._path

    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] | None = None,
    ) -> sqlite3.Cursor:
        """Execute a SQL statement, translating errors to domain errors."""
        try:
            if parameters is None:
                return self._connection.execute(sql)
            return self._connection.execute(sql, parameters)
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc, self._path, sql) from exc

    def executescript(self, sql: str) -> sqlite3.Cursor:
        """Execute a SQL script, translating errors to domain errors."""
        try:
            return self._connection.executescript(sql)
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc, self._path, sql) from exc

    def close(self) -> None:
        """Close the underlying connection."""
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise ConnectionError(f"Failed to close database: {exc}", path=self._path) from exc


def create_database(path: Path) -> DatabaseConnection:
    """Open a SQLite database with foreign keys enabled and return a wrapped connection.

    Args:
        path: Filesystem path to the SQLite database. Parent directories must exist.

    Returns:
        A DatabaseConnection configured with PRAGMA foreign_keys=ON.

    Raises:
        ConnectionError: If the database cannot be opened.
        PermissionDeniedError: If the path is not writable/readable.
    """
    normalized = _normalize_path(path)
    try:
        raw = sqlite3.connect(str(normalized), timeout=10.0)
    except sqlite3.Error as exc:
        raise ConnectionError(f"Unable to open database: {exc}", path=path) from exc
    except OSError as exc:
        if exc.errno == 13 or exc.winerror == 5:  # noqa: PLR2004
            raise PermissionDeniedError(
                "Database path is not accessible (permission denied).",
                path=path,
            ) from exc
        raise ConnectionError(f"Unable to open database: {exc}", path=path) from exc

    try:
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as exc:
        raw.close()
        raise _translate_sqlite_error(exc, path) from exc

    return DatabaseConnection(raw, path)


@contextmanager
def transaction(connection: DatabaseConnection) -> Generator[DatabaseConnection, None, None]:
    """Run a block inside a SQLite transaction.

    Commits on normal exit, rolls back on exception.

    Args:
        connection: An open DatabaseConnection.

    Yields:
        The same connection, usable inside the transaction.

    Raises:
        TransactionError: If commit or rollback fails.
    """
    raw = connection.connection
    try:
        yield connection
        raw.commit()
    except sqlite3.Error as exc:
        try:
            raw.rollback()
        except sqlite3.Error as rollback_exc:
            raise TransactionError(
                f"Transaction failed and rollback also failed: {rollback_exc}",
                path=connection.path,
            ) from exc
        raise _translate_sqlite_error(exc, connection.path) from exc
    except Exception:
        try:
            raw.rollback()
        except sqlite3.Error as rollback_exc:
            raise TransactionError(
                f"Transaction rollback failed: {rollback_exc}",
                path=connection.path,
            )
        raise


__all__ = [
    "ConnectionError",
    "DatabaseConnection",
    "DatabaseError",
    "PermissionDeniedError",
    "SqlExecutionError",
    "TransactionError",
    "create_database",
    "transaction",
]
