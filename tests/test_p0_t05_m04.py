"""P0-T05-M04: Prompt renderer and tamper-proof output contract."""

from __future__ import annotations

import string

import pytest

from transrealm.application.context import (
    BudgetEstimate,
    ContextBudget,
    ContextCandidate,
    ContextManifest,
    ContextSource,
    EstimateMethod,
    OutputItem,
)
from transrealm.application.context_composer import ContextComposer
from transrealm.application.prompt_renderer import (
    DEFAULT_OUTPUT_SCHEMA,
    PromptRenderer,
    PromptRenderError,
    RenderedPrompt,
)
from transrealm.domain.segment import Segment


def _segment(stable_key: str, source_text: str, sequence: int) -> Segment:
    return Segment.create(
        source_document_id=1,
        stable_key=stable_key,
        source_text=source_text,
        sequence=sequence,
    )


def _manifest() -> ContextManifest:
    composer = ContextComposer()
    current = _segment("seg-1", "Hello", 1)
    neighbor = _segment("seg-2", "World", 2)
    glossary = ContextCandidate(
        source=ContextSource.LOCKED_GLOSSARY,
        segment_id="glossary:term",
        content="term=word",
        priority=0,
        reason="locked glossary",
        estimate=BudgetEstimate(char_count=9),
    )
    budget = ContextBudget(
        total_budget=100,
        reserved_output=10,
        reserved_prompt=10,
        estimate_method=EstimateMethod.CHARACTER,
    )
    return composer.compose(
        profile_id="general",
        template_version="v1",
        current=current,
        neighbors=[neighbor],
        glossary_candidates=[glossary],
        budget=budget,
    )


class TestPromptRenderer:
    """Renderer produces prompt text and an output contract."""

    def test_rendered_prompt_has_text_and_contract(self) -> None:
        manifest = _manifest()
        renderer = PromptRenderer()
        result = renderer.render(
            profile_id="general",
            template_version="v1",
            manifest=manifest,
        )
        assert isinstance(result, RenderedPrompt)
        assert result.profile_id == "general"
        assert result.template_version == "v1"
        assert "Hello" in result.prompt_text
        assert result.output_contract.items
        assert result.output_contract.items[0].segment_id == "seg-1"
        assert result.output_contract.items[0].translation == ""
        assert result.prompt_hash

    def test_output_schema_is_always_present(self) -> None:
        manifest = _manifest()
        renderer = PromptRenderer()
        result = renderer.render(
            profile_id="general",
            template_version="v1",
            manifest=manifest,
        )
        schema_json = __import__("json").dumps(DEFAULT_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        assert schema_json in result.prompt_text
        assert "OUTPUT CONTRACT" in result.prompt_text

    def test_custom_template_substitutes_placeholders(self) -> None:
        manifest = _manifest()
        renderer = PromptRenderer()
        template = string.Template(
            "Translate $current from $source_language to $target_language.",
        )
        result = renderer.render(
            profile_id="general",
            template_version="v1",
            template=template,
            manifest=manifest,
            source_language="en",
            target_language="zh",
        )
        assert "Translate Hello" in result.prompt_text
        assert "en" in result.prompt_text
        assert "zh" in result.prompt_text
        assert "OUTPUT CONTRACT" in result.prompt_text

    def test_unknown_template_variable_raises(self) -> None:
        manifest = _manifest()
        renderer = PromptRenderer()
        template = string.Template("Translate $unknown.")
        with pytest.raises(PromptRenderError, match="substitution"):
            renderer.render(
                profile_id="general",
                template_version="v1",
                template=template,
                manifest=manifest,
            )

    def test_missing_current_segment_raises(self) -> None:
        manifest = ContextManifest(
            profile_id="general",
            template_version="v1",
            budget=ContextBudget(total_budget=10, reserved_output=0, reserved_prompt=0),
            candidates=(),
            selected=(),
            pruned=(),
            prompt_hash=None,
            estimate_method=EstimateMethod.CHARACTER,
        )
        renderer = PromptRenderer()
        with pytest.raises(PromptRenderError, match="no selected candidates"):
            renderer.render(
                profile_id="general",
                template_version="v1",
                manifest=manifest,
            )

    def test_output_contract_contains_only_current_segments(self) -> None:
        manifest = _manifest()
        renderer = PromptRenderer()
        result = renderer.render(
            profile_id="general",
            template_version="v1",
            manifest=manifest,
        )
        ids = {item.segment_id for item in result.output_contract.items}
        assert ids == {"seg-1"}
        for item in result.output_contract.items:
            assert isinstance(item, OutputItem)
            assert item.translation == ""

    def test_custom_output_schema_is_used(self) -> None:
        manifest = _manifest()
        renderer = PromptRenderer()
        custom_schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = renderer.render(
            profile_id="general",
            template_version="v1",
            manifest=manifest,
            output_schema=custom_schema,
        )
        assert '"answer"' in result.prompt_text
