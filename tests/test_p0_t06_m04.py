"""P0-T06-M04: Repair classification and malicious/abnormal output matrix."""

from __future__ import annotations

import pytest

from transrealm.application.context import OutputContract, OutputItem
from transrealm.application.output_parser import (
    IssueCategory,
    OutputParseError,
    OutputParser,
    RepairDescriptor,
    TranslationCandidate,
)


def _contract(*segment_ids: str) -> OutputContract:
    return OutputContract(
        items=tuple(
            OutputItem(segment_id=sid, translation="") for sid in segment_ids
        ),
    )


class TestRepairClassification:
    """Verify which issue categories are classified as repairable."""

    def test_invalid_json_is_repairable_when_fence_possible(self) -> None:
        parser = OutputParser()
        descriptor = RepairDescriptor(strategy="fence", max_attempts=1, attempted=0)
        report = parser.parse(
            "not json",
            output_contract=_contract("seg-1"),
            repair_descriptor=descriptor,
        )
        assert report.is_valid is False
        issue = report.issues[0]
        assert issue.category == IssueCategory.INVALID_JSON
        assert issue.repairable is True

    def test_invalid_json_is_not_repairable_without_descriptor(self) -> None:
        parser = OutputParser()
        report = parser.parse("not json", output_contract=_contract("seg-1"))
        assert report.is_valid is False
        issue = report.issues[0]
        assert issue.category == IssueCategory.INVALID_JSON
        assert issue.repairable is False

    def test_extracted_fenced_json_is_not_repairable(self) -> None:
        parser = OutputParser()
        descriptor = RepairDescriptor(strategy="fence", max_attempts=1, attempted=0)
        report = parser.parse(
            '```json\nnot json\n```',
            output_contract=_contract("seg-1"),
            repair_descriptor=descriptor,
        )
        assert report.is_valid is False
        issue = report.issues[0]
        assert issue.category == IssueCategory.INVALID_JSON
        assert issue.repairable is False

    def test_empty_translation_is_repairable(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '{"items": [{"segment_id": "seg-1", "translation": ""}]}',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is False
        issue = report.issues[0]
        assert issue.category == IssueCategory.EMPTY_TRANSLATION
        assert issue.repairable is True

    def test_duplicate_id_is_not_repairable(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-1", "translation": "b"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        issue = report.issues[0]
        assert issue.category == IssueCategory.DUPLICATE_ID
        assert issue.repairable is False

    def test_repair_limit_exceeded_is_not_repairable(self) -> None:
        parser = OutputParser()
        descriptor = RepairDescriptor(strategy="fence", max_attempts=1, attempted=1)
        report = parser.parse(
            "not json",
            output_contract=_contract("seg-1"),
            repair_descriptor=descriptor,
        )
        assert report.is_valid is False
        issue = report.issues[0]
        assert issue.category == IssueCategory.REPAIR_LIMIT_EXCEEDED
        assert issue.repairable is False


class TestAbnormalOutputMatrix:
    """Reject malformed or adversarial model outputs without forging candidates."""

    def test_non_dict_item_in_items_array(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '{"items": ["not an object"]}',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.TYPE_ERROR for issue in report.issues
        )

    def test_missing_segment_id_field(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '{"items": [{"translation": "hello"}]}',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.TYPE_ERROR for issue in report.issues
        )

    def test_extra_fields_in_item_are_ignored(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '{"items": [{"segment_id": "seg-1", "translation": "a", "extra": 1}]}',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is True
        assert report.candidates[0] == TranslationCandidate(
            segment_id="seg-1",
            translation="a",
        )

    def test_translation_with_json_fence_is_contaminated(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '{"items": [{"segment_id": "seg-1", "translation": "```json\\n{\\\"x\\": 1}\\n```"}]}',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.CONTAMINATION for issue in report.issues
        )
        contaminated = next(
            issue for issue in report.issues
            if issue.category == IssueCategory.CONTAMINATION
        )
        assert contaminated.repairable is True
        assert contaminated.segment_id == "seg-1"

    def test_translation_with_inline_fence_is_contaminated(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '{"items": [{"segment_id": "seg-1", "translation": "use `code` here"}]}',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is True

    def test_top_level_array_instead_of_object(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '[{"segment_id": "seg-1", "translation": "a"}]',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.TYPE_ERROR

    def test_items_field_is_string(self) -> None:
        parser = OutputParser()
        report = parser.parse(
            '{"items": "not an array"}',
            output_contract=_contract("seg-1"),
        )
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.MISSING_FIELD

    def test_repair_consumes_attempt_and_succeeds(self) -> None:
        parser = OutputParser()
        descriptor = RepairDescriptor(strategy="fence", max_attempts=2, attempted=0)
        text = (
            'explain\n```json\n{"items": [{"segment_id": "seg-1", '
            '"translation": "a"}]}\n```\nmore'
        )
        report = parser.parse(
            text,
            output_contract=_contract("seg-1"),
            repair_descriptor=descriptor,
        )
        assert report.is_valid is True
        assert report.repair_descriptor is not None
        assert report.repair_descriptor.attempted == 1

    def test_repair_limit_exhausted_with_abnormal_output(self) -> None:
        parser = OutputParser()
        descriptor = RepairDescriptor(strategy="fence", max_attempts=1, attempted=1)
        report = parser.parse(
            "still not json",
            output_contract=_contract("seg-1"),
            repair_descriptor=descriptor,
        )
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.REPAIR_LIMIT_EXCEEDED

    def test_parse_or_raise_surfaces_first_issue_category(self) -> None:
        parser = OutputParser()
        with pytest.raises(OutputParseError, match="segment_id") as exc_info:
            parser.parse_or_raise(
                '{"items": [{"segment_id": "seg-2", "translation": "a"}]}',
                output_contract=_contract("seg-1"),
            )
        assert exc_info.value.category == IssueCategory.UNKNOWN_ID

    def test_empty_items_array_is_rejected(self) -> None:
        parser = OutputParser()
        report = parser.parse('{"items": []}', output_contract=_contract("seg-1"))
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.ORDER_MISMATCH for issue in report.issues
        )

    def test_multiple_abnormal_issues_reported(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": ""}, '
            '{"segment_id": "seg-2", "translation": 123}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        categories = {issue.category for issue in report.issues}
        assert IssueCategory.EMPTY_TRANSLATION in categories
        assert IssueCategory.NON_STRING_TRANSLATION in categories
