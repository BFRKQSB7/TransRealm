"""P0-T05-M01: Context Budget, Manifest and output contract DTOs."""

from __future__ import annotations

import pytest

from transrealm.application.context import (
    BudgetEstimate,
    ContextBudget,
    ContextCandidate,
    ContextManifest,
    ContextSource,
    EstimateMethod,
    OutputContract,
    OutputItem,
)


class TestBudgetEstimate:
    """Size estimates are non-negative or None."""

    def test_accepts_positive_counts(self) -> None:
        estimate = BudgetEstimate(token_count=10, char_count=20)
        assert estimate.token_count == 10
        assert estimate.char_count == 20

    def test_accepts_none_counts(self) -> None:
        estimate = BudgetEstimate()
        assert estimate.token_count is None
        assert estimate.char_count is None

    def test_rejects_negative_token_count(self) -> None:
        with pytest.raises(ValueError, match="token_count"):
            BudgetEstimate(token_count=-1)

    def test_rejects_negative_char_count(self) -> None:
        with pytest.raises(ValueError, match="char_count"):
            BudgetEstimate(char_count=-1)


class TestContextCandidate:
    """Candidates carry source, priority and immutable metadata."""

    def test_create_current_segment_candidate(self) -> None:
        candidate = ContextCandidate(
            source=ContextSource.CURRENT_SEGMENT,
            segment_id="seg-1",
            content="Hello",
            priority=0,
            reason="current segment",
            estimate=BudgetEstimate(token_count=1),
        )
        assert candidate.source == ContextSource.CURRENT_SEGMENT
        assert candidate.segment_id == "seg-1"
        assert candidate.priority == 0

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(ValueError, match="content"):
            ContextCandidate(
                source=ContextSource.NEIGHBOR_SEGMENT,
                segment_id="seg-1",
                content="",
                priority=1,
                reason="neighbor",
                estimate=BudgetEstimate(token_count=1),
            )

    def test_rejects_negative_priority(self) -> None:
        with pytest.raises(ValueError, match="priority"):
            ContextCandidate(
                source=ContextSource.CURRENT_SEGMENT,
                segment_id="seg-1",
                content="Hello",
                priority=-1,
                reason="current",
                estimate=BudgetEstimate(token_count=1),
            )

    def test_rejects_empty_reason(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            ContextCandidate(
                source=ContextSource.CURRENT_SEGMENT,
                segment_id="seg-1",
                content="Hello",
                priority=0,
                reason="",
                estimate=BudgetEstimate(token_count=1),
            )

    def test_metadata_defaults_to_empty_dict(self) -> None:
        candidate = ContextCandidate(
            source=ContextSource.LOCKED_GLOSSARY,
            segment_id=None,
            content="term=word",
            priority=2,
            reason="locked glossary",
            estimate=BudgetEstimate(token_count=1),
        )
        assert candidate.metadata == {}


class TestContextBudget:
    """Budget computes available space and guards reservations."""

    def test_available_space_after_reservations(self) -> None:
        budget = ContextBudget(
            total_budget=100,
            reserved_output=20,
            reserved_prompt=10,
        )
        assert budget.reserved_total == 30
        assert budget.available == 70

    def test_defaults_to_token_estimate(self) -> None:
        budget = ContextBudget(
            total_budget=100,
            reserved_output=0,
            reserved_prompt=0,
        )
        assert budget.estimate_method == EstimateMethod.TOKEN

    def test_rejects_non_positive_total(self) -> None:
        with pytest.raises(ValueError, match="total_budget"):
            ContextBudget(total_budget=0, reserved_output=0, reserved_prompt=0)

    def test_rejects_negative_reserved_output(self) -> None:
        with pytest.raises(ValueError, match="reserved_output"):
            ContextBudget(total_budget=100, reserved_output=-1, reserved_prompt=0)

    def test_rejects_negative_reserved_prompt(self) -> None:
        with pytest.raises(ValueError, match="reserved_prompt"):
            ContextBudget(total_budget=100, reserved_output=0, reserved_prompt=-1)

    def test_rejects_reservations_exceeding_total(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            ContextBudget(total_budget=100, reserved_output=60, reserved_prompt=50)


class TestContextManifest:
    """Manifest records selection, pruning and version metadata."""

    def test_create_manifest(self) -> None:
        budget = ContextBudget(total_budget=100, reserved_output=10, reserved_prompt=10)
        current = ContextCandidate(
            source=ContextSource.CURRENT_SEGMENT,
            segment_id="seg-1",
            content="Hello",
            priority=0,
            reason="current",
            estimate=BudgetEstimate(token_count=1),
        )
        manifest = ContextManifest(
            profile_id="general",
            template_version="v1",
            budget=budget,
            candidates=(current,),
            selected=(current,),
            pruned=(),
            prompt_hash="abc123",
            estimate_method=EstimateMethod.TOKEN,
        )
        assert manifest.profile_id == "general"
        assert manifest.template_version == "v1"
        assert manifest.prompt_hash == "abc123"
        assert len(manifest.selected) == 1
        assert len(manifest.pruned) == 0

    def test_rejects_empty_profile_id(self) -> None:
        with pytest.raises(ValueError, match="profile_id"):
            ContextManifest(
                profile_id="",
                template_version="v1",
                budget=ContextBudget(total_budget=100, reserved_output=0, reserved_prompt=0),
                candidates=(),
                selected=(),
                pruned=(),
                prompt_hash=None,
                estimate_method=EstimateMethod.TOKEN,
            )

    def test_rejects_empty_template_version(self) -> None:
        with pytest.raises(ValueError, match="template_version"):
            ContextManifest(
                profile_id="general",
                template_version="",
                budget=ContextBudget(total_budget=100, reserved_output=0, reserved_prompt=0),
                candidates=(),
                selected=(),
                pruned=(),
                prompt_hash=None,
                estimate_method=EstimateMethod.TOKEN,
            )


class TestOutputItem:
    """Single machine-parseable translation result."""

    def test_create_item(self) -> None:
        item = OutputItem(segment_id="seg-1", translation="你好")
        assert item.segment_id == "seg-1"
        assert item.translation == "你好"
        assert item.warnings == ()
        assert item.notes == ()

    def test_empty_translation_is_allowed(self) -> None:
        item = OutputItem(segment_id="seg-1", translation="")
        assert item.translation == ""

    def test_rejects_empty_segment_id(self) -> None:
        with pytest.raises(ValueError, match="segment_id"):
            OutputItem(segment_id="", translation="你好")

    def test_rejects_none_translation(self) -> None:
        with pytest.raises(ValueError, match="translation"):
            OutputItem(segment_id="seg-1", translation=None)  # type: ignore[arg-type]


class TestOutputContract:
    """Batch contract requires unique segment ids and at least one item."""

    def test_create_contract(self) -> None:
        contract = OutputContract(
            items=(
                OutputItem(segment_id="seg-1", translation="你好"),
                OutputItem(segment_id="seg-2", translation="世界"),
            ),
        )
        assert len(contract.items) == 2

    def test_rejects_empty_contract(self) -> None:
        with pytest.raises(ValueError, match="at least one item"):
            OutputContract(items=())

    def test_rejects_duplicate_segment_ids(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            OutputContract(
                items=(
                    OutputItem(segment_id="seg-1", translation="a"),
                    OutputItem(segment_id="seg-1", translation="b"),
                ),
            )

    def test_preserves_raw_response(self) -> None:
        raw = {"id": "chatcmpl-1", "choices": []}
        contract = OutputContract(
            items=(OutputItem(segment_id="seg-1", translation="x"),),
            raw_response=raw,
        )
        assert contract.raw_response == raw
