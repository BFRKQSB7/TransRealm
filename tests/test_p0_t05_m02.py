"""P0-T05-M02: Context Composer for current and adjacent segments."""

from __future__ import annotations

import pytest

from transrealm.application.context import (
    BudgetEstimate,
    ContextBudget,
    ContextSource,
    EstimateMethod,
)
from transrealm.application.context_composer import ContextBudgetError, ContextComposer
from transrealm.domain.segment import Segment


def _segment(
    stable_key: str,
    source_text: str,
    sequence: int,
) -> Segment:
    return Segment.create(
        source_document_id=1,
        stable_key=stable_key,
        source_text=source_text,
        sequence=sequence,
    )


class TestContextComposerSelection:
    """Composer selects current segment and neighbors within budget."""

    def test_current_segment_always_selected(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-2", "Hello", 2)
        budget = ContextBudget(
            total_budget=100,
            reserved_output=10,
            reserved_prompt=10,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            budget=budget,
        )
        assert len(manifest.selected) == 1
        assert manifest.selected[0].source == ContextSource.CURRENT_SEGMENT
        assert manifest.selected[0].segment_id == "seg-2"
        assert manifest.pruned == ()

    def test_all_neighbors_selected_when_budget_allows(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-2", "B", 2)
        neighbors = [
            _segment("seg-1", "A", 1),
            _segment("seg-3", "C", 3),
        ]
        budget = ContextBudget(
            total_budget=100,
            reserved_output=10,
            reserved_prompt=10,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=neighbors,
            budget=budget,
        )
        assert len(manifest.selected) == 3
        assert [c.segment_id for c in manifest.selected] == [
            "seg-2",
            "seg-1",
            "seg-3",
        ]
        assert manifest.pruned == ()

    def test_far_neighbor_pruned_when_budget_tight(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-2", "B", 2)
        neighbors = [
            _segment("seg-1", "A", 1),
            _segment("seg-10", "x" * 20, 10),
        ]
        budget = ContextBudget(
            total_budget=20,
            reserved_output=5,
            reserved_prompt=5,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=neighbors,
            budget=budget,
        )
        assert len(manifest.selected) == 2
        assert manifest.selected[1].segment_id == "seg-1"
        assert len(manifest.pruned) == 1
        assert manifest.pruned[0].segment_id == "seg-10"

    def test_neighbors_selected_by_proximity(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-5", "E", 5)
        neighbors = [
            _segment("seg-8", "H", 8),
            _segment("seg-4", "D", 4),
            _segment("seg-6", "F", 6),
        ]
        budget = ContextBudget(
            total_budget=13,
            reserved_output=5,
            reserved_prompt=5,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=neighbors,
            budget=budget,
        )
        selected_ids = [c.segment_id for c in manifest.selected]
        assert selected_ids == ["seg-5", "seg-4", "seg-6"]
        assert len(manifest.pruned) == 1
        assert manifest.pruned[0].segment_id == "seg-8"

    def test_empty_neighbors_allowed(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "A", 1)
        budget = ContextBudget(
            total_budget=10,
            reserved_output=1,
            reserved_prompt=1,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=[],
            budget=budget,
        )
        assert len(manifest.selected) == 1
        assert manifest.candidates == manifest.selected
        assert manifest.pruned == ()

    def test_duplicate_current_in_neighbors_is_ignored(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "A", 1)
        neighbors = [_segment("seg-1", "A", 1)]
        budget = ContextBudget(
            total_budget=10,
            reserved_output=1,
            reserved_prompt=1,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=neighbors,
            budget=budget,
        )
        assert len(manifest.candidates) == 1
        assert len(manifest.selected) == 1


class TestContextComposerBudget:
    """Budget boundaries and estimate methods."""

    def test_current_segment_too_large_raises(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "x" * 1000, 1)
        budget = ContextBudget(
            total_budget=100,
            reserved_output=10,
            reserved_prompt=10,
        )
        with pytest.raises(ContextBudgetError, match="exceeds"):
            composer.compose(
                profile_id="general",
                template_version="v1",
                current=current,
                budget=budget,
            )

    def test_empty_current_segment_raises(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "", 1)
        budget = ContextBudget(
            total_budget=100,
            reserved_output=10,
            reserved_prompt=10,
            estimate_method=EstimateMethod.CHARACTER,
        )
        with pytest.raises(ContextBudgetError, match="empty"):
            composer.compose(
                profile_id="general",
                template_version="v1",
                current=current,
                budget=budget,
            )

    def test_token_estimate_method(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "Hello world", 1)
        budget = ContextBudget(
            total_budget=20,
            reserved_output=5,
            reserved_prompt=5,
            estimate_method=EstimateMethod.TOKEN,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            budget=budget,
        )
        assert manifest.estimate_method == EstimateMethod.TOKEN
        assert len(manifest.selected) == 1
        assert manifest.selected[0].estimate.token_count is not None

    def test_custom_estimator_used(self) -> None:
        calls: list[tuple[str, EstimateMethod]] = []

        def estimator(content: str, method: EstimateMethod) -> BudgetEstimate:
            calls.append((content, method))
            return BudgetEstimate(char_count=len(content))

        composer = ContextComposer(estimator=estimator)
        current = _segment("seg-1", "A", 1)
        neighbors = [_segment("seg-2", "B", 2)]
        budget = ContextBudget(
            total_budget=10,
            reserved_output=1,
            reserved_prompt=1,
            estimate_method=EstimateMethod.CHARACTER,
        )
        composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=neighbors,
            budget=budget,
        )
        assert calls == [("A", EstimateMethod.CHARACTER), ("B", EstimateMethod.CHARACTER)]

    def test_manifest_records_pruned_candidates(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-2", "B", 2)
        neighbors = [
            _segment("seg-1", "A", 1),
            _segment("seg-3", "x" * 50, 3),
        ]
        budget = ContextBudget(
            total_budget=15,
            reserved_output=5,
            reserved_prompt=5,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=neighbors,
            budget=budget,
        )
        assert len(manifest.candidates) == 3
        assert len(manifest.selected) == 2
        assert len(manifest.pruned) == 1
        assert manifest.selected[0].source == ContextSource.CURRENT_SEGMENT
        assert manifest.selected[1].source == ContextSource.NEIGHBOR_SEGMENT
        assert manifest.pruned[0].source == ContextSource.NEIGHBOR_SEGMENT

