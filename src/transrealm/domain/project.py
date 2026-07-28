"""Project domain model."""

from dataclasses import dataclass
from datetime import datetime


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

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source_language: str,
        target_language: str,
        schema_version: int = 1,
    ) -> "Project":
        """Create a new, unsaved Project instance."""
        return cls(
            id=None,
            name=name,
            source_language=source_language,
            target_language=target_language,
            created_at=None,
            updated_at=None,
            schema_version=schema_version,
        )

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
        )
