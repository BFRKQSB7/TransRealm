"""Context Composer: apply the Phase 0 minimal context budget rules.

The composer turns a current Segment and a list of neighbor Segments into a
``ContextManifest``.  It never truncates the current segment; if the current
segment does not fit, it raises ``ContextBudgetError``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from transrealm.application.context import (
    BudgetEstimate,
    ContextBudget,
    ContextCandidate,
    ContextManifest,
    ContextSource,
    EstimateMethod,
)
from transrealm.domain.segment import Segment


class ContextBudgetError(ValueError):
    """Raised when mandatory context cannot fit into the available budget."""


EstimateFn = Callable[[str, EstimateMethod], BudgetEstimate]


def default_estimate(content: str, method: EstimateMethod) -> BudgetEstimate:
    """Conservative default estimate: 1 token ~= 4 characters."""
    char_count = len(content)
    token_count = max(1, char_count // 4)
    return BudgetEstimate(token_count=token_count, char_count=char_count)


def _candidate_size(candidate: ContextCandidate, method: EstimateMethod) -> int:
    """Return the size of a candidate using the requested estimate method."""
    if method == EstimateMethod.TOKEN:
        if candidate.estimate.token_count is not None:
            return candidate.estimate.token_count
        if candidate.estimate.char_count is not None:
            return candidate.estimate.char_count
    else:
        if candidate.estimate.char_count is not None:
            return candidate.estimate.char_count
        if candidate.estimate.token_count is not None:
            return candidate.estimate.token_count
    raise ValueError(
        f"Candidate {candidate.segment_id!r} has no usable estimate for {method}.",
    )


class ContextComposer:
    """Rule-based context composer for a single model call.

    The composer is intentionally deterministic and stateless.  It accepts an
    optional ``estimator`` so tests can inject exact sizes without changing the
    public API.
    """

    _GLOSSARY_PRIORITY = 1
    _NOTES_PRIORITY = 2

    def __init__(self, estimator: EstimateFn | None = None) -> None:
        self._estimator = estimator or default_estimate

    def compose(
        self,
        *,
        profile_id: str,
        template_version: str,
        current: Segment,
        neighbors: Sequence[Segment] | None = None,
        glossary_candidates: Sequence[ContextCandidate] | None = None,
        notes: str = "",
        budget: ContextBudget,
    ) -> ContextManifest:
        """Select context candidates for ``current`` within ``budget``.

        Selection order follows the authority rules from
        ``docs/ARCHITECTURE.md``:

        1. Current segment (mandatory, never truncated).
        2. Locked glossary entries.
        3. Non-empty Project/Job Notes.
        4. Neighbor segments by proximity, then sequence.

        If the current segment does not fit, ``ContextBudgetError`` is raised.
        Locked glossary and Notes are protected. If they cannot fit with the
        current segment, fail before an Attempt or provider call. Only neighbor
        context is pruned when the budget is exhausted.
        """
        if not current.source_text:
            raise ContextBudgetError("Current segment source text is empty.")

        current_candidate = ContextCandidate(
            source=ContextSource.CURRENT_SEGMENT,
            segment_id=current.stable_key,
            content=current.source_text,
            priority=0,
            reason="current segment",
            estimate=self._estimator(current.source_text, budget.estimate_method),
        )
        current_size = _candidate_size(current_candidate, budget.estimate_method)
        if current_size > budget.available:
            raise ContextBudgetError(
                f"Current segment size {current_size} exceeds available budget "
                f"{budget.available}.",
            )

        glossary = self._normalize_glossary_candidates(glossary_candidates or [])
        notes_candidate = (
            ContextCandidate(
                source=ContextSource.JOB_NOTES,
                segment_id=None,
                content=notes,
                priority=self._NOTES_PRIORITY,
                reason="job notes",
                estimate=self._estimator(notes, budget.estimate_method),
            )
            if notes.strip()
            else None
        )
        protected = [*glossary, *([notes_candidate] if notes_candidate else [])]
        protected_size = sum(
            _candidate_size(candidate, budget.estimate_method) for candidate in protected
        )
        if current_size + protected_size > budget.available:
            raise ContextBudgetError(
                "Current segment, locked glossary and Notes exceed available context budget."
            )

        selected: list[ContextCandidate] = [current_candidate, *protected]
        pruned: list[ContextCandidate] = []
        remaining = budget.available - current_size - protected_size
        neighbor_candidates = self._build_neighbor_candidates(
            current,
            neighbors or [],
            budget.estimate_method,
        )

        # Keep a proximity prefix: a farther neighbor never displaces a nearer
        # one, even when its individual text would happen to be shorter.
        neighbor_budget_exhausted = False
        for candidate in neighbor_candidates:
            size = _candidate_size(candidate, budget.estimate_method)
            if not neighbor_budget_exhausted and size <= remaining:
                selected.append(candidate)
                remaining -= size
            else:
                pruned.append(candidate)
                neighbor_budget_exhausted = True

        return ContextManifest(
            profile_id=profile_id,
            template_version=template_version,
            budget=budget,
            candidates=(current_candidate, *protected, *neighbor_candidates),
            selected=tuple(selected),
            pruned=tuple(pruned),
            prompt_hash=None,
            estimate_method=budget.estimate_method,
        )

    def _normalize_glossary_candidates(
        self,
        candidates: Sequence[ContextCandidate],
    ) -> list[ContextCandidate]:
        """Return glossary candidates with normalized high priority.

        Callers provide ``ContextCandidate`` values for locked glossary entries.
        The composer normalizes their priority so they rank just below the
        current segment and above neighbor segments, regardless of the
        caller-provided priority value.
        """
        normalized: list[ContextCandidate] = []
        for candidate in candidates:
            normalized.append(
                ContextCandidate(
                    source=ContextSource.LOCKED_GLOSSARY,
                    segment_id=candidate.segment_id,
                    content=candidate.content,
                    priority=self._GLOSSARY_PRIORITY,
                    reason=candidate.reason or "locked glossary",
                    estimate=candidate.estimate,
                    metadata=dict(candidate.metadata),
                ),
            )
        return normalized

    def _build_neighbor_candidates(
        self,
        current: Segment,
        neighbors: Sequence[Segment],
        method: EstimateMethod,
    ) -> list[ContextCandidate]:
        """Build neighbor candidates, sorted by distance then sequence."""
        seen = {current.stable_key}
        scored: list[tuple[int, Segment]] = []

        for neighbor in neighbors:
            if not neighbor.source_text or neighbor.stable_key in seen:
                continue
            seen.add(neighbor.stable_key)
            distance = abs(neighbor.sequence - current.sequence)
            scored.append((distance, neighbor))

        scored.sort(key=lambda item: (item[0], item[1].sequence))

        return [
            ContextCandidate(
                source=ContextSource.NEIGHBOR_SEGMENT,
                segment_id=neighbor.stable_key,
                content=neighbor.source_text,
                priority=distance + 1,
                reason=f"neighbor segment ({distance} away)",
                estimate=self._estimator(neighbor.source_text, method),
                metadata={"sequence": neighbor.sequence},
            )
            for distance, neighbor in scored
        ]
