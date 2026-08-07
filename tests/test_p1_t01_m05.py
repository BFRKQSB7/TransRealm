"""Tests for P1-T01-M05: the ASS/SSA vertical closed loop.

Covers the DEC-P1-T01-FOUNDATION plan-2 acceptance matrix for ASS (ScriptType
``v4.00+``) and SSA (``v4.00``): each ``Dialogue:`` event's Text field becomes
a stable Segment while every section, the ``[Events] Format:`` line,
``Comment:`` events, all non-Text fields, inline override tags, escapes and
line endings stay structural; no-op exports are byte-identical (LF/CRLF/CR/
UTF-8 BOM/UTF-16 LE and BE BOM/sections/styles/comments/tags/escapes/comma
text); a translated export replaces only the Dialogue Text field while
preserving every non-target byte; an ASS file is refused by the SSA parser and
vice versa (no silent downgrade); malformed documents (missing signature,
missing ScriptType, missing or non-standard Events Format, wrong field count,
empty Text, invalid timing) are rejected without polluting the database,
revisions, or an existing target file; and a real translation run round-trips
an ASS/SSA Dialogue through the pipeline and back out byte-accurately.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.adapters.errors import AdapterServerError
from transrealm.application.exporter import AssExporter, ExportError, SsaExporter
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_service import TranslationService
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.segment import Segment
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.parsers.ass_ssa_parser import AssSsaParseError
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}

_ASS_EVENTS_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text"
)
_SSA_EVENTS_FORMAT = (
    "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text"
)

_ASS_HEADER = (
    "[Script Info]\n"
    "; a comment\n"
    "Title: Demo\n"
    "ScriptType: v4.00+\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
    "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1\n"
    "\n"
    "[Events]\n"
    f"{_ASS_EVENTS_FORMAT}\n"
)
_SSA_HEADER = (
    "[Script Info]\n"
    "Title: Demo\n"
    "ScriptType: v4.00\n"
    "\n"
    "[V4 Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\n"
    "Style: Default,Arial,20,16777215,16777215,16777215,0,0,0,1,2,2,2,"
    "10,10,10,0,1\n"
    "\n"
    "[Events]\n"
    f"{_SSA_EVENTS_FORMAT}\n"
)


def _events_format_line(fmt: str) -> str:
    return _ASS_EVENTS_FORMAT if fmt == "ass" else _SSA_EVENTS_FORMAT


def _script_type(fmt: str) -> str:
    return "v4.00+" if fmt == "ass" else "v4.00"


def _header(fmt: str) -> str:
    return _ASS_HEADER if fmt == "ass" else _SSA_HEADER


def _min_header(fmt: str) -> str:
    return (
        "[Script Info]\n"
        f"ScriptType: {_script_type(fmt)}\n"
        "\n"
        "[Events]\n"
        f"{_events_format_line(fmt)}\n"
    )


def _doc(
    fmt: str,
    *events: str,
    newline: str = "\n",
    header: str | None = None,
) -> str:
    """Build an ASS/SSA document (as text) with the given event lines."""
    head = (header if header is not None else _header(fmt)).rstrip("\n")
    text = head + "\n" + "\n".join(events)
    if not text.endswith("\n"):
        text += "\n"
    return text.replace("\n", newline)


def _dialogue(
    fmt: str,
    text: str,
    *,
    start: str = "0:00:01.00",
    end: str = "0:00:02.00",
) -> str:
    if fmt == "ass":
        return f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
    return f"Dialogue: Marked=0,{start},{end},Default,,0000,0000,0000,,{text}"


def _comment(
    fmt: str,
    text: str,
    *,
    start: str = "0:00:05.00",
    end: str = "0:00:06.00",
) -> str:
    if fmt == "ass":
        return f"Comment: 0,{start},{end},Default,,0,0,0,,{text}"
    return f"Comment: Marked=0,{start},{end},Default,,0000,0000,0000,,{text}"


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
            name="M05",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import(
    path: Path,
    project_id: int,
    raw: bytes,
    fmt: str,
    *,
    encoding: str = "utf-8",
    name: str | None = None,
) -> tuple[int, list[Segment]]:
    source = path.parent / (name or f"source.{fmt}")
    source.write_bytes(raw)
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_file(
            project_id,
            source,
            format=fmt,
            name=name,
            encoding=encoding,
        )
    assert document.id is not None
    return document.id, segments


def _ids(segments: list[Segment]) -> list[int]:
    ids: list[int] = []
    for segment in segments:
        assert segment.id is not None
        ids.append(segment.id)
    return ids


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


def _set_revisions(path: Path, segments: list[Segment], texts: list[str]) -> None:
    revision_ids: list[tuple[int, int]] = []
    repo = TranslationRevisionRepository.open(path)
    try:
        for segment, text in zip(segments, texts):
            assert segment.id is not None
            saved = repo.save(
                TranslationRevision.create(
                    segment_id=segment.id,
                    text=text,
                    origin="ai",
                ),
            )
            assert saved.id is not None
            revision_ids.append((saved.id, segment.id))
    finally:
        repo.close()
    db = create_database(path)
    try:
        with transaction(db):
            for revision_id, segment_id in revision_ids:
                db.execute(
                    "UPDATE segments SET current_revision_id = ? WHERE id = ?",
                    (revision_id, segment_id),
                )
    finally:
        db.close()


def _export(
    path: Path,
    document_id: int,
    target_path: Path,
    fmt: str,
    **kwargs: Any,
) -> None:
    exporter: AssExporter | SsaExporter = (
        AssExporter(path, app_version=APP_VERSION)
        if fmt == "ass"
        else SsaExporter(path, app_version=APP_VERSION)
    )
    try:
        exporter.export_document(
            source_document_id=document_id,
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


class TestParseSegments:
    """Dialogue events become segments; everything else stays structural."""

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_dialogue_text_becomes_segment(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert [segment.source_text for segment in segments] == ["Hello world"]
        assert [segment.sequence for segment in segments] == [1]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_comment_events_are_not_segments(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _comment(fmt, "do not translate"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert [segment.source_text for segment in segments] == ["One"]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_text_with_commas_is_one_field(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello, world, again!")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert segments[0].source_text == "Hello, world, again!"

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_inline_tags_and_escapes_preserved(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, r"{\i1}bold\N{\i0}line")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert segments[0].source_text == r"{\i1}bold\N{\i0}line"

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_hard_space_escape_preserved(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, r"a\h b")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert segments[0].source_text == r"a\h b"

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_leading_spaces_in_text_field_preserved(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "  padded  ")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert segments[0].source_text == "  padded  "

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_trailing_space_on_section_headers_is_parsed(self, tmp_path: Path, fmt: str) -> None:
        header = _min_header(fmt).replace(
            "[Script Info]\n",
            "[Script Info] \n",
        ).replace("[Events]\n", "[Events] \n")
        raw = _doc(fmt, _dialogue(fmt, "Hello world"), header=header).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert [segment.source_text for segment in segments] == ["Hello world"]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_indented_dialogue_is_parsed_not_swallowed(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, "  " + _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert [segment.source_text for segment in segments] == ["Hello world"]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_space_before_colon_keys_are_parsed(self, tmp_path: Path, fmt: str) -> None:
        header = _min_header(fmt).replace("ScriptType:", "ScriptType :")
        header = header.replace("Format: ", "Format : ")
        dialogue = _dialogue(fmt, "Hello world").replace("Dialogue:", "Dialogue :")
        raw = _doc(fmt, dialogue, header=header).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert [segment.source_text for segment in segments] == ["Hello world"]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_lowercase_keys_are_parsed(self, tmp_path: Path, fmt: str) -> None:
        header = _min_header(fmt).replace("ScriptType:", "scripttype:")
        header = header.replace("Format: ", "format: ")
        raw = _doc(fmt, _dialogue(fmt, "Hello world"), header=header).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert [segment.source_text for segment in segments] == ["Hello world"]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_indented_comment_is_structural(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            "  ; an indented comment",
            _dialogue(fmt, "Two", start="0:00:03.00"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert [segment.source_text for segment in segments] == ["One", "Two"]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_duplicate_timings_are_allowed(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _dialogue(fmt, "Two", start="0:00:01.00"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert len(segments) == 2
        assert [segment.source_text for segment in segments] == ["One", "Two"]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_non_events_sections_are_structural(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "One")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert len(segments) == 1
        assert segments[0].source_text == "One"

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_header_only_file_has_no_segments(self, tmp_path: Path, fmt: str) -> None:
        raw = _header(fmt).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import(path, project_id, raw, fmt)
        assert segments == []

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_stable_keys_deterministic_and_unique(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _dialogue(fmt, "Two"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document1, segments1 = _import(path, project_id, raw, fmt)
        document2, segments2 = _import(path, project_id, raw, fmt)
        assert document1 == document2
        assert [s.stable_key for s in segments1] == [s.stable_key for s in segments2]
        assert len({s.stable_key for s in segments1}) == 2

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_locator_records_timing_and_text_span(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        envelope = _envelope(path, document_id)
        assert envelope["locator"]["type"] == f"{fmt}.events"
        entry = envelope["locator"]["segments"][0]
        assert entry["sequence"] == 1
        assert entry["start"] == "0:00:01.00"
        assert entry["end"] == "0:00:02.00"
        span = raw[entry["byte_start"] : entry["byte_end"]]
        assert span.decode() == "Hello world"
        assert segments[0].source_text == "Hello world"


class TestNoOpByteIdentity:
    """A no-op export reproduces the source bytes byte-for-byte."""

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    @pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
    def test_noop_newline_style_byte_identical(
        self,
        tmp_path: Path,
        fmt: str,
        newline: str,
    ) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "Hello world"),
            _dialogue(fmt, "Second", start="0:00:03.00"),
            newline=newline,
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(path, document_id, target, fmt, apply_revisions=False)
        assert target.read_bytes() == raw

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_noop_full_document_with_sections_and_events(
        self,
        tmp_path: Path,
        fmt: str,
    ) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, r"{\i1}bold text{\i0}"),
            _comment(fmt, "a comment, with commas"),
            _dialogue(fmt, "Third line", start="0:00:03.00"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(path, document_id, target, fmt, apply_revisions=False)
        assert target.read_bytes() == raw

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_noop_utf8_bom(self, tmp_path: Path, fmt: str) -> None:
        raw = b"\xef\xbb\xbf" + _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(path, document_id, target, fmt, apply_revisions=False)
        assert target.read_bytes() == raw

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_noop_utf16_le_bom(self, tmp_path: Path, fmt: str) -> None:
        text = _doc(fmt, _dialogue(fmt, "Hello world"))
        raw = b"\xff\xfe" + text.encode("utf-16-le")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt, encoding="utf-16")
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(path, document_id, target, fmt, apply_revisions=False)
        assert target.read_bytes() == raw

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_noop_utf16_be_bom(self, tmp_path: Path, fmt: str) -> None:
        text = _doc(fmt, _dialogue(fmt, "Hello world"))
        raw = b"\xfe\xff" + text.encode("utf-16-be")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt, encoding="utf-16")
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(path, document_id, target, fmt, apply_revisions=False)
        assert target.read_bytes() == raw

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_noop_non_ascii_utf8(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "こんにちは世界")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(path, document_id, target, fmt, apply_revisions=False)
        assert target.read_bytes() == raw

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_noop_eof_without_trailing_newline(self, tmp_path: Path, fmt: str) -> None:
        head = _min_header(fmt).rstrip("\n")
        text = head + "\n" + _dialogue(fmt, "Hello world")
        raw = text.encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(path, document_id, target, fmt, apply_revisions=False)
        assert target.read_bytes() == raw

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_encoding_override_matching_succeeds_and_mismatch_refused(
        self,
        tmp_path: Path,
        fmt: str,
    ) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        target = _new_target(tmp_path, f"noop.{fmt}")
        _export(
            path,
            document_id,
            target,
            fmt,
            apply_revisions=False,
            encoding="utf-8",
        )
        assert target.read_bytes() == raw
        with pytest.raises(ExportError, match="cannot encode"):
            _export(
                path,
                document_id,
                target,
                fmt,
                apply_revisions=False,
                encoding="utf-16",
            )


class TestTranslatedReplacesOnlyDialogueText:
    """Translation replaces only the Text field of each Dialogue event."""

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_single_dialogue_replacement_is_exact(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world"), header=_min_header(fmt)).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["こんにちは世界"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        expected = _doc(
            fmt,
            _dialogue(fmt, "こんにちは世界"),
            header=_min_header(fmt),
        ).encode()
        assert target.read_bytes() == expected

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_multi_dialogue_replacement_preserves_all_structure(
        self,
        tmp_path: Path,
        fmt: str,
    ) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _dialogue(fmt, "Two", start="0:00:03.00"),
            _dialogue(fmt, "Three", start="0:00:05.00"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["一", "二", "三"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        out = target.read_bytes().decode("utf-8")
        assert _dialogue(fmt, "一") in out
        assert _dialogue(fmt, "二", start="0:00:03.00") in out
        assert _dialogue(fmt, "三", start="0:00:05.00") in out
        assert "One" not in out and "Two" not in out and "Three" not in out

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_comment_event_is_never_translated(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _comment(fmt, "keep me, please"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["一"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        out = target.read_bytes().decode("utf-8")
        assert "keep me, please" in out
        assert _dialogue(fmt, "一") in out
        assert out.count("Dialogue:") == 1
        assert out.count("Comment:") == 1

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_text_with_commas_replaced_correctly(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello, world!")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["こんにちは、世界！"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        out = target.read_bytes().decode("utf-8")
        assert _dialogue(fmt, "こんにちは、世界！") in out
        assert "Hello, world!" not in out

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_inline_tags_and_escapes_survive_translation(
        self,
        tmp_path: Path,
        fmt: str,
    ) -> None:
        raw = _doc(fmt, _dialogue(fmt, r"{\i1}bold\N{\i0}")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        translation = r"{\i1}太字\N{\i0}"
        _set_revisions(path, segments, [translation])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        out = target.read_bytes().decode("utf-8")
        assert translation in out

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_leading_space_text_field_replaced_as_whole(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "  padded  ")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["翻訳"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        out = target.read_bytes().decode("utf-8")
        assert _dialogue(fmt, "翻訳") in out

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_crlf_translated_replaces_text_only(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world"), newline="\r\n").encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["こんにちは世界"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        expected = raw.replace(b"Hello world", "こんにちは世界".encode())
        assert target.read_bytes() == expected

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_utf16_translated_replaces_text_only(self, tmp_path: Path, fmt: str) -> None:
        text = _doc(fmt, _dialogue(fmt, "Hello world"))
        raw = b"\xff\xfe" + text.encode("utf-16-le")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt, encoding="utf-16")
        _set_revisions(path, segments, ["こんにちは世界"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        expected = b"\xff\xfe" + text.replace(
            "Hello world",
            "こんにちは世界",
        ).encode("utf-16-le")
        assert target.read_bytes() == expected

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_reparse_of_export_round_trips_structure_and_values(
        self,
        tmp_path: Path,
        fmt: str,
    ) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _dialogue(fmt, "Two", start="0:00:03.00"),
            header=_min_header(fmt),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["一", "二"])
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)

        path2 = tmp_path / "project2.sqlite"
        project2 = _create_project(path2)
        _document2_id, segments2 = _import(path2, project2, target.read_bytes(), fmt)
        assert [segment.source_text for segment in segments2] == ["一", "二"]
        assert [segment.sequence for segment in segments2] == [1, 2]

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_revision_override_for_segment(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        segment_id = _ids(segments)[0]
        override_id = _add_revision(path, segment_id, "オーバーライド")
        target = _new_target(tmp_path, f"override.{fmt}")
        _export(
            path,
            document_id,
            target,
            fmt,
            revision_overrides={segment_id: override_id},
        )
        out = target.read_bytes().decode("utf-8")
        assert _dialogue(fmt, "オーバーライド") in out

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_locator_type_change_alone_is_benign(self, tmp_path: Path, fmt: str) -> None:
        # The shared seam does not independently validate ``locator.type``; the
        # envelope ``format`` and the per-segment span/timing verification are
        # the real guards (TXT/JSON/SRT/VTT share this behavior).
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_revisions(path, segments, ["こんにちは世界"])
        _tamper(path, document_id, lambda env: env["locator"].update(type="vtt.cues"))
        target = _new_target(tmp_path, f"translated.{fmt}")
        _export(path, document_id, target, fmt)
        out = target.read_bytes().decode("utf-8")
        assert _dialogue(fmt, "こんにちは世界") in out


class TestMalformedImportRejected:
    """Malformed ASS/SSA input is refused without polluting the database."""

    def _assert_import_rejected(
        self,
        path: Path,
        project_id: int,
        raw: bytes,
        fmt: str,
        match: str,
    ) -> None:
        source = path.parent / f"bad.{fmt}"
        source.write_bytes(raw)
        with ImportService(path, app_version=APP_VERSION) as service:
            with pytest.raises(AssSsaParseError, match=match):
                service.import_file(project_id, source, format=fmt)
        db = create_database(path)
        try:
            documents = db.execute(
                "SELECT COUNT(*) FROM source_documents WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            segments = db.execute(
                "SELECT COUNT(*) FROM segments WHERE source_document_id IN "
                "(SELECT id FROM source_documents WHERE project_id = ?)",
                (project_id,),
            ).fetchone()[0]
        finally:
            db.close()
        assert documents == 0
        assert segments == 0

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_srt_content_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, r"\[Script Info\]")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_wrong_script_type_rejected(self, tmp_path: Path, fmt: str) -> None:
        other = "ssa" if fmt == "ass" else "ass"
        raw = _doc(other, _dialogue(other, "Hello")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "ScriptType")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_missing_script_type_rejected(self, tmp_path: Path, fmt: str) -> None:
        header = (
            "[Script Info]\n"
            "Title: No type\n"
            "\n"
            "[Events]\n"
            f"{_events_format_line(fmt)}\n"
        )
        raw = _doc(fmt, _dialogue(fmt, "Hello"), header=header).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "ScriptType")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_missing_events_format_rejected(self, tmp_path: Path, fmt: str) -> None:
        header = (
            "[Script Info]\n"
            f"ScriptType: {_script_type(fmt)}\n"
            "\n"
            "[Events]\n"
        )
        text = header + _dialogue(fmt, "Hello") + "\n"
        raw = text.encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(
            path,
            project_id,
            raw,
            fmt,
            r"before the \[Events\] Format",
        )

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_nonstandard_events_format_rejected(self, tmp_path: Path, fmt: str) -> None:
        header = (
            "[Script Info]\n"
            f"ScriptType: {_script_type(fmt)}\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name\n"
        )
        text = header + _dialogue(fmt, "Hello") + "\n"
        raw = text.encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "Unsupported")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_duplicate_events_format_rejected(self, tmp_path: Path, fmt: str) -> None:
        header = (
            "[Script Info]\n"
            f"ScriptType: {_script_type(fmt)}\n"
            "\n"
            "[Events]\n"
            f"{_events_format_line(fmt)}\n"
        )
        text = header + _events_format_line(fmt) + "\n" + _dialogue(fmt, "Hello") + "\n"
        raw = text.encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "Duplicate")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_dialogue_too_few_fields_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, "Dialogue: 0,0:00:01.00,0:00:02.00,Default").encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "fields")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_empty_text_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "empty Text")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_whitespace_only_text_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "   ")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "empty Text")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    @pytest.mark.parametrize(
        "timing",
        [
            "garbage",
            "0:99:01.00",
            "0:00:99.00",
            "0:00:01.000",
            "00:01.00",
            "0:00:01,00",
        ],
    )
    def test_invalid_timing_rejected(self, tmp_path: Path, fmt: str, timing: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello", start=timing)).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        self._assert_import_rejected(path, project_id, raw, fmt, "invalid timing")


class TestVerificationFailuresRejected:
    """Any carrier validation failure is refused without writing a file."""

    def _assert_rejected(self, path: Path, document_id: int, fmt: str, match: str) -> None:
        target = _new_target(path.parent, f"rejected.{fmt}")
        with pytest.raises(ExportError, match=match):
            _export(path, document_id, target, fmt)
        assert not target.exists()

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_start_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(start="0:00:09.00"),
        )
        self._assert_rejected(path, document_id, fmt, "timing")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_end_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(end="0:00:09.00"),
        )
        self._assert_rejected(path, document_id, fmt, "timing")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_sequence_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _dialogue(fmt, "Two"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(sequence=99),
        )
        self._assert_rejected(path, document_id, fmt, "sequence")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_span_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(byte_start=0),
        )
        self._assert_rejected(path, document_id, fmt, "Text span")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_source_text_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE segments SET source_text = 'tampered' "
                    "WHERE source_document_id = ?",
                    (document_id,),
                )
        finally:
            db.close()
        self._assert_rejected(path, document_id, fmt, "source text")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_source_hash_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env.update(source_hash="0" * 64))
        self._assert_rejected(path, document_id, fmt, "source hash")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_bom_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env.update(bom="utf-16-le"))
        self._assert_rejected(path, document_id, fmt, "BOM")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_newline_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env.update(newline="crlf"))
        self._assert_rejected(path, document_id, fmt, "newline")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_metadata_version_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env.update(schema_version=99))
        self._assert_rejected(path, document_id, fmt, "schema version")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_parser_version_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env.update(parser_version="2.0.0"))
        self._assert_rejected(path, document_id, fmt, "parser version")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_wrong_format_envelope_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env.update(format="srt"))
        self._assert_rejected(path, document_id, fmt, "does not match")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_malformed_envelope_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET format_metadata = ? WHERE id = ?",
                    ("{not json", document_id),
                )
        finally:
            db.close()
        self._assert_rejected(path, document_id, fmt, "not valid JSON")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_stored_raw_bytes_hash_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET raw_bytes = ? WHERE id = ?",
                    (b"tampered bytes", document_id),
                )
        finally:
            db.close()
        self._assert_rejected(path, document_id, fmt, "raw bytes hash")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_missing_locator_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env.pop("locator"))
        self._assert_rejected(path, document_id, fmt, "no ASS/SSA segment locator")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_segment_count_mismatch_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(
            fmt,
            _dialogue(fmt, "One"),
            _dialogue(fmt, "Two"),
        ).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(path, document_id, lambda env: env["locator"]["segments"].pop())
        self._assert_rejected(path, document_id, fmt, "segment count")

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_cross_segment_revision_override_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw1 = _doc(fmt, _dialogue(fmt, "One")).encode()
        raw2 = _doc(fmt, _dialogue(fmt, "Two")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document1, segments1 = _import(path, project_id, raw1, fmt)
        document2, segments2 = _import(path, project_id, raw2, fmt)
        assert document1 != document2
        segment1_id = _ids(segments1)[0]
        segment2_id = _ids(segments2)[0]
        revision_of_other_segment = _add_revision(path, segment2_id, "二")
        _set_current_revision(path, segment1_id, "一")
        target = _new_target(tmp_path, f"cross.{fmt}")
        with pytest.raises(ExportError, match="belongs to segment"):
            _export(
                path,
                document1,
                target,
                fmt,
                revision_overrides={segment1_id: revision_of_other_segment},
            )
        assert not target.exists()

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_raw_bytes_that_no_longer_parse_rejected(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        # Rewrite raw_bytes AND its hash (and the envelope's stored hash)
        # consistently so the carrier hash checks pass, but the exporter's
        # re-parse of the raw bytes fails the SubStation signature check.
        tampered = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"
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
        self._assert_rejected(path, document_id, fmt, "not valid")


class TestFailuresDoNotPollute:
    """Encoding/write/verification failures preserve the target and the data."""

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_encoding_failure_preserves_target_and_data(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode("ascii")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt, encoding="ascii")
        _set_current_revision(path, _ids(segments)[0], "你好")
        target = _new_target(tmp_path, f"translated.{fmt}")
        target.write_bytes(b"OLD CONTENT")

        with pytest.raises(ExportError, match="encode"):
            _export(path, document_id, target, fmt)

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

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_unwritable_target_preserves_state(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
        _set_current_revision(path, _ids(segments)[0], "你好")
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("occupied", encoding="utf-8")
        target = blocker / f"translated.{fmt}"

        with pytest.raises(ExportError, match="temp file"):
            _export(path, document_id, target, fmt)
        assert not target.exists()

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_verification_failure_never_writes_partial_file(
        self,
        tmp_path: Path,
        fmt: str,
    ) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import(path, project_id, raw, fmt)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(start="0:00:09.00"),
        )
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        target = out_dir / f"translated.{fmt}"

        with pytest.raises(ExportError):
            _export(path, document_id, target, fmt)

        assert list(out_dir.iterdir()) == []

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_missing_carrier_rejected(self, tmp_path: Path, fmt: str) -> None:
        """A document without raw bytes cannot be exported with fidelity."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        raw = _doc(fmt, _dialogue(fmt, "Hello world")).encode()
        source = path.parent / f"source.{fmt}"
        source.write_bytes(raw)
        # Import, then clear the fidelity carrier like an old pre-008 document.
        with ImportService(path, app_version=APP_VERSION) as service:
            document, _segments = service.import_file(
                project_id,
                source,
                format=fmt,
            )
        assert document.id is not None
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET raw_bytes = NULL, "
                    "format_metadata = NULL WHERE id = ?",
                    (document.id,),
                )
        finally:
            db.close()
        target = _new_target(tmp_path, f"no-carrier.{fmt}")
        with pytest.raises(ExportError, match="no preserved original bytes"):
            _export(path, document.id, target, fmt)
        assert not target.exists()


class TestVerticalTranslationLoop:
    """A real translation run round-trips an ASS/SSA Dialogue through export."""

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

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_import_translate_export_round_trip(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world"), header=_min_header(fmt)).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
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

        target = _new_target(tmp_path, f"roundtrip.{fmt}")
        _export(path, document_id, target, fmt)

        expected = _doc(
            fmt,
            _dialogue(fmt, "こんにちは世界"),
            header=_min_header(fmt),
        ).encode()
        assert target.read_bytes() == expected

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_adapter_failure_finalizes_failed_attempt(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello world"), header=_min_header(fmt)).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import(path, project_id, raw, fmt)
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
        segment_id = _ids(segments)[0]
        repo = TranslationRevisionRepository.open(path)
        try:
            revisions = repo.list_by_segment(segment_id)
        finally:
            repo.close()
        assert revisions == []
        assert document_id is not None


class TestIdentityDomain:
    """ASS/SSA re-imports stay idempotent under the 008 logical identity."""

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_reimport_same_bytes_is_idempotent(self, tmp_path: Path, fmt: str) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document1, _segments1 = _import(path, project_id, raw, fmt)
        document2, _segments2 = _import(path, project_id, raw, fmt)
        assert document1 == document2
        db = create_database(path)
        try:
            count = db.execute(
                "SELECT COUNT(*) FROM source_documents WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
        finally:
            db.close()
        assert count == 1

    def test_same_bytes_as_ass_and_ssa_are_separate_documents(
        self,
        tmp_path: Path,
    ) -> None:
        raw_ass = _doc("ass", _dialogue("ass", "Hello")).encode()
        raw_ssa = _doc("ssa", _dialogue("ssa", "Hello")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_a, _segments_a = _import(path, project_id, raw_ass, "ass")
        document_b, _segments_b = _import(path, project_id, raw_ssa, "ssa")
        assert document_a != document_b

    @pytest.mark.parametrize("fmt", ["ass", "ssa"])
    def test_same_bytes_as_ass_and_txt_are_separate_documents(
        self,
        tmp_path: Path,
        fmt: str,
    ) -> None:
        raw = _doc(fmt, _dialogue(fmt, "Hello")).encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_fmt, _segments_fmt = _import(path, project_id, raw, fmt)
        source_txt = path.parent / "source.txt"
        source_txt.write_bytes(raw)
        with ImportService(path, app_version=APP_VERSION) as service:
            document_txt, _segments_txt = service.import_file(
                project_id,
                source_txt,
                format="txt",
            )
        assert document_txt.id is not None
        assert document_fmt != document_txt.id
