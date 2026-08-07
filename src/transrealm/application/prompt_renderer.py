"""Prompt renderer: combine a Profile template with a ContextManifest.

The renderer produces a prompt text and the expected ``OutputContract`` for
the current segment(s).  It guarantees that the output schema/wrapper is always
present, even when a user or override supplies a custom template.
"""

from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass
from typing import Any

from transrealm.application.context import (
    ContextManifest,
    ContextSource,
    OutputContract,
    OutputItem,
)
from transrealm.application.preset_templates import current_preset


class PromptRenderError(ValueError):
    """Raised when a prompt cannot be rendered from the given inputs."""


DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "translation": {"type": "string"},
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "notes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["segment_id", "translation"],
            },
        },
    },
    "required": ["items"],
}


@dataclass(frozen=True)
class RenderedPrompt:
    """Result of rendering a prompt for a model call."""

    profile_id: str
    template_version: str
    prompt_text: str
    output_contract: OutputContract
    prompt_hash: str


class PromptRenderer:
    """Render a prompt from a template and a context manifest.

    The renderer appends a fixed output-schema instruction to the rendered
    template.  This makes the output contract wrapper unbreakable: callers cannot
    remove it by overriding the template.
    """

    _OUTPUT_SUFFIX = string.Template(
        "\n---OUTPUT CONTRACT---\n"
        "Return only a JSON object matching the following schema. "
        "Do not include any additional text outside the JSON object.\n"
        "$output_schema",
    )

    def __init__(
        self,
        *,
        default_template: string.Template | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        if default_template is None:
            default_template = string.Template(current_preset().template_text)
        self._default_template = default_template
        self._default_schema = output_schema or DEFAULT_OUTPUT_SCHEMA

    def render(
        self,
        *,
        profile_id: str,
        template_version: str,
        template: string.Template | None = None,
        manifest: ContextManifest,
        source_language: str | None = None,
        target_language: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> RenderedPrompt:
        """Render a prompt and expected output contract."""
        if not manifest.selected:
            raise PromptRenderError("Context manifest has no selected candidates.")

        current_candidates = [
            candidate
            for candidate in manifest.selected
            if candidate.source == ContextSource.CURRENT_SEGMENT
        ]
        if not current_candidates:
            raise PromptRenderError(
                "No current segment in selected candidates; cannot build output contract.",
            )

        schema = output_schema if output_schema is not None else self._default_schema
        schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
        placeholders = self._build_placeholders(
            current_candidates,
            manifest,
            schema_json,
            source_language,
            target_language,
        )

        template_to_use = template if template is not None else self._default_template
        try:
            body = template_to_use.substitute(placeholders)
        except (KeyError, ValueError) as exc:
            raise PromptRenderError(f"Template substitution failed: {exc}") from exc

        suffix = self._OUTPUT_SUFFIX.substitute({"output_schema": schema_json})
        prompt_text = f"{body}{suffix}"

        output_contract = OutputContract(
            items=tuple(
                OutputItem(segment_id=candidate.segment_id or "", translation="")
                for candidate in current_candidates
            ),
        )

        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        return RenderedPrompt(
            profile_id=profile_id,
            template_version=template_version,
            prompt_text=prompt_text,
            output_contract=output_contract,
            prompt_hash=prompt_hash,
        )

    @staticmethod
    def _build_placeholders(
        current_candidates: list,
        manifest: ContextManifest,
        schema_json: str,
        source_language: str | None,
        target_language: str | None,
    ) -> dict[str, str]:
        current_text = "\n\n".join(
            candidate.content for candidate in current_candidates
        )
        context_lines = [
            f"[{candidate.reason}] {candidate.content}"
            for candidate in manifest.selected
            if candidate.source != ContextSource.CURRENT_SEGMENT
        ]
        context = "\n".join(context_lines) if context_lines else "None"
        return {
            "current": current_text,
            "context": context,
            "output_schema": schema_json,
            "source_language": source_language or "source",
            "target_language": target_language or "target",
        }
