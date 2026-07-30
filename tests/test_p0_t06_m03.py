"""P0-T06-M03: Batch items ID/quantity/order cross-validation."""

from __future__ import annotations

from transrealm.application.context import OutputContract, OutputItem
from transrealm.application.output_parser import (
    IssueCategory,
    OutputParser,
    TranslationCandidate,
)


def _contract(*segment_ids: str) -> OutputContract:
    return OutputContract(
        items=tuple(
            OutputItem(segment_id=sid, translation="") for sid in segment_ids
        ),
    )


class TestBatchCrossValidation:
    """Validate a batch of model output items against the output contract."""

    def test_valid_batch_in_expected_order(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2", "seg-3")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-2", "translation": "b"}, '
            '{"segment_id": "seg-3", "translation": "c"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is True
        assert len(report.candidates) == 3
        assert [candidate.segment_id for candidate in report.candidates] == [
            "seg-1",
            "seg-2",
            "seg-3",
        ]
        assert report.candidates[0] == TranslationCandidate(
            segment_id="seg-1",
            translation="a",
        )

    def test_wrong_order_rejected(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2", "seg-3")
        text = (
            '{"items": ['
            '{"segment_id": "seg-3", "translation": "c"}, '
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-2", "translation": "b"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.ORDER_MISMATCH
            for issue in report.issues
        )

    def test_extra_item_rejected(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-2", "translation": "b"}, '
            '{"segment_id": "seg-3", "translation": "c"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.ORDER_MISMATCH
            for issue in report.issues
        )

    def test_missing_item_rejected(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2", "seg-3")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-2", "translation": "b"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.MISSING_ID
            for issue in report.issues
        )

    def test_empty_batch_rejected(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1")
        report = parser.parse('{"items": []}', output_contract=contract)
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.ORDER_MISMATCH
            for issue in report.issues
        )

    def test_partial_reverse_order_rejected(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2", "seg-3", "seg-4")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-3", "translation": "c"}, '
            '{"segment_id": "seg-2", "translation": "b"}, '
            '{"segment_id": "seg-4", "translation": "d"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.ORDER_MISMATCH
            for issue in report.issues
        )

    def test_batch_with_duplicate_id_rejected(self) -> None:
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
        assert any(
            issue.category == IssueCategory.DUPLICATE_ID
            for issue in report.issues
        )

    def test_batch_with_unknown_id_rejected(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a"}, '
            '{"segment_id": "seg-3", "translation": "c"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        assert any(
            issue.category == IssueCategory.UNKNOWN_ID
            for issue in report.issues
        )

    def test_batch_preserves_warnings_and_notes(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2")
        text = (
            '{"items": ['
            '{"segment_id": "seg-1", "translation": "a", '
            '"warnings": ["w1"], "notes": ["n1"]}, '
            '{"segment_id": "seg-2", "translation": "b", '
            '"warnings": ["w2"], "notes": ["n2"]}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is True
        assert report.candidates[0].warnings == ("w1",)
        assert report.candidates[0].notes == ("n1",)
        assert report.candidates[1].warnings == ("w2",)
        assert report.candidates[1].notes == ("n2",)

    def test_batch_reports_multiple_issues(self) -> None:
        parser = OutputParser()
        contract = _contract("seg-1", "seg-2", "seg-3")
        text = (
            '{"items": ['
            '{"segment_id": "seg-2", "translation": "b"}, '
            '{"segment_id": "seg-2", "translation": "b"}'
            ']}'
        )
        report = parser.parse(text, output_contract=contract)
        assert report.is_valid is False
        categories = {issue.category for issue in report.issues}
        assert IssueCategory.DUPLICATE_ID in categories
        assert IssueCategory.MISSING_ID in categories
