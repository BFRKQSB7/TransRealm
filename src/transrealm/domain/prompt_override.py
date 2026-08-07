"""Prompt Override domain model and template-text validation.

A prompt override is the user's copy of a read-only preset template. It records
which preset version it was based on, so the application can reject an override
whose parent template has since changed (fail-closed) instead of silently
rendering against a drifted base. Validation never executes template code:
``string.Template`` only performs placeholder substitution.
"""

from __future__ import annotations

import string
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


class PromptOverrideError(ValueError):
    """Invalid prompt override text or parent template version."""


@dataclass
class PromptOverride:
    """A user's override of a read-only preset template."""

    id: int | None
    model_profile_id: int
    parent_template_version: str
    template_text: str
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        model_profile_id: int,
        parent_template_version: str,
        template_text: str,
        allowed_placeholders: Iterable[str],
    ) -> PromptOverride:
        """Create and validate a new, unsaved PromptOverride."""
        instance = cls(
            id=None,
            model_profile_id=model_profile_id,
            parent_template_version=parent_template_version,
            template_text=template_text,
            created_at=None,
            updated_at=None,
        )
        instance.validate(allowed_placeholders=allowed_placeholders)
        return instance

    def with_text(
        self,
        template_text: str,
        *,
        allowed_placeholders: Iterable[str],
    ) -> PromptOverride:
        """Return a copy with the template text replaced and re-validated."""
        updated = PromptOverride(
            id=self.id,
            model_profile_id=self.model_profile_id,
            parent_template_version=self.parent_template_version,
            template_text=template_text,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        updated.validate(allowed_placeholders=allowed_placeholders)
        return updated

    def validate(self, *, allowed_placeholders: Iterable[str]) -> None:
        """Validate all fields and raise PromptOverrideError on failure."""
        if not isinstance(self.model_profile_id, int) or self.model_profile_id <= 0:
            raise PromptOverrideError(
                "model_profile_id must be a positive integer.",
            )
        if not self.parent_template_version or not self.parent_template_version.strip():
            raise PromptOverrideError("parent_template_version is required.")
        validate_override_template(
            self.template_text,
            allowed_placeholders=allowed_placeholders,
        )


def validate_override_template(
    template_text: str,
    *,
    allowed_placeholders: Iterable[str],
) -> None:
    """Validate override template text.

    The text must be non-empty, parse as a ``string.Template`` with no invalid
    ``$`` usage, and use only the allowed placeholder identifiers. Unknown
    variables are rejected so a stale or mistyped template cannot silently drop
    the current segment or context from the prompt.
    """
    if not isinstance(template_text, str):
        raise PromptOverrideError("template_text must be a string.")
    if not template_text.strip():
        raise PromptOverrideError("Template text must not be empty.")
    try:
        template = string.Template(template_text)
    except ValueError as exc:
        raise PromptOverrideError(f"Invalid template syntax: {exc}") from exc
    if not template.is_valid():
        raise PromptOverrideError(
            "Invalid template syntax: check for a stray '$' — a literal dollar "
            "must be written as '$$' (e.g. '$$5').",
        )
    allowed = set(allowed_placeholders)
    unknown = sorted(set(template.get_identifiers()) - allowed)
    if unknown:
        names = ", ".join(f"${name}" for name in unknown)
        raise PromptOverrideError(f"Unknown template variable(s): {names}.")
