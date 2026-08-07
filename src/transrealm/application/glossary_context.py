"""Map locked glossary entries to deterministic ContextCandidates.

P1-T04-M03 bridges the project-scoped glossary into the existing context
candidate representation so the ContextComposer injects locked terms before
neighbor segments, in priority/stable order. This module is a pure function:
the "only locked, only this project" filter is enforced by the repository
query (``list_locked_by_project``), not by the mapper.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from transrealm.application.context import (
    BudgetEstimate,
    ContextCandidate,
    ContextSource,
    EstimateMethod,
)
from transrealm.application.context_composer import default_estimate
from transrealm.domain.glossary_entry import GlossaryEntry

GLOSSARY_REASON = "locked glossary"


def build_glossary_candidates(
    entries: Sequence[GlossaryEntry],
    *,
    estimate_method: EstimateMethod = EstimateMethod.CHARACTER,
    estimator: Callable[[str, EstimateMethod], BudgetEstimate] | None = None,
) -> list[ContextCandidate]:
    """Map glossary entries to context candidates, preserving input order.

    Callers supply entries already ordered by the stable ``priority DESC, id``
    contract (``list_locked_by_project``); the returned candidates keep that
    order so the composer's stable priority sort ranks them deterministically
    ahead of neighbor segments. Only locked, project-scoped entries should be
    passed; the filter lives in the repository query.
    """
    estimate = estimator or default_estimate
    candidates: list[ContextCandidate] = []
    for entry in entries:
        content = f"{entry.source_term} -> {entry.target_term}"
        candidates.append(
            ContextCandidate(
                source=ContextSource.LOCKED_GLOSSARY,
                segment_id=f"glossary:{entry.source_term}",
                content=content,
                priority=entry.priority,
                reason=GLOSSARY_REASON,
                estimate=estimate(content, estimate_method),
                metadata={
                    "entry_id": entry.id,
                    "source_term": entry.source_term,
                    "target_term": entry.target_term,
                    "scope": entry.scope,
                    "priority": entry.priority,
                    "origin": entry.origin,
                },
            ),
        )
    return candidates
