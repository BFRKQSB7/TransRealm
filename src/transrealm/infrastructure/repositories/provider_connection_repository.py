"""SQLite-backed repository for ProviderConnection entities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from transrealm.domain.provider_connection import ProviderConnection
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class ProviderConnectionRepository:
    """SQLite-backed repository for ProviderConnection entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> ProviderConnectionRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, connection: ProviderConnection) -> ProviderConnection:
        """Insert or update a connection and return the persisted entity."""
        now = datetime.now().isoformat()
        if connection.id is None:
            with transaction(self._db):
                cursor = self._db.execute(
                    "INSERT INTO provider_connections "
                    "(name, provider_type, endpoint, timeout_seconds, max_retries, "
                    "retry_delay_seconds, credential_reference, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        connection.name,
                        connection.provider_type,
                        connection.endpoint,
                        connection.timeout_seconds,
                        connection.max_retries,
                        connection.retry_delay_seconds,
                        connection.credential_reference,
                        now,
                        now,
                    ),
                )
                new_id = cursor.lastrowid
            assert new_id is not None
            loaded = self.get_by_id(new_id)
            assert loaded is not None
            return loaded

        with transaction(self._db):
            cursor = self._db.execute(
                "UPDATE provider_connections SET name = ?, provider_type = ?, "
                "endpoint = ?, timeout_seconds = ?, max_retries = ?, "
                "retry_delay_seconds = ?, credential_reference = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    connection.name,
                    connection.provider_type,
                    connection.endpoint,
                    connection.timeout_seconds,
                    connection.max_retries,
                    connection.retry_delay_seconds,
                    connection.credential_reference,
                    now,
                    connection.id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"ProviderConnection with id {connection.id} does not exist.",
                )
        loaded = self.get_by_id(connection.id)
        assert loaded is not None
        return loaded

    def get_by_id(self, connection_id: int) -> ProviderConnection | None:
        """Fetch a connection by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, name, provider_type, endpoint, timeout_seconds, max_retries, "
            "retry_delay_seconds, credential_reference, created_at, updated_at "
            "FROM provider_connections WHERE id = ?",
            (connection_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_connection(row)

    def get_by_name(self, name: str) -> ProviderConnection | None:
        """Fetch a connection by name, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, name, provider_type, endpoint, timeout_seconds, max_retries, "
            "retry_delay_seconds, credential_reference, created_at, updated_at "
            "FROM provider_connections WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_connection(row)

    def list_all(self) -> list[ProviderConnection]:
        """Return all connections ordered by id."""
        cursor = self._db.execute(
            "SELECT id, name, provider_type, endpoint, timeout_seconds, max_retries, "
            "retry_delay_seconds, credential_reference, created_at, updated_at "
            "FROM provider_connections ORDER BY id",
        )
        return [self._row_to_connection(row) for row in cursor.fetchall()]

    def delete(self, connection_id: int) -> bool:
        """Delete a connection by id. Returns True if a row was removed."""
        with transaction(self._db):
            cursor = self._db.execute(
                "DELETE FROM provider_connections WHERE id = ?",
                (connection_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_connection(row: tuple[object, ...]) -> ProviderConnection:
        return ProviderConnection(
            id=int(str(row[0])),
            name=str(row[1]),
            provider_type=str(row[2]),
            endpoint=str(row[3]),
            timeout_seconds=int(str(row[4])),
            max_retries=int(str(row[5])),
            retry_delay_seconds=float(str(row[6])),
            credential_reference=str(row[7]) if row[7] is not None else None,
            created_at=datetime.fromisoformat(str(row[8])),
            updated_at=datetime.fromisoformat(str(row[9])),
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
