"""Project-scoped glossary entry domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

ALLOWED_GLOSSARY_ORIGINS = ("user", "import")
PRIORITY_MIN = 0
PRIORITY_MAX = 100
DEFAULT_PRIORITY = 50


class GlossaryEntryError(ValueError):
    """Invalid glossary entry or state transition."""


@dataclass
class GlossaryEntry:
    """A source/target term pair scoped to a single project."""

    id: int | None
    project_id: int
    source_term: str
    target_term: str
    scope: str
    priority: int
    is_locked: bool
    origin: str
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        project_id: int,
        source_term: str,
        target_term: str,
        scope: str,
        priority: int = DEFAULT_PRIORITY,
        is_locked: bool = False,
        origin: str = "user",
    ) -> GlossaryEntry:
        """Create and validate a new, unsaved GlossaryEntry."""
        instance = cls(
            id=None,
            project_id=project_id,
            source_term=source_term,
            target_term=target_term,
            scope=scope,
            priority=priority,
            is_locked=is_locked,
            origin=origin,
            created_at=None,
            updated_at=None,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate all fields, normalize whitespace, and raise on failure.

        Text fields are stripped so that ``" Apple "`` and ``"Apple"`` compare
        equal under the ``(project_id, source_term)`` uniqueness domain.
        """
        if not isinstance(self.project_id, int) or self.project_id <= 0:
            raise GlossaryEntryError(
                "project_id must be a positive integer.",
            )
        self.source_term = self._normalize_text(self.source_term, "source_term")
        self.target_term = self._normalize_text(self.target_term, "target_term")
        self.scope = self._normalize_text(self.scope, "scope")
        if not self.source_term:
            raise GlossaryEntryError("source_term is required.")
        if not self.target_term:
            raise GlossaryEntryError("target_term is required.")
        if not self.scope:
            raise GlossaryEntryError("scope is required.")
        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or not (PRIORITY_MIN <= self.priority <= PRIORITY_MAX)
        ):
            raise GlossaryEntryError(
                f"priority must be an integer between {PRIORITY_MIN} and "
                f"{PRIORITY_MAX}.",
            )
        if not isinstance(self.is_locked, bool):
            raise GlossaryEntryError("is_locked must be a boolean.")
        if self.origin not in ALLOWED_GLOSSARY_ORIGINS:
            raise GlossaryEntryError(
                f"origin must be one of {', '.join(ALLOWED_GLOSSARY_ORIGINS)}.",
            )

    @staticmethod
    def _normalize_text(value: object, name: str) -> str:
        """Return a stripped string or raise a clear error for non-strings."""
        if not isinstance(value, str):
            raise GlossaryEntryError(f"{name} must be a string.")
        return value.strip()

    def with_updated_fields(
        self,
        *,
        source_term: str | None = None,
        target_term: str | None = None,
        scope: str | None = None,
        priority: int | None = None,
        is_locked: bool | None = None,
    ) -> GlossaryEntry:
        """Return a copy with selected fields replaced and re-validated."""
        updated = GlossaryEntry(
            id=self.id,
            project_id=self.project_id,
            source_term=source_term if source_term is not None else self.source_term,
            target_term=target_term if target_term is not None else self.target_term,
            scope=scope if scope is not None else self.scope,
            priority=priority if priority is not None else self.priority,
            is_locked=is_locked if is_locked is not None else self.is_locked,
            origin=self.origin,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        updated.validate()
        return updated
