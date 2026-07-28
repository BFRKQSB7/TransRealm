"""Database errors with actionable messages."""

from pathlib import Path


class DatabaseError(Exception):
    """Base class for database-related errors."""

    def __init__(self, message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.path = path

    def __str__(self) -> str:
        if self.path is not None:
            return f"{self.message} (path: {self.path})"
        return self.message


class ConnectionError(DatabaseError):  # noqa: A001
    """Failed to open or maintain a database connection."""


class PermissionDeniedError(DatabaseError):
    """The database path is not writable or readable."""


class TransactionError(DatabaseError):
    """A transaction could not be committed or rolled back."""


class SqlExecutionError(DatabaseError):
    """A SQL statement failed to execute."""

    def __init__(
        self,
        message: str,
        path: Path | None = None,
        sql: str | None = None,
    ) -> None:
        super().__init__(message, path)
        self.sql = sql

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.sql is not None:
            parts.append(f"SQL: {self.sql}")
        return "; ".join(parts)
