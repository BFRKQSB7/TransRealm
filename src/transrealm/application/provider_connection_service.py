"""Application service for Provider Connection lifecycle operations."""

from __future__ import annotations

from pathlib import Path

from transrealm.domain.provider_connection import ProviderConnection, ProviderConnectionError
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.provider_connection_repository import (
    ProviderConnectionRepository,
)


class ProviderConnectionService:
    """Application service for creating and managing provider connections."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._db = create_database(db_path)
        self._repository = ProviderConnectionRepository(self._db)
        self._run_migrations()

    def _run_migrations(self) -> None:
        from transrealm.infrastructure.migrations.discovery import discover_migrations

        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

    def create_connection(
        self,
        *,
        name: str,
        provider_type: str,
        endpoint: str,
        timeout_seconds: int = 30,
        max_retries: int = 0,
        retry_delay_seconds: float = 0.0,
        credential_reference: str | None = None,
    ) -> ProviderConnection:
        """Create and persist a new provider connection."""
        connection = ProviderConnection.create(
            name=name,
            provider_type=provider_type,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            credential_reference=credential_reference,
        )
        return self._repository.save(connection)

    def update_connection(
        self,
        connection_id: int,
        *,
        name: str | None = None,
        provider_type: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        credential_reference: str | None = None,
    ) -> ProviderConnection:
        """Update an existing provider connection."""
        existing = self._repository.get_by_id(connection_id)
        if existing is None:
            raise ProviderConnectionError(
                f"ProviderConnection with id {connection_id} does not exist.",
            )
        updated = existing.with_updated_fields(
            name=name,
            provider_type=provider_type,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            credential_reference=credential_reference,
        )
        return self._repository.save(updated)

    def get_connection(self, connection_id: int) -> ProviderConnection | None:
        """Fetch a connection by id."""
        return self._repository.get_by_id(connection_id)

    def get_connection_by_name(self, name: str) -> ProviderConnection | None:
        """Fetch a connection by name."""
        return self._repository.get_by_name(name)

    def list_connections(self) -> list[ProviderConnection]:
        """Return all persisted connections."""
        return self._repository.list_all()

    def delete_connection(self, connection_id: int) -> bool:
        """Delete a connection by id."""
        return self._repository.delete(connection_id)

    def close(self) -> None:
        """Close the service and release resources."""
        self._repository.close()

    def __enter__(self) -> ProviderConnectionService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
