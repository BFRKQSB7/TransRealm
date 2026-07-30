"""P0-T06-M02: Single-segment output parser and validator."""

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


def _contract(segment_id: str = "seg-1") -> OutputContract:
    return OutputContract(items=(OutputItem(segment_id=segment_id, translation=""),))


class TestSingleSegmentParser:
    """Parse and validate a single model output item."""

    def test_valid_single_item(self) -> None:
        parser = OutputParser()
        text = '{"items": [{"segment_id": "seg-1", "translation": "你好"}]}'
        report = parser.parse(text, output_contract=_contract())
        assert report.is_valid is True
        assert len(report.candidates) == 1
        assert report.candidates[0] == TranslationCandidate(
            segment_id="seg-1",
            translation="你好",
        )

    def test_valid_item_with_warnings_and_notes(self) -> None:
        parser = OutputParser()
        text = (
            '{"items": [{"segment_id": "seg-1", "translation": "你好", '
            '"warnings": ["a"], "notes": ["b"]}]}'
        )
        report = parser.parse(text, output_contract=_contract())
        assert report.is_valid is True
        candidate = report.candidates[0]
        assert candidate.translation == "你好"
        assert candidate.warnings == ("a",)
        assert candidate.notes == ("b",)

    def test_fenced_json_is_repaired(self) -> None:
        parser = OutputParser()
        text = (
            'Some extra text\n```json\n'
            '{"items": [{"segment_id": "seg-1", "translation": "你好"}]}\n'
            '```\nmore text'
        )
        report = parser.parse(text, output_contract=_contract())
        assert report.is_valid is True
        assert report.candidates[0].segment_id == "seg-1"

    def test_invalid_json(self) -> None:
        parser = OutputParser()
        report = parser.parse("not json", output_contract=_contract())
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.INVALID_JSON

    def test_missing_items_field(self) -> None:
        parser = OutputParser()
        report = parser.parse('{"foo": "bar"}', output_contract=_contract())
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.MISSING_FIELD

    def test_top_level_not_object(self) -> None:
        parser = OutputParser()
        report = parser.parse('[1, 2, 3]', output_contract=_contract())
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.TYPE_ERROR

    def test_wrong_segment_id(self) -> None:
        parser = OutputParser()
        text = '{"items": [{"segment_id": "seg-2", "translation": "你好"}]}'
        report = parser.parse(text, output_contract=_contract())
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.UNKNOWN_ID

    def test_missing_segment_id(self) -> None:
        parser = OutputParser()
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "你好"}, '
            '{"segment_id": "seg-2", "translation": "world"}'
            ']}'
        )
        report = parser.parse(text, output_contract=_contract())
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.ORDER_MISMATCH for issue in report.issues
        )

    def test_empty_translation(self) -> None:
        parser = OutputParser()
        text = '{"items": [{"segment_id": "seg-1", "translation": ""}]}'
        report = parser.parse(text, output_contract=_contract())
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.EMPTY_TRANSLATION

    def test_non_string_translation(self) -> None:
        parser = OutputParser()
        text = '{"items": [{"segment_id": "seg-1", "translation": 123}]}'
        report = parser.parse(text, output_contract=_contract())
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.NON_STRING_TRANSLATION

    def test_duplicate_segment_id(self) -> None:
        parser = OutputParser()
        contract = OutputContract(
            items=(
                OutputItem(segment_id="seg-1", translation=""),
                OutputItem(segment_id="seg-2", translation=""),
            ),
        )
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-1", "translation": "b"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.DUPLICATE_ID

    def test_repair_limit_exceeded(self) -> None:
        parser = OutputParser()
        descriptor = RepairDescriptor(strategy="fence", max_attempts=1, attempted=1)
        report = parser.parse(
            "not json",
            output_contract=_contract(),
            repair_descriptor=descriptor,
        )
        assert report.is_valid is False
        assert report.issues[0].category == IssueCategory.REPAIR_LIMIT_EXCEEDED

    def test_repair_descriptor_updated(self) -> None:
        parser = OutputParser()
        descriptor = RepairDescriptor(strategy="fence", max_attempts=2, attempted=0)
        text = '```json\n{"items": [{"segment_id": "seg-1", "translation": "你好"}]}\n```'
        report = parser.parse(
            text,
            output_contract=_contract(),
            repair_descriptor=descriptor,
        )
        assert report.is_valid is True
        assert report.repair_descriptor is not None
        assert report.repair_descriptor.attempted == 1

    def test_parse_or_raise_returns_candidates(self) -> None:
        parser = OutputParser()
        text = '{"items": [{"segment_id": "seg-1", "translation": "你好"}]}'
        candidates = parser.parse_or_raise(text, output_contract=_contract())
        assert len(candidates) == 1
        assert candidates[0].translation == "你好"

    def test_parse_or_raise_raises(self) -> None:
        parser = OutputParser()
        with pytest.raises(OutputParseError, match="segment_id"):
            parser.parse_or_raise(
                '{"items": [{"segment_id": "seg-2", "translation": "你好"}]}',
                output_contract=_contract(),
            )
