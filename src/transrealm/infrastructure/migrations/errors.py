"""Migration-specific errors."""

from pathlib import Path

from transrealm.infrastructure.errors import DatabaseError


class MigrationError(DatabaseError):
    """Base class for migration errors."""


class MigrationBackupError(MigrationError):
    """Creating a pre-upgrade database backup failed."""

    def __init__(
        self,
        message: str,
        path: Path | None = None,
    ) -> None:
        super().__init__(message, path)


class MigrationChecksumError(MigrationError):
    """A migration file's checksum does not match the recorded checksum."""


class MigrationOrderError(MigrationError):
    """A migration would be applied out of order or gaps are detected."""


class MigrationExecutionError(MigrationError):
    """A migration SQL script failed to execute."""

    def __init__(
        self,
        message: str,
        path: Path | None = None,
        migration_id: str | None = None,
    ) -> None:
        super().__init__(message, path)
        self.migration_id = migration_id

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.migration_id is not None:
            parts.append(f"migration: {self.migration_id}")
        return "; ".join(parts)
