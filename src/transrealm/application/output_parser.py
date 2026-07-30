"""Output parsing and validation DTOs for model responses.

This module defines the data structures and error taxonomy used by the
Output Parser / Validator (P0-T06).  It contains no network, persistence or
model-calling code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from transrealm.application.context import OutputContract


class IssueCategory(Enum):
    """Classification of output parsing/validation failures."""

    INVALID_JSON = auto()
    MISSING_FIELD = auto()
    TYPE_ERROR = auto()
    DUPLICATE_ID = auto()
    MISSING_ID = auto()
    UNKNOWN_ID = auto()
    ORDER_MISMATCH = auto()
    EMPTY_TRANSLATION = auto()
    NON_STRING_TRANSLATION = auto()
    CONTAMINATION = auto()
    REPAIR_LIMIT_EXCEEDED = auto()


class OutputParseError(ValueError):
    """Raised when a model response cannot be parsed or validated.

    The exception carries an ``IssueCategory`` so callers can decide whether
    to attempt a repair, record a failed attempt, or surface the error.
    """

    def __init__(
        self,
        *,
        category: IssueCategory,
        message: str,
        segment_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.segment_id = segment_id

    def __str__(self) -> str:
        prefix = f"[{self.segment_id}] " if self.segment_id else ""
        return f"{prefix}{self.category.name}: {super().__str__()}"


@dataclass(frozen=True)
class TranslationCandidate:
    """A single translation extracted from a model response."""

    segment_id: str
    translation: str
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.segment_id:
            raise ValueError("segment_id must be a non-empty string.")
        if self.translation is None:
            raise ValueError("translation must not be None.")


@dataclass(frozen=True)
class ParseIssue:
    """A single issue found while validating a model response."""

    category: IssueCategory
    message: str
    segment_id: str | None = None
    repairable: bool = False


@dataclass(frozen=True)
class RepairDescriptor:
    """Describes a repair strategy and how many attempts remain."""

    strategy: str
    max_attempts: int
    attempted: int = 0

    def __post_init__(self) -> None:
        if not self.strategy:
            raise ValueError("strategy must be a non-empty string.")
        if self.max_attempts < 0:
            raise ValueError("max_attempts must be non-negative.")
        if self.attempted < 0:
            raise ValueError("attempted must be non-negative.")
        if self.attempted > self.max_attempts:
            raise ValueError("attempted cannot exceed max_attempts.")

    @property
    def can_retry(self) -> bool:
        return self.attempted < self.max_attempts


@dataclass(frozen=True)
class ValidationReport:
    """Result of validating a model response against an output contract."""

    candidates: tuple[TranslationCandidate, ...]
    issues: tuple[ParseIssue, ...]
    repair_descriptor: RepairDescriptor | None = None
    raw_response: dict[str, Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        ids = [candidate.segment_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("ValidationReport candidate segment_ids must be unique.")

    @property
    def is_valid(self) -> bool:
        return not self.issues and bool(self.candidates)


_extract_json_re = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Markers that suggest a translation value has been polluted with explanatory
# text or code blocks instead of containing only the target translation.
_CONTAMINATION_MARKERS = ("```",)


def _is_contaminated(translation: str) -> bool:
    return any(marker in translation for marker in _CONTAMINATION_MARKERS)


def _extract_json(text: str) -> str | None:
    """Try to extract a JSON object or array from a fenced/markdown block."""
    fenced = _extract_json_re.search(text)
    if fenced:
        return fenced.group(1)
    for start in ("{", "["):
        index = text.find(start)
        if index != -1:
            return text[index:]
    return None


class OutputParser:
    """Parse a model response and validate it against an ``OutputContract``."""

    def parse(
        self,
        text: str,
        *,
        output_contract: OutputContract,
        repair_descriptor: RepairDescriptor | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> ValidationReport:
        """Parse ``text`` and validate it against ``output_contract``.

        If the raw text is not valid JSON, the parser attempts a single repair
        by extracting JSON from a markdown fence.  This consumes one repair
        attempt from ``repair_descriptor`` if provided.
        """
        if repair_descriptor is not None and not repair_descriptor.can_retry:
            return ValidationReport(
                candidates=(),
                issues=(
                    ParseIssue(
                        category=IssueCategory.REPAIR_LIMIT_EXCEEDED,
                        message="Repair limit reached; cannot re-parse response.",
                        repairable=False,
                    ),
                ),
                repair_descriptor=repair_descriptor,
                raw_response=raw_response,
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            extracted = _extract_json(text)
            if extracted is None:
                return ValidationReport(
                    candidates=(),
                    issues=(
                        ParseIssue(
                            category=IssueCategory.INVALID_JSON,
                            message="Response is not valid JSON.",
                            repairable=repair_descriptor is not None,
                        ),
                    ),
                    repair_descriptor=repair_descriptor,
                    raw_response=raw_response,
                )
            try:
                data = json.loads(extracted)
            except json.JSONDecodeError:
                return ValidationReport(
                    candidates=(),
                    issues=(
                        ParseIssue(
                            category=IssueCategory.INVALID_JSON,
                            message="Extracted fenced content is not valid JSON.",
                            repairable=False,
                        ),
                    ),
                    repair_descriptor=repair_descriptor,
                    raw_response=raw_response,
                )
            if repair_descriptor is not None:
                repair_descriptor = RepairDescriptor(
                    strategy=repair_descriptor.strategy,
                    max_attempts=repair_descriptor.max_attempts,
                    attempted=repair_descriptor.attempted + 1,
                )

        return self._validate(data, output_contract, repair_descriptor, raw_response)

    def _validate(
        self,
        data: Any,
        output_contract: OutputContract,
        repair_descriptor: RepairDescriptor | None,
        raw_response: dict[str, Any] | None,
    ) -> ValidationReport:
        issues: list[ParseIssue] = []

        if not isinstance(data, dict):
            issues.append(
                ParseIssue(
                    category=IssueCategory.TYPE_ERROR,
                    message="Top-level JSON value must be an object.",
                    repairable=False,
                ),
            )
            return ValidationReport(
                candidates=(),
                issues=tuple(issues),
                repair_descriptor=repair_descriptor,
                raw_response=raw_response,
            )

        items = data.get("items")
        if not isinstance(items, list):
            issues.append(
                ParseIssue(
                    category=IssueCategory.MISSING_FIELD,
                    message="Missing or invalid items array.",
                    repairable=False,
                ),
            )
            return ValidationReport(
                candidates=(),
                issues=tuple(issues),
                repair_descriptor=repair_descriptor,
                raw_response=raw_response,
            )

        expected_items = output_contract.items
        if len(items) != len(expected_items):
            issues.append(
                ParseIssue(
                    category=IssueCategory.ORDER_MISMATCH,
                    message=f"Expected {len(expected_items)} items, got {len(items)}.",
                    repairable=False,
                ),
            )

        expected_ids = {item.segment_id for item in expected_items}
        seen_ids: set[str] = set()
        candidates: list[TranslationCandidate] = []

        for index, raw_item in enumerate(items):
            if not isinstance(raw_item, dict):
                issues.append(
                    ParseIssue(
                        category=IssueCategory.TYPE_ERROR,
                        message=f"Item at index {index} is not an object.",
                        repairable=False,
                    ),
                )
                continue

            segment_id = raw_item.get("segment_id")
            if not isinstance(segment_id, str):
                issues.append(
                    ParseIssue(
                        category=IssueCategory.TYPE_ERROR,
                        message=f"segment_id at index {index} is not a string.",
                        segment_id=str(segment_id) if segment_id is not None else None,
                        repairable=False,
                    ),
                )
                continue

            if segment_id in seen_ids:
                issues.append(
                    ParseIssue(
                        category=IssueCategory.DUPLICATE_ID,
                        message=f"Duplicate segment_id '{segment_id}'.",
                        segment_id=segment_id,
                        repairable=False,
                    ),
                )
                continue
            seen_ids.add(segment_id)

            if segment_id not in expected_ids:
                issues.append(
                    ParseIssue(
                        category=IssueCategory.UNKNOWN_ID,
                        message=f"Unexpected segment_id '{segment_id}'.",
                        segment_id=segment_id,
                        repairable=False,
                    ),
                )
                continue

            translation = raw_item.get("translation")
            if not isinstance(translation, str):
                issues.append(
                    ParseIssue(
                        category=IssueCategory.NON_STRING_TRANSLATION,
                        message=f"translation for '{segment_id}' is not a string.",
                        segment_id=segment_id,
                        repairable=False,
                    ),
                )
                continue

            if translation == "":
                issues.append(
                    ParseIssue(
                        category=IssueCategory.EMPTY_TRANSLATION,
                        message=f"translation for '{segment_id}' is empty.",
                        segment_id=segment_id,
                        repairable=True,
                    ),
                )
                continue

            if _is_contaminated(translation):
                issues.append(
                    ParseIssue(
                        category=IssueCategory.CONTAMINATION,
                        message=f"translation for '{segment_id}' contains markdown fence markers.",
                        segment_id=segment_id,
                        repairable=True,
                    ),
                )
                continue

            warnings = raw_item.get("warnings", [])
            notes = raw_item.get("notes", [])
            if not isinstance(warnings, list) or not all(
                isinstance(w, str) for w in warnings
            ):
                warnings = []
            if not isinstance(notes, list) or not all(
                isinstance(n, str) for n in notes
            ):
                notes = []

            candidates.append(
                TranslationCandidate(
                    segment_id=segment_id,
                    translation=translation,
                    warnings=tuple(warnings),
                    notes=tuple(notes),
                ),
            )

        found_ids = {candidate.segment_id for candidate in candidates}
        for missing_id in expected_ids - found_ids:
            issues.append(
                ParseIssue(
                    category=IssueCategory.MISSING_ID,
                    message=f"Missing segment_id '{missing_id}'.",
                ),
            )

        expected_id_list = [item.segment_id for item in expected_items]
        observed_id_list = [candidate.segment_id for candidate in candidates]
        if (
            len(observed_id_list) == len(expected_id_list)
            and set(observed_id_list) == set(expected_id_list)
            and observed_id_list != expected_id_list
        ):
            issues.append(
                ParseIssue(
                    category=IssueCategory.ORDER_MISMATCH,
                    message="Segment IDs are not in the expected order.",
                    repairable=False,
                ),
            )

        if issues:
            return ValidationReport(
                candidates=(),
                issues=tuple(issues),
                repair_descriptor=repair_descriptor,
                raw_response=raw_response,
            )

        return ValidationReport(
            candidates=tuple(candidates),
            issues=(),
            repair_descriptor=repair_descriptor,
            raw_response=raw_response,
        )

    def parse_or_raise(
        self,
        text: str,
        *,
        output_contract: OutputContract,
        repair_descriptor: RepairDescriptor | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> tuple[TranslationCandidate, ...]:
        """Return candidates if valid, otherwise raise ``OutputParseError``."""
        report = self.parse(
            text,
            output_contract=output_contract,
            repair_descriptor=repair_descriptor,
            raw_response=raw_response,
        )
        if report.is_valid:
            return report.candidates
        first = report.issues[0]
        raise OutputParseError(
            category=first.category,
            message=first.message,
            segment_id=first.segment_id,
        )
