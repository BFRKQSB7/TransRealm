"""Migration runner that applies SQL scripts in order and records history."""

from pathlib import Path

from transrealm.infrastructure.database import DatabaseConnection, create_database
from transrealm.infrastructure.migrations.discovery import Migration, discover_migrations
from transrealm.infrastructure.migrations.errors import (
    MigrationChecksumError,
    MigrationExecutionError,
)


class MigrationRunner:
    """Apply discovered migrations to a SQLite database.

    The runner maintains a `schema_migrations` table recording each applied
    migration id, checksum, application timestamp, and app version.
    """

    _CREATE_HISTORY_TABLE = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        migration_id TEXT PRIMARY KEY,
        checksum TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT (datetime('now')),
        app_version TEXT NOT NULL
    )
    """

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> "MigrationRunner":
        """Create a runner for the database at ``path``."""
        return cls(create_database(path))

    def _ensure_history_table(self) -> None:
        self._db.execute(self._CREATE_HISTORY_TABLE)

    def _fetch_records(self) -> dict[str, str]:
        """Return a mapping of migration_id -> checksum for applied migrations."""
        cursor = self._db.execute(
            "SELECT migration_id, checksum FROM schema_migrations ORDER BY migration_id",
        )
        return {row[0]: row[1] for row in cursor.fetchall()}

    def apply(self, migrations: list[Migration], *, app_version: str) -> list[Migration]:
        """Apply migrations that have not yet been applied.

        Args:
            migrations: Ordered list of migrations to apply.
            app_version: Version string recorded in the history table.

        Returns:
            The list of migrations that were actually applied.

        Raises:
            MigrationChecksumError: If an already-applied migration's checksum
                does not match the file.
            MigrationExecutionError: If a migration SQL script fails.
        """
        self._ensure_history_table()
        records = self._fetch_records()
        applied: list[Migration] = []

        for migration in migrations:
            recorded_checksum = records.get(migration.migration_id)
            if recorded_checksum is not None:
                if recorded_checksum != migration.checksum:
                    raise MigrationChecksumError(
                        f"Checksum mismatch for migration {migration.migration_id}: "
                        f"expected {recorded_checksum}, got {migration.checksum}",
                        path=migration.path,
                    )
                continue

            applied.append(migration)
            self._apply_single(migration, app_version=app_version)

        return applied

    def _apply_single(self, migration: Migration, *, app_version: str) -> None:
        """Execute a migration inside an explicit BEGIN/COMMIT transaction.

        sqlite3's ``executescript`` implicitly commits any pending transaction,
        so we embed ``BEGIN`` and ``COMMIT`` in the script itself to keep the
        migration DDL and the history insert atomic.
        """

        def _escape(value: str) -> str:
            return value.replace("'", "''")

        script = (
            "BEGIN;\n"
            f"{migration.sql}\n"
            "INSERT INTO schema_migrations "
            f"(migration_id, checksum, app_version) VALUES ("
            f"'{_escape(migration.migration_id)}', "
            f"'{_escape(migration.checksum)}', "
            f"'{_escape(app_version)}'"
            f");\n"
            "COMMIT;"
        )
        try:
            self._db.executescript(script)
        except Exception as exc:
            # The explicit transaction is aborted. Roll back any remaining work
            # and surface a domain-friendly error.
            try:
                self._db.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise MigrationExecutionError(
                f"Migration {migration.migration_id} failed: {exc}",
                path=migration.path,
                migration_id=migration.migration_id,
            ) from exc

    def history(self) -> list[dict[str, object]]:
        """Return the applied migration history ordered by application time."""
        self._ensure_history_table()
        cursor = self._db.execute(
            "SELECT migration_id, checksum, applied_at, app_version "
            "FROM schema_migrations ORDER BY applied_at, migration_id",
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def run_migrations(
    db_path: Path,
    migrations_dir: Path,
    *,
    app_version: str,
) -> list[Migration]:
    """Convenience function to open a database and apply migrations."""
    migrations = discover_migrations(migrations_dir)
    runner = MigrationRunner.open(db_path)
    try:
        return runner.apply(migrations, app_version=app_version)
    finally:
        runner._db.close()
