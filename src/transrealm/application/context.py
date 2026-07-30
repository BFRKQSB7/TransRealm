"""Context Budget, Manifest and output contract DTOs.

These value objects describe what context is gathered, how it fits into a
model's context budget, and the machine-parseable output expected from the
model. They contain no persistence, network or UI code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ContextSource(Enum):
    """Authority-ordered source of a context candidate."""

    CURRENT_SEGMENT = auto()
    NEIGHBOR_SEGMENT = auto()
    LOCKED_GLOSSARY = auto()
    # Phase 2 sources; kept here so manifests remain forward-compatible.
    CHARACTER_DATA = auto()
    TRANSLATION_MEMORY = auto()
    RAG = auto()
    WORLD_STATE = auto()


class EstimateMethod(Enum):
    """How the size of a candidate is estimated."""

    TOKEN = auto()
    CHARACTER = auto()


@dataclass(frozen=True)
class BudgetEstimate:
    """Estimated size of a context contribution."""

    token_count: int | None = None
    char_count: int | None = None

    def __post_init__(self) -> None:
        if self.token_count is not None and self.token_count < 0:
            raise ValueError(
                f"token_count must be non-negative: {self.token_count}",
            )
        if self.char_count is not None and self.char_count < 0:
            raise ValueError(
                f"char_count must be non-negative: {self.char_count}",
            )


@dataclass(frozen=True)
class ContextCandidate:
    """A single piece of context that may be included in a prompt."""

    source: ContextSource
    segment_id: str | None
    content: str
    priority: int
    reason: str
    estimate: BudgetEstimate
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.content is None or self.content == "":
            raise ValueError("ContextCandidate content must be a non-empty string.")
        if self.priority < 0:
            raise ValueError(f"priority must be non-negative: {self.priority}")
        if self.reason is None or self.reason == "":
            raise ValueError("ContextCandidate reason must be a non-empty string.")


@dataclass(frozen=True)
class ContextBudget:
    """Rule-based budget for a single model call.

    ``available`` is what remains after reserving space for the prompt
    scaffolding and the expected output.
    """

    total_budget: int
    reserved_output: int
    reserved_prompt: int
    estimate_method: EstimateMethod = EstimateMethod.TOKEN

    def __post_init__(self) -> None:
        if self.total_budget <= 0:
            raise ValueError(
                f"total_budget must be positive: {self.total_budget}",
            )
        if self.reserved_output < 0:
            raise ValueError(
                f"reserved_output must be non-negative: {self.reserved_output}",
            )
        if self.reserved_prompt < 0:
            raise ValueError(
                f"reserved_prompt must be non-negative: {self.reserved_prompt}",
            )
        if self.reserved_total > self.total_budget:
            raise ValueError(
                f"reserved {self.reserved_total} exceeds total budget "
                f"{self.total_budget}.",
            )

    @property
    def reserved_total(self) -> int:
        return self.reserved_output + self.reserved_prompt

    @property
    def available(self) -> int:
        return self.total_budget - self.reserved_total


@dataclass(frozen=True)
class ContextManifest:
    """Immutable record of what context was selected, pruned and why."""

    profile_id: str
    template_version: str
    budget: ContextBudget
    candidates: tuple[ContextCandidate, ...]
    selected: tuple[ContextCandidate, ...]
    pruned: tuple[ContextCandidate, ...]
    prompt_hash: str | None
    estimate_method: EstimateMethod

    def __post_init__(self) -> None:
        if self.profile_id is None or self.profile_id == "":
            raise ValueError("profile_id must be a non-empty string.")
        if self.template_version is None or self.template_version == "":
            raise ValueError("template_version must be a non-empty string.")


@dataclass(frozen=True)
class OutputItem:
    """A single machine-parseable translation result."""

    segment_id: str
    translation: str
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.segment_id is None or self.segment_id == "":
            raise ValueError("segment_id must be a non-empty string.")
        if self.translation is None:
            raise ValueError("translation must not be None.")


@dataclass(frozen=True)
class OutputContract:
    """Validated response contract for one or more segments."""

    items: tuple[OutputItem, ...]
    raw_response: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("OutputContract must contain at least one item.")
        ids = [item.segment_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("OutputContract segment_ids must be unique.")
