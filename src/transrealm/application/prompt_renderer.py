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
    output_protocol: str = "json"


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
        output_protocol: str = "json",
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
        protocol = output_protocol.strip().lower().replace("-", "_")
        if protocol in {"plain", "plain_text"}:
            protocol = "text"
        if protocol == "json_object":
            protocol = "json"
        if protocol not in {"text", "json"}:
            raise PromptRenderError("Output protocol must be text or json.")
        if protocol == "text" and len(current_candidates) != 1:
            raise PromptRenderError("Plain text output requires exactly one target segment.")

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

        # Older presets and valid user overrides may omit $notes. Keep them
        # compatible while ensuring saved Notes reach every applicable call.
        if placeholders["notes"] and "notes" not in template_to_use.get_identifiers():
            body += f"\n\nJob Notes:\n{placeholders['notes']}"

        if protocol == "text":
            suffix = (
                "\n---OUTPUT CONTRACT---\n"
                "Return only the translation of the current segment as plain text. "
                "Do not translate context separately. Do not include reasoning, "
                "explanations, JSON wrappers or Markdown fences.\n"
            )
        else:
            target_ids = json.dumps(
                [candidate.segment_id for candidate in current_candidates], ensure_ascii=False
            )
            suffix = self._OUTPUT_SUFFIX.substitute({"output_schema": schema_json})
            suffix += f"\nTarget segment IDs (in order): {target_ids}\n"
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
            output_protocol=protocol,
        )

    @staticmethod
    def _build_placeholders(
        current_candidates: list,
        manifest: ContextManifest,
        schema_json: str,
        source_language: str | None,
        target_language: str | None,
    ) -> dict[str, str]:
        current_text = "\n\n".join(candidate.content for candidate in current_candidates)
        context_lines = [
            f"[{candidate.reason}] {candidate.content}"
            for candidate in manifest.selected
            if candidate.source not in (ContextSource.CURRENT_SEGMENT, ContextSource.JOB_NOTES)
        ]
        context = "\n".join(context_lines) if context_lines else "None"
        notes = "\n\n".join(
            candidate.content
            for candidate in manifest.selected
            if candidate.source == ContextSource.JOB_NOTES
        )
        return {
            "current": current_text,
            "context": context,
            "notes": notes,
            "output_schema": schema_json,
            "source_language": source_language or "source",
            "target_language": target_language or "target",
        }
