"""Application service for Model Profile lifecycle operations."""

from __future__ import annotations

from pathlib import Path

from transrealm.application.preset_templates import (
    ALLOWED_PLACEHOLDERS,
    current_preset,
)
from transrealm.domain.model_profile import (
    ModelCapability,
    ModelProfile,
    ModelProfileError,
    ModelProfileInUseError,
)
from transrealm.domain.prompt_override import PromptOverride
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.model_profile_repository import (
    ModelProfileRepository,
)
from transrealm.infrastructure.repositories.project_repository import ProjectRepository
from transrealm.infrastructure.repositories.prompt_override_repository import (
    PromptOverrideRepository,
)
from transrealm.infrastructure.repositories.provider_connection_repository import (
    ProviderConnectionRepository,
)
from transrealm.infrastructure.repositories.segment_attempt_repository import (
    SegmentAttemptRepository,
)


class ModelProfileService:
    """Application service for creating and managing model profiles."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._db = create_database(db_path)
        self._profile_repository = ModelProfileRepository(self._db)
        self._override_repository = PromptOverrideRepository(self._db)
        self._connection_repository = ProviderConnectionRepository(self._db)
        self._project_repository = ProjectRepository(self._db)
        self._attempt_repository = SegmentAttemptRepository(self._db)
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

    def set_prompt_override(
        self,
        profile_id: int,
        template_text: str,
    ) -> PromptOverride:
        """Save the user's template text as an override of the preset.

        The override records the current preset version as its parent, so a
        later preset update invalidates it (rejected fail-closed at render
        time). Unknown variables, invalid ``$`` syntax and empty text are
        rejected here; a failed validation persists nothing.
        """
        if self._profile_repository.get_by_id(profile_id) is None:
            raise ModelProfileError(
                f"ModelProfile with id {profile_id} does not exist.",
            )
        preset = current_preset()
        override = PromptOverride.create(
            model_profile_id=profile_id,
            parent_template_version=preset.version,
            template_text=template_text,
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        return self._override_repository.save(override)

    def get_prompt_override(self, profile_id: int) -> PromptOverride | None:
        """Return the saved override for a profile, or None if there is none."""
        return self._override_repository.get_by_profile(profile_id)

    def clear_prompt_override(self, profile_id: int) -> bool:
        """Remove the saved override for a profile. Returns True if one existed."""
        return self._override_repository.delete_by_profile(profile_id)

    def list_profiles(self) -> list[ModelProfile]:
        """Return all persisted profiles."""
        return self._profile_repository.list_all()

    def list_profiles_by_connection(self, connection_id: int) -> list[ModelProfile]:
        """Return all profiles referencing a given ProviderConnection."""
        return self._profile_repository.list_by_connection(connection_id)

    def delete_profile(self, profile_id: int) -> bool:
        """Delete a profile by id.

        Raises:
            ModelProfileInUseError: If the profile is the active profile of any
                project or is referenced by any historical attempt. The caller
                must first clear or repoint those references.
        """
        if self._profile_repository.get_by_id(profile_id) is None:
            return False

        referencing_projects = self._project_repository.list_by_active_profile(
            profile_id,
        )
        if referencing_projects:
            names = ", ".join(p.name for p in referencing_projects)
            raise ModelProfileInUseError(
                f"ModelProfile with id {profile_id} is the active profile of "
                f"project(s): {names}. Clear or change those selections first.",
            )

        attempt_count = self._attempt_repository.count_by_model_profile(profile_id)
        if attempt_count:
            raise ModelProfileInUseError(
                f"ModelProfile with id {profile_id} is referenced by "
                f"{attempt_count} historical attempt(s). It cannot be deleted "
                "while those records must stay explainable.",
            )

        return self._profile_repository.delete(profile_id)

    def _ensure_connection_exists(self, connection_id: int) -> None:
        """Raise ModelProfileError if the referenced connection does not exist."""
        if self._connection_repository.get_by_id(connection_id) is None:
            raise ModelProfileError(
                f"ProviderConnection with id {connection_id} does not exist.",
            )

    def close(self) -> None:
        """Close the service and release resources."""
        self._override_repository.close()
        self._profile_repository.close()

    def __enter__(self) -> ModelProfileService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
