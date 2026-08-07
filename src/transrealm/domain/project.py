"""Project domain model."""

from dataclasses import dataclass
from datetime import datetime


class ProjectError(ValueError):
    """Invalid project configuration or state transition."""


MODE_AUTO = "auto"
MODE_WORKBENCH = "workbench"
SUPPORTED_MODES = (MODE_AUTO, MODE_WORKBENCH)


@dataclass
class Project:
    """A TransRealm translation project."""

    id: int | None
    name: str
    source_language: str
    target_language: str
    created_at: datetime | None
    updated_at: datetime | None
    schema_version: int
    active_profile_id: int | None = None
    mode: str = MODE_AUTO

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source_language: str,
        target_language: str,
        schema_version: int = 1,
        active_profile_id: int | None = None,
        mode: str = MODE_AUTO,
    ) -> "Project":
        """Create a new, unsaved Project instance."""
        project = cls(
            id=None,
            name=name,
            source_language=source_language,
            target_language=target_language,
            created_at=None,
            updated_at=None,
            schema_version=schema_version,
            active_profile_id=active_profile_id,
            mode=mode,
        )
        project._validate_mode()
        return project

    def with_updated_name(self, name: str) -> "Project":
        """Return a copy with a new name."""
        return Project(
            id=self.id,
            name=name,
            source_language=self.source_language,
            target_language=self.target_language,
            created_at=self.created_at,
            updated_at=self.updated_at,
            schema_version=self.schema_version,
            active_profile_id=self.active_profile_id,
            mode=self.mode,
        )

    def with_active_profile(self, profile_id: int | None) -> "Project":
        """Return a copy with a new active profile reference."""
        return Project(
            id=self.id,
            name=self.name,
            source_language=self.source_language,
            target_language=self.target_language,
            created_at=self.created_at,
            updated_at=self.updated_at,
            schema_version=self.schema_version,
            active_profile_id=profile_id,
            mode=self.mode,
        )

    def with_mode(self, mode: str) -> "Project":
        """Return a copy with a new interaction mode.

        Raises:
            ProjectError: If ``mode`` is not a supported interaction mode.
        """
        project = Project(
            id=self.id,
            name=self.name,
            source_language=self.source_language,
            target_language=self.target_language,
            created_at=self.created_at,
            updated_at=self.updated_at,
            schema_version=self.schema_version,
            active_profile_id=self.active_profile_id,
            mode=mode,
        )
        project._validate_mode()
        return project

    def _validate_mode(self) -> None:
        if self.mode not in SUPPORTED_MODES:
            supported = ", ".join(SUPPORTED_MODES)
            raise ProjectError(
                f"Project mode must be one of {supported}: {self.mode!r}.",
            )

