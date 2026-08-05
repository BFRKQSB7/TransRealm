"""Translation revision domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class TranslationRevisionError(ValueError):
    """Invalid translation revision state or configuration."""


@dataclass
class TranslationRevision:
    """A single immutable translation result for a segment."""

    id: int | None
    segment_id: int
    text: str
    origin: str
    attempt_id: int | None
    is_locked: bool
    created_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        segment_id: int,
        text: str,
        origin: str,
        attempt_id: int | None = None,
    ) -> TranslationRevision:
        """Create a new, unsaved translation revision."""
        instance = cls(
            id=None,
            segment_id=segment_id,
            text=text,
            origin=origin,
            attempt_id=attempt_id,
            is_locked=False,
            created_at=None,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate fields and raise TranslationRevisionError on failure."""
        if not isinstance(self.segment_id, int) or self.segment_id <= 0:
            raise TranslationRevisionError("segment_id must be a positive integer.")

        if self.text is None:
            raise TranslationRevisionError("text is required.")

        if self.origin not in {"ai", "user", "import"}:
            raise TranslationRevisionError(f"Invalid revision origin: {self.origin!r}")

        if not isinstance(self.is_locked, bool):
            raise TranslationRevisionError("is_locked must be a boolean.")
