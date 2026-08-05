"""Application service for Model Profile lifecycle operations."""

from __future__ import annotations

from pathlib import Path

from transrealm.domain.model_profile import (
    ModelCapability,
    ModelProfile,
    ModelProfileError,
)
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.model_profile_repository import (
    ModelProfileRepository,
)
from transrealm.infrastructure.repositories.provider_connection_repository import (
    ProviderConnectionRepository,
)


class ModelProfileService:
    """Application service for creating and managing model profiles."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._db = create_database(db_path)
        self._profile_repository = ModelProfileRepository(self._db)
        self._connection_repository = ProviderConnectionRepository(self._db)
        self._run_migrations()

    def _run_migrations(self) -> None:
        from transrealm.infrastructure.migrations.discovery import discover_migrations

        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

    def create_profile(
        self,
        *,
        name: str,
        provider_connection_id: int,
        model_id: str,
        template_version: str,
        output_protocol: str,
        context_budget: dict[str, object] | None = None,
        default_params: dict[str, object] | None = None,
        capability: ModelCapability | None = None,
    ) -> ModelProfile:
        """Create and persist a new model profile."""
        self._ensure_connection_exists(provider_connection_id)
        profile = ModelProfile.create(
            name=name,
            provider_connection_id=provider_connection_id,
            model_id=model_id,
            template_version=template_version,
            output_protocol=output_protocol,
            context_budget=context_budget,
            default_params=default_params,
            capability=capability,
        )
        return self._profile_repository.save(profile)

    def update_profile(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        provider_connection_id: int | None = None,
        model_id: str | None = None,
        template_version: str | None = None,
        output_protocol: str | None = None,
        context_budget: dict[str, object] | None = None,
        default_params: dict[str, object] | None = None,
        capability: ModelCapability | None = None,
    ) -> ModelProfile:
        """Update an existing model profile."""
        existing = self._profile_repository.get_by_id(profile_id)
        if existing is None:
            raise ModelProfileError(f"ModelProfile with id {profile_id} does not exist.")
        if provider_connection_id is not None:
            self._ensure_connection_exists(provider_connection_id)
        updated = existing.with_updated_fields(
            name=name,
            provider_connection_id=provider_connection_id,
            model_id=model_id,
            template_version=template_version,
            output_protocol=output_protocol,
            context_budget=context_budget,
            default_params=default_params,
            capability=capability,
        )
        return self._profile_repository.save(updated)

    def get_profile(self, profile_id: int) -> ModelProfile | None:
        """Fetch a profile by id."""
        return self._profile_repository.get_by_id(profile_id)

    def list_profiles(self) -> list[ModelProfile]:
        """Return all persisted profiles."""
        return self._profile_repository.list_all()

    def list_profiles_by_connection(self, connection_id: int) -> list[ModelProfile]:
        """Return all profiles referencing a given ProviderConnection."""
        return self._profile_repository.list_by_connection(connection_id)

    def delete_profile(self, profile_id: int) -> bool:
        """Delete a profile by id."""
        return self._profile_repository.delete(profile_id)

    def _ensure_connection_exists(self, connection_id: int) -> None:
        """Raise ModelProfileError if the referenced connection does not exist."""
        if self._connection_repository.get_by_id(connection_id) is None:
            raise ModelProfileError(
                f"ProviderConnection with id {connection_id} does not exist.",
            )

    def close(self) -> None:
        """Close the service and release resources."""
        self._profile_repository.close()

    def __enter__(self) -> ModelProfileService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
