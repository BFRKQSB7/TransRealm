"""P0-T06-M01: Output parser/validator DTOs and error taxonomy."""

from __future__ import annotations

import pytest

from transrealm.application.output_parser import (
    IssueCategory,
    OutputParseError,
    ParseIssue,
    RepairDescriptor,
    TranslationCandidate,
    ValidationReport,
)


class TestTranslationCandidate:
    """Parsed translation item."""

    def test_create_candidate(self) -> None:
        candidate = TranslationCandidate(
            segment_id="seg-1",
            translation="你好",
            warnings=("note",),
        )
        assert candidate.segment_id == "seg-1"
        assert candidate.translation == "你好"
        assert candidate.warnings == ("note",)
        assert candidate.notes == ()

    def test_rejects_empty_segment_id(self) -> None:
        with pytest.raises(ValueError, match="segment_id"):
            TranslationCandidate(segment_id="", translation="x")

    def test_rejects_none_translation(self) -> None:
        with pytest.raises(ValueError, match="translation"):
            TranslationCandidate(segment_id="seg-1", translation=None)  # type: ignore[arg-type]

    def test_empty_translation_is_allowed(self) -> None:
        candidate = TranslationCandidate(segment_id="seg-1", translation="")
        assert candidate.translation == ""


class TestParseIssue:
    """Classification of validation issues."""

    def test_issue_categories(self) -> None:
        categories = {
            IssueCategory.INVALID_JSON,
            IssueCategory.MISSING_FIELD,
            IssueCategory.TYPE_ERROR,
            IssueCategory.DUPLICATE_ID,
            IssueCategory.MISSING_ID,
            IssueCategory.UNKNOWN_ID,
            IssueCategory.ORDER_MISMATCH,
            IssueCategory.EMPTY_TRANSLATION,
            IssueCategory.NON_STRING_TRANSLATION,
            IssueCategory.CONTAMINATION,
            IssueCategory.REPAIR_LIMIT_EXCEEDED,
        }
        assert len(categories) == 11

    def test_issue_carries_repairable_flag(self) -> None:
        issue = ParseIssue(
            category=IssueCategory.INVALID_JSON,
            message="expected object",
            repairable=True,
        )
        assert issue.category == IssueCategory.INVALID_JSON
        assert issue.repairable is True


class TestRepairDescriptor:
    """Repair strategy and attempt budget."""

    def test_can_retry_when_attempts_remain(self) -> None:
        descriptor = RepairDescriptor(strategy="reparse", max_attempts=2, attempted=1)
        assert descriptor.can_retry is True

    def test_cannot_retry_when_limit_reached(self) -> None:
        descriptor = RepairDescriptor(strategy="reparse", max_attempts=1, attempted=1)
        assert descriptor.can_retry is False

    def test_rejects_negative_attempts(self) -> None:
        with pytest.raises(ValueError, match="attempted"):
            RepairDescriptor(strategy="reparse", max_attempts=2, attempted=-1)

    def test_rejects_attempts_exceeding_max(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            RepairDescriptor(strategy="reparse", max_attempts=1, attempted=2)


class TestOutputParseError:
    """Exception taxonomy for parser failures."""

    def test_error_includes_category(self) -> None:
        error = OutputParseError(
            category=IssueCategory.INVALID_JSON,
            message="not valid json",
            segment_id="seg-1",
        )
        assert error.category == IssueCategory.INVALID_JSON
        assert "seg-1" in str(error)
        assert "INVALID_JSON" in str(error)

    def test_error_without_segment_id(self) -> None:
        error = OutputParseError(
            category=IssueCategory.CONTAMINATION,
            message="extra text",
        )
        assert error.segment_id is None
        assert "CONTAMINATION" in str(error)


class TestValidationReport:
    """Aggregated validation result."""

    def test_valid_report(self) -> None:
        candidate = TranslationCandidate(segment_id="seg-1", translation="你好")
        report = ValidationReport(candidates=(candidate,), issues=())
        assert report.is_valid is True
        assert report.candidates == (candidate,)

    def test_invalid_report_with_issues(self) -> None:
        issue = ParseIssue(
            category=IssueCategory.MISSING_ID,
            message="missing segment_id",
            repairable=True,
        )
        report = ValidationReport(candidates=(), issues=(issue,))
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.MISSING_ID

    def test_rejects_duplicate_candidate_ids(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            ValidationReport(
                candidates=(
                    TranslationCandidate(segment_id="seg-1", translation="a"),
                    TranslationCandidate(segment_id="seg-1", translation="b"),
                ),
                issues=(),
            )
