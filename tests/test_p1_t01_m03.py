"""Tests for P1-T01-M03: the SRT vertical closed loop.

Covers the DEC-P1-T01-FOUNDATION plan-2 acceptance matrix for SRT: each cue's
text block becomes a stable Segment; no-op exports are byte-identical
(LF/CRLF/UTF-8 BOM/UTF-16 BOM/leading-trailing blank lines/settings/dot
timestamps/index-less cues); translated exports replace only the cue text
block while preserving the cue index, timing line, settings, blank separators
and line endings; malformed timestamps, duplicate cue timings, missing blank
separators and structural damage are rejected without polluting the database,
revisions, or an existing target file; and a real translation run round-trips
an SRT cue through the pipeline and back out byte-accurately.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.adapters.errors import AdapterServerError
from transrealm.application.exporter import ExportError, SrtExporter
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_service import TranslationService
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.segment import Segment
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.parsers.srt_parser import SRTParseError
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}


class FakeAdapter:
    """In-memory ModelAdapter that counts calls and returns a canned response."""

    def __init__(self, response: AdapterResponse | Exception) -> None:
        self.response = response
        self.calls = 0
        self.last_request: AdapterRequest | None = None

    def get_capabilities(self) -> ModelCapability:
        return ModelCapability(
            context_window=128000,
            max_output_tokens=4096,
            supports_streaming=False,
            supports_structured_output=False,
            supported_parameters={"temperature", "max_tokens"},
        )

    def filter_params(self, params: dict[str, object]) -> dict[str, object]:
        return params

    async def chat_completion(self, request: AdapterRequest) -> AdapterResponse:
        self.calls += 1
        self.last_request = request
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _valid_response(stable_key: str, translation: str) -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-1",
        raw_response=None,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _create_project(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="M03",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_srt(
    path: Path,
    project_id: int,
    raw: bytes,
    *,
    encoding: str = "utf-8",
    name: str = "source.srt",
) -> tuple[int, list[Segment]]:
    source = path.parent / name
    source.write_bytes(raw)
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_file(
            project_id,
            source,
            format="srt",
            name=name,
            encoding=encoding,
        )
    assert document.id is not None
    return document.id, segments


def _add_revision(path: Path, segment_id: int, text: str) -> int:
    repo = TranslationRevisionRepository.open(path)
    try:
        saved = repo.save(
            TranslationRevision.create(segment_id=segment_id, text=text, origin="ai"),
        )
    finally:
        repo.close()
    assert saved.id is not None
    return saved.id


def _set_current_revision(path: Path, segment_id: int, text: str) -> int:
    revision_id = _add_revision(path, segment_id, text)
    db = create_database(path)
    try:
        with transaction(db):
            db.execute(
                "UPDATE segments SET current_revision_id = ? WHERE id = ?",
                (revision_id, segment_id),
            )
    finally:
        db.close()
    return revision_id


def _export(
    path: Path,
    source_document_id: int,
    target_path: Path,
    **kwargs: Any,
) -> None:
    exporter = SrtExporter(path, app_version=APP_VERSION)
    try:
        exporter.export_document(
            source_document_id=source_document_id,
            target_path=target_path,
            **kwargs,
        )
    finally:
        exporter.close()


def _envelope(path: Path, document_id: int) -> dict[str, Any]:
    db = create_database(path)
    try:
        row = db.execute(
            "SELECT format_metadata FROM source_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    result = json.loads(row[0])
    assert isinstance(result, dict)
    return result


def _set_metadata(path: Path, document_id: int, envelope: dict[str, Any]) -> None:
    db = create_database(path)
    try:
        with transaction(db):
            db.execute(
                "UPDATE source_documents SET format_metadata = ? WHERE id = ?",
                (json.dumps(envelope, ensure_ascii=False), document_id),
            )
    finally:
        db.close()


def _tamper(path: Path, document_id: int, mutate: Callable[[dict[str, Any]], None]) -> None:
    envelope = _envelope(path, document_id)
    mutate(envelope)
    _set_metadata(path, document_id, envelope)


def _new_target(tmp_path: Path, name: str) -> Path:
    target = tmp_path / "out" / name
    target.parent.mkdir(exist_ok=True)
    return target


def _ids(segments: list[Segment]) -> list[int]:
    ids: list[int] = []
    for segment in segments:
        assert segment.id is not None
        ids.append(segment.id)
    return ids


class TestParseSegments:
    """Cue text blocks become Segments with stable cue-based identities."""

    def test_cue_text_lines_become_segments(self, tmp_path: Path) -> None:
        raw = (
            b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
            b"2\n00:00:05,000 --> 00:00:07,000\nSecond cue\nwith multi-line text\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_srt(path, project_id, raw)

        assert [s.source_text for s in segments] == [
            "Hello world",
            "Second cue\nwith multi-line text",
        ]
        assert [s.sequence for s in segments] == [1, 2]

    def test_indexless_cue_is_supported(self, tmp_path: Path) -> None:
        raw = b"00:00:01,000 --> 00:00:04,000\nHello world\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)

        assert [s.source_text for s in segments] == ["Hello world"]
        envelope = _envelope(path, document_id)
        entries = envelope["locator"]["segments"]
        assert entries[0]["index"] is None

    def test_cue_identity_is_stored_in_the_locator(self, tmp_path: Path) -> None:
        raw = (
            b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
            b"2\n00:00:05,000 --> 00:00:07,000\nSecond\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)

        envelope = _envelope(path, document_id)
        locator = envelope["locator"]
        assert locator["type"] == "srt.cues"
        entries = locator["segments"]
        assert [e["sequence"] for e in entries] == [1, 2]
        assert [e["index"] for e in entries] == ["1", "2"]
        assert [e["start"] for e in entries] == [
            "00:00:01,000",
            "00:00:05,000",
        ]
        assert [e["end"] for e in entries] == [
            "00:00:04,000",
            "00:00:07,000",
        ]

    def test_settings_preserved_in_the_locator(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000 X1:100 X2:400 Y1:50 Y2:75\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)

        envelope = _envelope(path, document_id)
        entries = envelope["locator"]["segments"]
        assert entries[0]["settings"] == "X1:100 X2:400 Y1:50 Y2:75"
        assert entries[0]["start"] == "00:00:01,000"
        assert entries[0]["end"] == "00:00:04,000"

    def test_dot_separator_timestamps_are_supported(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01.000 --> 00:00:04.000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)

        assert [s.source_text for s in segments] == ["Hello"]
        envelope = _envelope(path, document_id)
        entry = envelope["locator"]["segments"][0]
        assert entry["start"] == "00:00:01.000"
        assert entry["end"] == "00:00:04.000"

    def test_index_with_surrounding_spaces_is_preserved(self, tmp_path: Path) -> None:
        raw = b" 1 \n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)

        envelope = _envelope(path, document_id)
        assert envelope["locator"]["segments"][0]["index"] == "1"

    def test_text_line_that_looks_like_a_timing_line_is_text(self, tmp_path: Path) -> None:
        raw = (
            b"1\n00:00:01,000 --> 00:00:04,000\n"
            b"See 00:00:03,000 --> 00:00:04,000 in the video\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_srt(path, project_id, raw)

        assert [s.source_text for s in segments] == [
            "See 00:00:03,000 --> 00:00:04,000 in the video",
        ]

    def test_stable_keys_are_deterministic_and_unique(self, tmp_path: Path) -> None:
        raw = (
            b"1\n00:00:01,000 --> 00:00:02,000\nSame text\n\n"
            b"2\n00:00:03,000 --> 00:00:04,000\nSame text\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_srt(path, project_id, raw)

        assert len(segments) == 2
        assert segments[0].source_text == segments[1].source_text == "Same text"
        assert segments[0].stable_key != segments[1].stable_key
        _document_id2, segments2 = _import_srt(path, project_id, raw)
        assert [s.stable_key for s in segments2] == [s.stable_key for s in segments]

    def test_leading_and_trailing_blank_lines_are_structural(self, tmp_path: Path) -> None:
        raw = (
            b"\n\n1\n00:00:01,000 --> 00:00:02,000\nHello\n\n\n"
            b"2\n00:00:03,000 --> 00:00:04,000\nWorld\n\n\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)

        assert [s.source_text for s in segments] == ["Hello", "World"]
        target = _new_target(tmp_path, "noop.srt")
        _export(path, document_id, target, apply_revisions=False)
        assert target.read_bytes() == raw

    def test_empty_document_has_no_segments(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, b"\n\n\n")

        assert segments == []
        target = _new_target(tmp_path, "noop.srt")
        _export(path, document_id, target, apply_revisions=False)
        assert target.read_bytes() == b"\n\n\n"


class TestNoOpByteIdentity:
    """Import -> no-op export is byte-for-byte identical."""

    def test_noop_lf(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_crlf(self, tmp_path: Path) -> None:
        raw = b"1\r\n00:00:01,000 --> 00:00:04,000\r\nHello world\r\n\r\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_multiline_text_and_trailing_blanks(self, tmp_path: Path) -> None:
        raw = (
            b"1\n00:00:01,000 --> 00:00:04,000\n"
            b"First line\nsecond line\n\n"
            b"2\n00:00:05,000 --> 00:00:07,000\nLast\n\n\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf8_bom(self, tmp_path: Path) -> None:
        raw = b"\xef\xbb\xbf1\n00:00:01,000 --> 00:00:04,000\nHello world\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw, encoding="utf-8")
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf16_le_bom(self, tmp_path: Path) -> None:
        raw = "1\r\n00:00:01,000 --> 00:00:04,000\r\nHello\r\n\r\n".encode("utf-16")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw, encoding="utf-16")
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf16_be_bom(self, tmp_path: Path) -> None:
        raw = b"\xfe\xff" + "1\n00:00:01,000 --> 00:00:04,000\nHello\n".encode("utf-16-be")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw, encoding="utf-16")
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_non_ascii_utf8(self, tmp_path: Path) -> None:
        raw = "1\n00:00:01,000 --> 00:00:04,000\nこんにちは世界\n".encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_settings_and_dot_timestamps(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01.000 --> 00:00:04.000 X1:100 X2:400 Y1:50 Y2:75\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_text_block_at_eof_without_trailing_newline(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_cr_only_newlines(self, tmp_path: Path) -> None:
        raw = b"1\r00:00:01,000 --> 00:00:04,000\rHello\r\r"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_encoding_override_matching_succeeds_and_mismatch_refused(
        self,
        tmp_path: Path,
    ) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw, encoding="utf-8")
        target = _new_target(tmp_path, "noop.srt")

        _export(path, document_id, target, apply_revisions=False, encoding="utf-8")
        assert target.read_bytes() == raw

        mismatched = _new_target(tmp_path, "refused.srt")
        with pytest.raises(ExportError, match="cannot encode fidelity output"):
            _export(path, document_id, mismatched, apply_revisions=False, encoding="utf-16")
        assert not mismatched.exists()


class TestTranslatedReplacesOnlyCueText:
    """Revisions change only the cue text blocks."""

    def test_single_cue_replacement_preserves_index_timing_blank(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        _set_current_revision(path, segments[0].id or 0, "你好世界")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        assert target.read_bytes() == ("1\n00:00:01,000 --> 00:00:04,000\n你好世界\n\n").encode()

    def test_multi_cue_replacement_preserves_all_structure(self, tmp_path: Path) -> None:
        raw = (
            b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
            b"2\n00:00:05,000 --> 00:00:07,000\nSecond cue\nwith multi-line text\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        ids = _ids(segments)
        _set_current_revision(path, ids[0], "你好世界")
        _set_current_revision(path, ids[1], "第二个提示\n多行译文")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        expected = (
            "1\n00:00:01,000 --> 00:00:04,000\n你好世界\n\n"
            "2\n00:00:05,000 --> 00:00:07,000\n第二个提示\n多行译文\n"
        ).encode()
        assert target.read_bytes() == expected

    def test_indexless_cue_text_replaced(self, tmp_path: Path) -> None:
        raw = b"00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        _set_current_revision(path, segments[0].id or 0, "你好")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        assert target.read_bytes() == ("00:00:01,000 --> 00:00:04,000\n你好\n").encode()

    def test_multiline_source_replaced_as_block(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nLine one\nline two\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        assert segments[0].source_text == "Line one\nline two"
        _set_current_revision(path, segments[0].id or 0, "单行译文")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        assert target.read_bytes() == ("1\n00:00:01,000 --> 00:00:04,000\n单行译文\n").encode()

    def test_translation_with_newline_is_multiline_in_output(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        _set_current_revision(path, segments[0].id or 0, "第一行\n第二行")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        expected = "1\n00:00:01,000 --> 00:00:04,000\n第一行\n第二行\n".encode()
        assert target.read_bytes() == expected

    def test_settings_and_dot_timestamps_survive_translation(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01.000 --> 00:00:04.000 X1:100 X2:400 Y1:50 Y2:75\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        _set_current_revision(path, segments[0].id or 0, "你好")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        assert (
            target.read_bytes()
            == ("1\n00:00:01.000 --> 00:00:04.000 X1:100 X2:400 Y1:50 Y2:75\n你好\n").encode()
        )

    def test_crlf_multiline_text_round_trip(self, tmp_path: Path) -> None:
        raw = b"1\r\n00:00:01,000 --> 00:00:04,000\r\nA\r\nB\r\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        assert segments[0].source_text == "A\r\nB"
        _set_current_revision(path, segments[0].id or 0, "甲\n乙")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        assert target.read_bytes() == ("1\r\n00:00:01,000 --> 00:00:04,000\r\n甲\n乙\r\n").encode()

    def test_utf16_translated_replaces_text_only(self, tmp_path: Path) -> None:
        raw = "1\r\n00:00:01,000 --> 00:00:04,000\r\nHello\r\n".encode("utf-16")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw, encoding="utf-16")
        _set_current_revision(path, segments[0].id or 0, "你好")
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        text = target.read_bytes().decode("utf-16")
        assert text == "1\r\n00:00:01,000 --> 00:00:04,000\r\n你好\r\n"

    def test_reparse_of_export_round_trips_structure_and_values(self, tmp_path: Path) -> None:
        raw = (
            b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
            b"2\n00:00:05,000 --> 00:00:07,000\nSecond cue\nwith multi-line text\n"
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        ids = _ids(segments)
        translations = {ids[0]: "你好世界", ids[1]: "第二个提示\n多行译文"}
        for segment_id, text in translations.items():
            _set_current_revision(path, segment_id, text)
        target = _new_target(tmp_path, "translated.srt")

        _export(path, document_id, target)

        _document2, segments2 = _import_srt(
            path,
            project_id,
            target.read_bytes(),
            name="reimport.srt",
        )
        assert [s.source_text for s in segments2] == ["你好世界", "第二个提示\n多行译文"]

    def test_revision_override_for_srt(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:02,000\nOne\n\n2\n00:00:03,000 --> 00:00:04,000\nTwo\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        ids = _ids(segments)
        _set_current_revision(path, ids[0], "一")
        _set_current_revision(path, ids[1], "二")
        historical = _add_revision(path, ids[0], "X")
        target = _new_target(tmp_path, "override.srt")

        _export(path, document_id, target, revision_overrides={ids[0]: historical})

        assert (
            target.read_bytes()
            == (
                "1\n00:00:01,000 --> 00:00:02,000\nX\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\n二\n"
            ).encode()
        )


class TestMalformedImportRejected:
    """Malformed SRT is rejected at import without polluting the database."""

    @pytest.mark.parametrize(
        "content",
        [
            b"1\n00:00:01,000 00:00:04,000\nHello\n",  # missing arrow
            b"1\n00:00:01,000 -- 00:00:04,000\nHello\n",  # broken arrow
            b"1\n00:00:01 000 --> 00:00:04,000\nHello\n",  # missing comma
            b"1\n00:00:01,00 --> 00:00:04,000\nHello\n",  # milliseconds too short
            b"1\n00:00:01,0000 --> 00:00:04,000\nHello\n",  # milliseconds too long
            b"1\n00:60:01,000 --> 00:00:04,000\nHello\n",  # minutes 60
            b"1\n00:00:60,000 --> 00:00:04,000\nHello\n",  # seconds 60
            b"1\n00:00:01,000 --> 00:99:04,000\nHello\n",  # minutes 99 on end
            b"1\n00:00:01,000 --> 00:00:100,000\nHello\n",  # seconds 100 on end
            b"1\n00:00:01,000 --> 00:00:04,000\n\n",  # cue with no text
            b"1\n00:00:01,000 --> 00:00:04,000\n\n"
            b"2\n00:00:05,000 --> 00:00:06,000\nHi\n",  # empty cue 1
            b"1\nHello\n",  # index not followed by a timing line
            b"X\n00:00:01,000 --> 00:00:04,000\nHello\n",  # non-numeric first line
            b"1\n00:00:01,000 --> 00:00:02,000\nA\n"
            b"2\n00:00:03,000 --> 00:00:04,000\nB\n",  # no blank separator
            b"1\n",  # index at EOF
        ],
    )
    def test_malformed_import_rejected_no_pollution(
        self,
        tmp_path: Path,
        content: bytes,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        source = tmp_path / "bad.srt"
        source.write_bytes(content)

        with pytest.raises(SRTParseError):
            with ImportService(path, app_version=APP_VERSION) as service:
                service.import_file(project_id, source, format="srt", name="bad.srt")

        db = create_database(path)
        try:
            documents = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
            segments = db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        finally:
            db.close()
        assert documents == 0
        assert segments == 0

    @pytest.mark.parametrize(
        "content",
        [
            b"1\n00:00:01,000 --> 00:00:04,000\nHello\n\n"
            b"2\n00:00:01,000 --> 00:00:04,000\nWorld\n",  # exact duplicate timing
            b"1\n00:00:01,000 --> 00:00:04,000\nHello\n\n"
            b"2\n00:00:01.000 --> 00:00:04.000\nWorld\n",  # same timing, dot separator
            b"1\n00:00:01,000 --> 00:00:04,000\nHello\n\n"
            b"2\n00:00:01,000 --> 00:00:04,000 X1:100\nWorld\n",  # same timing, extra settings
        ],
    )
    def test_duplicate_cue_timings_rejected_no_pollution(
        self,
        tmp_path: Path,
        content: bytes,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        source = tmp_path / "dup.srt"
        source.write_bytes(content)

        with pytest.raises(SRTParseError, match="[Dd]uplicate"):
            with ImportService(path, app_version=APP_VERSION) as service:
                service.import_file(project_id, source, format="srt", name="dup.srt")

        db = create_database(path)
        try:
            documents = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
            segments = db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        finally:
            db.close()
        assert documents == 0
        assert segments == 0


class TestVerificationFailuresRejected:
    """Any carrier validation failure is refused without writing a file."""

    def _assert_rejected(self, path: Path, document_id: int, match: str) -> None:
        target = _new_target(path.parent, "rejected.srt")
        with pytest.raises(ExportError, match=match):
            _export(path, document_id, target)
        assert not target.exists()

    def test_cue_index_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"][0].update(index="9"))

        self._assert_rejected(path, document_id, "cue index")

    def test_timing_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(start="00:00:02,000"),
        )

        self._assert_rejected(path, document_id, "timing")

    def test_settings_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000 X1:100\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(settings="X9:9"),
        )

        self._assert_rejected(path, document_id, "settings")

    def test_span_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"][0].update(byte_start=0))

        self._assert_rejected(path, document_id, "text block span")

    def test_sequence_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:02,000\nOne\n\n2\n00:00:03,000 --> 00:00:04,000\nTwo\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"][0].update(sequence=99))

        self._assert_rejected(path, document_id, "sequence")

    def test_source_text_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE segments SET source_text = 'tampered' WHERE source_document_id = ?",
                    (document_id,),
                )
        finally:
            db.close()

        self._assert_rejected(path, document_id, "does not match its source text")

    def test_source_hash_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(source_hash="0" * 64))

        self._assert_rejected(path, document_id, "source hash")

    def test_bom_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(bom="utf-16-le"))

        self._assert_rejected(path, document_id, "BOM")

    def test_newline_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(newline="crlf"))

        self._assert_rejected(path, document_id, "newline")

    def test_metadata_version_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(schema_version=99))

        self._assert_rejected(path, document_id, "schema version")

    def test_parser_version_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(parser_version="2.0.0"))

        self._assert_rejected(path, document_id, "parser version")

    def test_wrong_format_envelope_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(format="txt"))

        self._assert_rejected(path, document_id, "does not match")

    def test_malformed_envelope_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET format_metadata = ? WHERE id = ?",
                    ("{not json", document_id),
                )
        finally:
            db.close()

        self._assert_rejected(path, document_id, "not valid JSON")

    def test_stored_raw_bytes_hash_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET raw_bytes = ? WHERE id = ?",
                    (b"1\n00:00:01,000 --> 00:00:04,000\nTampered\n", document_id),
                )
        finally:
            db.close()

        self._assert_rejected(path, document_id, "raw bytes hash")

    def test_missing_locator_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.pop("locator"))

        self._assert_rejected(path, document_id, "no SRT segment locator")

    def test_segment_count_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:02,000\nOne\n\n2\n00:00:03,000 --> 00:00:04,000\nTwo\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"].pop())

        self._assert_rejected(path, document_id, "segment count")

    def test_cross_segment_revision_override_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:02,000\nOne\n\n2\n00:00:03,000 --> 00:00:04,000\nTwo\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        ids = _ids(segments)
        _set_current_revision(path, ids[0], "一")
        _set_current_revision(path, ids[1], "二")
        rev_of_b = _add_revision(path, ids[1], "乙")
        target = _new_target(tmp_path, "rejected.srt")

        with pytest.raises(ExportError, match="belongs to segment"):
            _export(path, document_id, target, revision_overrides={ids[0]: rev_of_b})
        assert not target.exists()

    def test_raw_bytes_that_no_longer_parse_as_srt_rejected(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        # Rewrite raw_bytes AND its hash (and the envelope's stored hash)
        # consistently so the carrier hash checks pass, but the exporter's
        # re-parse of the raw bytes finds a malformed timing line.
        import hashlib

        tampered = b"1\n00:00:01,000 00:00:04,000\nHello\n"
        tampered_hash = hashlib.sha256(tampered).hexdigest()
        envelope = _envelope(path, document_id)
        envelope["source_hash"] = tampered_hash
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET raw_bytes = ?, source_hash = ?, "
                    "format_metadata = ? WHERE id = ?",
                    (
                        tampered,
                        tampered_hash,
                        json.dumps(envelope, ensure_ascii=False),
                        document_id,
                    ),
                )
        finally:
            db.close()

        self._assert_rejected(path, document_id, "not valid SRT")


class TestFailuresDoNotPollute:
    """Encoding/write/verification failures preserve the target and the data."""

    def test_encoding_failure_preserves_target_and_data(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw, encoding="ascii")
        _set_current_revision(path, segments[0].id or 0, "你好")
        target = _new_target(tmp_path, "translated.srt")
        target.write_bytes(b"OLD CONTENT")

        with pytest.raises(ExportError, match="encode"):
            _export(path, document_id, target)

        assert target.read_bytes() == b"OLD CONTENT"
        assert list(target.parent.iterdir()) == [target]

        db = create_database(path)
        try:
            revisions = db.execute("SELECT COUNT(*) FROM translation_revisions").fetchone()[0]
            documents = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
        finally:
            db.close()
        assert revisions == 1
        assert documents == 1

    def test_unwritable_target_preserves_state(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        _set_current_revision(path, segments[0].id or 0, "你好")
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("occupied", encoding="utf-8")
        target = blocker / "translated.srt"

        with pytest.raises(ExportError, match="temp file"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_verification_failure_never_writes_partial_file(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_srt(path, project_id, raw)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(start="00:00:02,000"),
        )
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        target = out_dir / "translated.srt"

        with pytest.raises(ExportError):
            _export(path, document_id, target)

        assert list(out_dir.iterdir()) == []

    def test_missing_carrier_rejected(self, tmp_path: Path) -> None:
        """A document without raw bytes cannot be exported with fidelity."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        source = tmp_path / "source.srt"
        source.write_bytes(b"1\n00:00:01,000 --> 00:00:04,000\nHello\n")
        with ImportService(path, app_version=APP_VERSION) as service:
            document, _ = service.import_file(
                project_id,
                source,
                format="srt",
                name="source.srt",
            )
        assert document.id is not None
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET raw_bytes = NULL, format_metadata = NULL "
                    "WHERE id = ?",
                    (document.id,),
                )
        finally:
            db.close()

        target = _new_target(tmp_path, "missing.srt")
        with pytest.raises(ExportError, match="no preserved original bytes"):
            _export(path, document.id, target, apply_revisions=False)
        assert not target.exists()


class TestVerticalTranslationLoop:
    """A real translation run round-trips an SRT cue through export."""

    def _create_profile(self, path: Path) -> ModelProfile:
        with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
            connection = conn_service.create_connection(
                name="local",
                provider_type="openai-compatible",
                endpoint="http://localhost:8080/v1",
                timeout_seconds=30,
                max_retries=0,
                retry_delay_seconds=0.0,
                credential_reference="env:OPENAI_API_KEY",
            )
            assert connection.id is not None
            with ModelProfileService(path, app_version=APP_VERSION) as profile_service:
                profile = profile_service.create_profile(
                    name="general",
                    provider_connection_id=connection.id,
                    model_id="gpt-4o-mini",
                    template_version="1.0.0",
                    output_protocol="json",
                    context_budget=DEFAULT_BUDGET,
                    default_params={"temperature": 0.3},
                    capability=ModelCapability(
                        context_window=128000,
                        max_output_tokens=4096,
                        supports_streaming=False,
                        supports_structured_output=False,
                        supported_parameters={"temperature", "max_tokens"},
                    ),
                )
        assert profile.id is not None
        return profile

    def test_import_translate_export_round_trip(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello world.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_srt(path, project_id, raw)
        assert len(segments) == 1
        profile = self._create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key, "こんにちは世界"))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            revision = _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=segments[0].id or 0,
                    profile_id=profile.id,
                ),
            )
        assert revision.text == "こんにちは世界"
        assert fake.calls == 1

        target = _new_target(tmp_path, "roundtrip.srt")
        _export(path, document_id, target)

        expected = "1\n00:00:01,000 --> 00:00:04,000\nこんにちは世界\n".encode()
        assert target.read_bytes() == expected

    def test_adapter_failure_finalizes_failed_attempt(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello world.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_srt(path, project_id, raw)
        profile = self._create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(AdapterServerError("provider exploded", provider_code=500))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(Exception):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=segments[0].id or 0,
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 1
        assert segments[0].id is not None
        repo = TranslationRevisionRepository.open(path)
        try:
            revisions = repo.list_by_segment(segments[0].id)
        finally:
            repo.close()
        assert revisions == []


class TestIdentityDomain:
    """SRT re-imports stay idempotent under the 008 logical identity."""

    def test_reimport_same_srt_is_idempotent(self, tmp_path: Path) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document1, segments1 = _import_srt(path, project_id, raw)
        document2, segments2 = _import_srt(path, project_id, raw)

        assert document1 == document2
        assert [s.id for s in segments1] == [s.id for s in segments2]
        db = create_database(path)
        try:
            count = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
        finally:
            db.close()
        assert count == 1

    def test_same_bytes_as_srt_and_txt_are_separate_documents(self, tmp_path: Path) -> None:
        raw = b"00:00:01,000 --> 00:00:04,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        srt_doc, srt_segments = _import_srt(path, project_id, raw, name="source.srt")
        txt_source = path.parent / "source.txt"
        txt_source.write_bytes(raw)
        with ImportService(path, app_version=APP_VERSION) as service:
            txt_doc, _ = service.import_file(
                project_id,
                txt_source,
                format="txt",
                name="source.txt",
            )
        assert srt_doc != txt_doc
        assert [s.source_text for s in srt_segments] == ["Hello"]

