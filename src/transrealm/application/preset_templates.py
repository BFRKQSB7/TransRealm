"""Read-only preset Prompt templates.

Preset templates are application constants: they cannot be modified through the
UI or a service. A user edit is saved as a :class:`PromptOverride` that records
the preset version it was based on; rendering resolves the effective template
and fails closed when the parent version no longer matches the current preset.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from transrealm.domain.prompt_override import (
    PromptOverride,
    PromptOverrideError,
    validate_override_template,
)

PRESET_TEMPLATE_ID = "general"
PRESET_TEMPLATE_VERSION = "1.0.0"

# Placeholders the renderer can fill. Kept aligned with
# ``PromptRenderer._build_placeholders`` (a test asserts the exact match).
ALLOWED_PLACEHOLDERS: tuple[str, ...] = (
    "current",
    "context",
    "output_schema",
    "source_language",
    "target_language",
)


@dataclass(frozen=True)
class PresetTemplate:
    """A read-only built-in prompt template."""

    template_id: str
    version: str
    template_text: str


_PRESET_TEMPLATES: dict[str, PresetTemplate] = {
    PRESET_TEMPLATE_ID: PresetTemplate(
        template_id=PRESET_TEMPLATE_ID,
        version=PRESET_TEMPLATE_VERSION,
        template_text=(
            "Translate the following text from $source_language to $target_language.\n\n"
            "Current segment:\n$current\n\n"
            "Context:\n$context\n\n"
        ),
    ),
}


def get_preset_template(template_id: str) -> PresetTemplate | None:
    """Return the preset template with ``template_id``, or None if unknown."""
    return _PRESET_TEMPLATES.get(template_id)


def current_preset() -> PresetTemplate:
    """Return the built-in preset used by every profile by default."""
    preset = get_preset_template(PRESET_TEMPLATE_ID)
    assert preset is not None
    return preset


def resolve_override_template(
    override: PromptOverride,
    preset: PresetTemplate | None,
) -> string.Template:
    """Return the override as a renderable template, rejecting stale parents.

    The override is rejected when its recorded parent template version no longer
    matches the current preset version (fail-closed) or when the persisted text
    no longer validates. The caller renders with the returned template; the
    output contract is still appended by the renderer, so an override can never
    remove the output boundary.
    """
    if preset is None or override.parent_template_version != preset.version:
        current = preset.version if preset is not None else "unknown"
        raise PromptOverrideError(
            f"Prompt override is based on template version "
            f"{override.parent_template_version!r}, but the current preset "
            f"version is {current!r}. Re-create the override from the current "
            "preset before translating.",
        )
    validate_override_template(
        override.template_text,
        allowed_placeholders=ALLOWED_PLACEHOLDERS,
    )
    return string.Template(override.template_text)
