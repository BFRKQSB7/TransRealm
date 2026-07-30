"""P0-T05-M03: Locked glossary candidate interface and budget behavior."""

from __future__ import annotations

from transrealm.application.context import (
    BudgetEstimate,
    ContextBudget,
    ContextCandidate,
    ContextSource,
    EstimateMethod,
)
from transrealm.application.context_composer import ContextComposer
from transrealm.domain.segment import Segment


def _segment(stable_key: str, source_text: str, sequence: int) -> Segment:
    return Segment.create(
        source_document_id=1,
        stable_key=stable_key,
        source_text=source_text,
        sequence=sequence,
    )


def _glossary(content: str, estimate: int) -> ContextCandidate:
    return ContextCandidate(
        source=ContextSource.LOCKED_GLOSSARY,
        segment_id=f"glossary:{content}",
        content=content,
        priority=99,
        reason="locked glossary",
        estimate=BudgetEstimate(char_count=estimate),
    )


class TestLockedGlossaryCandidates:
    """Composer accepts locked glossary candidates and ranks them correctly."""

    def test_empty_glossary_candidates_allowed(self) -> None:
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
            glossary_candidates=[],
            budget=budget,
        )
        assert len(manifest.selected) == 1
        assert manifest.selected[0].source == ContextSource.CURRENT_SEGMENT
        assert manifest.pruned == ()

    def test_glossary_selected_before_neighbors(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-2", "B", 2)
        neighbor = _segment("seg-1", "A", 1)
        glossary = _glossary("term", 1)
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
            neighbors=[neighbor],
            glossary_candidates=[glossary],
            budget=budget,
        )
        sources = [c.source for c in manifest.selected]
        assert sources == [
            ContextSource.CURRENT_SEGMENT,
            ContextSource.LOCKED_GLOSSARY,
            ContextSource.NEIGHBOR_SEGMENT,
        ]

    def test_glossary_keeps_provided_estimate(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "A", 1)
        glossary = _glossary("long term", 5)
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
            glossary_candidates=[glossary],
            budget=budget,
        )
        glossary_candidate = manifest.selected[1]
        assert glossary_candidate.source == ContextSource.LOCKED_GLOSSARY
        assert glossary_candidate.estimate.char_count == 5

    def test_glossary_priority_normalized_above_neighbors(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-2", "B", 2)
        neighbor = _segment("seg-1", "A", 1)
        glossary = ContextCandidate(
            source=ContextSource.LOCKED_GLOSSARY,
            segment_id="glossary:term",
            content="term",
            priority=999,
            reason="locked glossary",
            estimate=BudgetEstimate(char_count=1),
        )
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
            neighbors=[neighbor],
            glossary_candidates=[glossary],
            budget=budget,
        )
        assert manifest.selected[1].source == ContextSource.LOCKED_GLOSSARY
        assert manifest.selected[2].source == ContextSource.NEIGHBOR_SEGMENT


class TestBudgetExhaustion:
    """Budget exhaustion prunes optional context without truncating current."""

    def test_glossary_fits_but_neighbor_pruned(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-2", "B", 2)
        neighbor = _segment("seg-1", "A", 1)
        glossary = _glossary("term", 1)
        budget = ContextBudget(
            total_budget=4,
            reserved_output=1,
            reserved_prompt=1,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=[neighbor],
            glossary_candidates=[glossary],
            budget=budget,
        )
        assert len(manifest.selected) == 2
        assert manifest.selected[1].source == ContextSource.LOCKED_GLOSSARY
        assert len(manifest.pruned) == 1
        assert manifest.pruned[0].source == ContextSource.NEIGHBOR_SEGMENT

    def test_all_optional_pruned_when_budget_tight(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "A", 1)
        glossary = _glossary("x" * 20, 20)
        neighbor = _segment("seg-2", "B", 2)
        budget = ContextBudget(
            total_budget=3,
            reserved_output=1,
            reserved_prompt=1,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=[neighbor],
            glossary_candidates=[glossary],
            budget=budget,
        )
        assert len(manifest.selected) == 1
        assert manifest.selected[0].source == ContextSource.CURRENT_SEGMENT
        assert len(manifest.pruned) == 2

    def test_manifest_records_pruned_glossary(self) -> None:
        composer = ContextComposer()
        current = _segment("seg-1", "A", 1)
        glossary = _glossary("x" * 50, 50)
        budget = ContextBudget(
            total_budget=5,
            reserved_output=1,
            reserved_prompt=1,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = composer.compose(
            profile_id="general",
            template_version="v1",
            current=current,
            glossary_candidates=[glossary],
            budget=budget,
        )
        assert len(manifest.candidates) == 2
        assert len(manifest.selected) == 1
        assert len(manifest.pruned) == 1
        assert manifest.pruned[0].source == ContextSource.LOCKED_GLOSSARY
