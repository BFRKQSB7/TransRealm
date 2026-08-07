"""Tests for P1-T01-M02: the JSON vertical closed loop.

Covers the DEC-P1-T01-FOUNDATION plan-2 acceptance matrix for JSON: only
string values in value position become stable structural-path Segments; no-op
exports are byte-identical (nested/escapes/non-ASCII/UTF-8 BOM/UTF-16 BOM/CRLF/
empty containers/no-string documents); translated exports replace only the
value tokens while preserving keys, ordering, numbers, booleans, escaping and
whitespace; malformed input, duplicate keys, excessive nesting, and
path/span/hash/BOM/parser-version mismatches are rejected without polluting the
database, revisions, or an existing target file; and a real translation run
round-trips a JSON value through the pipeline and back out byte-accurately.
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
from transrealm.application.exporter import ExportError, JsonExporter
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_service import TranslationService
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.segment import Segment
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.parsers.json_parser import JSONParseError
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
            name="M02",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_json(
    path: Path,
    project_id: int,
    raw: bytes,
    *,
    encoding: str = "utf-8",
    name: str = "source.json",
) -> tuple[int, list[Segment]]:
    source = path.parent / name
    source.write_bytes(raw)
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_file(
            project_id,
            source,
            format="json",
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
    exporter = JsonExporter(path, app_version=APP_VERSION)
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
    """String leaf values become Segments with stable structural paths."""

    def test_only_string_values_in_value_position_are_segments(self, tmp_path: Path) -> None:
        raw = (
            b'{"greeting": "hello", "count": 42, '
            b'"nested": {"deep": [true, null, {"inner": "world"}]}}'
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_json(path, project_id, raw)

        assert [s.source_text for s in segments] == ["hello", "world"]
        assert [s.sequence for s in segments] == [1, 2]

    def test_structural_paths_are_stored_in_the_locator(self, tmp_path: Path) -> None:
        raw = b'{"a": {"b": ["x", "y"]}}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)

        assert [s.source_text for s in segments] == ["x", "y"]
        envelope = _envelope(path, document_id)
        locator = envelope["locator"]
        assert locator["type"] == "json.paths"
        entries = locator["segments"]
        assert [e["path"] for e in entries] == ["/a/b/0", "/a/b/1"]
        assert [e["sequence"] for e in entries] == [1, 2]

    def test_array_index_and_escaped_keys_build_paths(self, tmp_path: Path) -> None:
        raw = b'[["top", "x"], {"a/b": "y", "t~e": "z"}]'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)

        assert [s.source_text for s in segments] == ["top", "x", "y", "z"]
        envelope = _envelope(path, document_id)
        paths = [e["path"] for e in envelope["locator"]["segments"]]
        assert paths == ["/0/0", "/0/1", "/1/a~1b", "/1/t~0e"]

    def test_stable_keys_are_deterministic_and_unique(self, tmp_path: Path) -> None:
        raw = b'{"a": [{"b": "x"}, {"b": "x"}]}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_json(path, project_id, raw)

        assert len(segments) == 2
        assert segments[0].source_text == "x"
        assert segments[1].source_text == "x"
        assert segments[0].stable_key != segments[1].stable_key
        _document_id2, segments2 = _import_json(path, project_id, raw)
        assert [s.stable_key for s in segments2] == [s.stable_key for s in segments]

    def test_bare_string_root_is_a_segment(self, tmp_path: Path) -> None:
        raw = b'"hello"'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)

        assert [s.source_text for s in segments] == ["hello"]
        envelope = _envelope(path, document_id)
        assert envelope["locator"]["segments"][0]["path"] == ""

    def test_empty_string_value_is_a_segment(self, tmp_path: Path) -> None:
        raw = b'{"a": ""}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_json(path, project_id, raw)

        assert [s.source_text for s in segments] == [""]

    def test_document_without_string_leaves_has_no_segments(self, tmp_path: Path) -> None:
        raw = b'{"n": -12.5e3, "m": 0, "p": 1.50, "q": 1E+2, "f": false, "t": true, "z": null}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_json(path, project_id, raw)

        assert segments == []

    def test_unescaped_values_are_decoded(self, tmp_path: Path) -> None:
        raw = b'{"k": "a\\nb", "m": "c\\\\d", "u": "\\u00e9", "e": "\\ud83d\\ude00"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_json(path, project_id, raw)

        assert [s.source_text for s in segments] == ["a\nb", "c\\d", "é", "\U0001f600"]

    def test_unpaired_surrogates_rejected(self, tmp_path: Path) -> None:
        """Lone surrogate \\u escapes are rejected as invalid input."""
        for index, content in enumerate(
            (
                b'{"s": "\\ud83d"}',  # lone high surrogate
                b'{"s": "\\ude00"}',  # lone low surrogate
                b'{"s": "\\ud83d\\u0041"}',  # high followed by a non-low escape
                b'{"s": "\\ud83d\\ud83d"}',  # two high surrogates
            ),
        ):
            path = tmp_path / f"project_{index}.sqlite"
            project_id = _create_project(path)
            source = path.parent / "bad.json"
            source.write_bytes(content)

            with pytest.raises(JSONParseError, match="surrogate"):
                with ImportService(path, app_version=APP_VERSION) as service:
                    service.import_file(project_id, source, format="json", name="bad.json")


class TestNoOpByteIdentity:
    """Import -> no-op export is byte-for-byte identical."""

    def test_noop_nested_with_whitespace(self, tmp_path: Path) -> None:
        raw = (
            b'{\n  "greeting": "hello",\n  "nested": {\n'
            b'    "deep": [1, 2, 3],\n    "flag": true\n  },\n'
            b'  "none": null\n}\n'
        )
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_tabs_and_number_formats(self, tmp_path: Path) -> None:
        raw = b'{\t"a":\t"x",\t"n": -12.5e3,\t"m": 1E+2,\t"p": 0.50\t}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_non_ascii_utf8(self, tmp_path: Path) -> None:
        raw = '{"msg": "こんにちは世界", "arr": ["日本語"]}\n'.encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf8_bom(self, tmp_path: Path) -> None:
        raw = b"\xef\xbb\xbf" + b'{"a": "hello", "b": "world"}\n'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw, encoding="utf-8")
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf16_le_bom(self, tmp_path: Path) -> None:
        raw = '{"a": "hello", "b": "world"}\r\n'.encode("utf-16")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw, encoding="utf-16")
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf16_be_bom(self, tmp_path: Path) -> None:
        raw = b"\xfe\xff" + '{"a": "hello"}\n'.encode("utf-16-be")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw, encoding="utf-16")
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_empty_containers(self, tmp_path: Path) -> None:
        raw = b'{"a": {}, "b": [], "c": {"d": {}}}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_no_string_document(self, tmp_path: Path) -> None:
        raw = b'[1, 2.5, true, false, null, -3e2]'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        target = _new_target(tmp_path, "noop.json")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw


class TestTranslatedReplacesOnlyValueToken:
    """Revisions change only the target string value tokens."""

    def test_single_value_replacement_preserves_structure(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello", "n": 42}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        assert len(segments) == 1
        _set_current_revision(path, segments[0].id or 0, "你好")
        target = _new_target(tmp_path, "translated.json")

        _export(path, document_id, target)

        assert target.read_bytes() == '{"a": "你好", "n": 42}'.encode()

    def test_multi_value_preserves_keys_order_numbers_whitespace(self, tmp_path: Path) -> None:
        raw = b'{\n  "z": 1,\n  "a": {"x": "one", "y": [true, null, 42]},\n  "b": "two"\n}\n'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        ids = _ids(segments)
        assert [s.source_text for s in segments] == ["one", "two"]
        _set_current_revision(path, ids[0], "一")
        _set_current_revision(path, ids[1], "二")
        target = _new_target(tmp_path, "translated.json")

        _export(path, document_id, target)

        expected = (
            '{\n  "z": 1,\n  "a": {"x": "一", "y": [true, null, 42]},\n'
            '  "b": "二"\n}\n'
        ).encode()
        assert target.read_bytes() == expected

    def test_escapes_outside_target_and_value_escaping(self, tmp_path: Path) -> None:
        raw = b'{"k": "a\\nb", "m": "c\\\\d", "u": "\\u00e9"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        ids = _ids(segments)
        assert [s.source_text for s in segments] == ["a\nb", "c\\d", "é"]
        # Translating all values still preserves the non-target skeleton
        # (keys/colons/commas), and every translation is re-escaped into a
        # valid JSON string literal -- quotes, backslashes and newlines.
        translations = {
            ids[0]: 'x\ny "quoted" \\ z',
            ids[1]: "m\v\tend",
            ids[2]: "é",
        }
        for segment_id, text in translations.items():
            _set_current_revision(path, segment_id, text)
        target = _new_target(tmp_path, "translated.json")

        _export(path, document_id, target)

        expected = (
            '{"k": '
            + json.dumps(translations[ids[0]], ensure_ascii=False)
            + ', "m": '
            + json.dumps(translations[ids[1]], ensure_ascii=False)
            + ', "u": '
            + json.dumps(translations[ids[2]], ensure_ascii=False)
            + "}"
        )
        assert target.read_bytes().decode("utf-8") == expected
        assert json.loads(expected) == {
            "k": 'x\ny "quoted" \\ z',
            "m": "m\v\tend",
            "u": "é",
        }

    def test_reparse_of_export_round_trips_structure_and_values(self, tmp_path: Path) -> None:
        raw = b'{"title": "hello", "items": [{"name": "one"}, {"name": "two"}]}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        ids = _ids(segments)
        translations = {ids[0]: "标题", ids[1]: "一", ids[2]: "二"}
        for segment_id, text in translations.items():
            _set_current_revision(path, segment_id, text)
        target = _new_target(tmp_path, "translated.json")

        _export(path, document_id, target)

        loaded = json.loads(target.read_bytes().decode("utf-8"))
        assert loaded == {
            "title": "标题",
            "items": [{"name": "一"}, {"name": "二"}],
        }
        # Re-importing the exported file yields the translated values as the
        # new source segments (same structure).
        _document2, segments2 = _import_json(
            path,
            project_id,
            target.read_bytes(),
            name="reimport.json",
        )
        assert [s.source_text for s in segments2] == ["标题", "一", "二"]

    def test_utf16_translated_replaces_token_only(self, tmp_path: Path) -> None:
        raw = '{"a": "hello", "b": "world"}\r\n'.encode("utf-16")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw, encoding="utf-16")
        ids = _ids(segments)
        _set_current_revision(path, ids[0], "甲")
        _set_current_revision(path, ids[1], "乙")
        target = _new_target(tmp_path, "translated.json")

        _export(path, document_id, target)

        text = target.read_bytes().decode("utf-16")
        assert text == '{"a": "甲", "b": "乙"}\r\n'
        assert json.loads(text) == {"a": "甲", "b": "乙"}

    def test_empty_string_value_gets_a_revision(self, tmp_path: Path) -> None:
        raw = b'{"a": ""}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        assert segments[0].source_text == ""
        _set_current_revision(path, segments[0].id or 0, "filled")
        target = _new_target(tmp_path, "translated.json")

        _export(path, document_id, target)

        assert target.read_bytes() == b'{"a": "filled"}'

    def test_revision_override_for_json(self, tmp_path: Path) -> None:
        raw = b'{"a": "one", "b": "two"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        ids = _ids(segments)
        _set_current_revision(path, ids[0], "一")
        _set_current_revision(path, ids[1], "二")
        historical = _add_revision(path, ids[0], "X")
        target = _new_target(tmp_path, "override.json")

        _export(path, document_id, target, revision_overrides={ids[0]: historical})

        assert target.read_bytes() == '{"a": "X", "b": "二"}'.encode()


class TestVerificationFailuresRejected:
    """Any carrier validation failure is refused without writing a file."""

    def _assert_rejected(self, path: Path, document_id: int, match: str) -> None:
        target = _new_target(path.parent, "rejected.json")
        with pytest.raises(ExportError, match=match):
            _export(path, document_id, target)
        assert not target.exists()

    def test_path_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"][0].update(path="/wrong"))

        self._assert_rejected(path, document_id, "structural path")

    def test_span_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"][0].update(byte_start=0))

        self._assert_rejected(path, document_id, "byte span")

    def test_value_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
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

    def test_sequence_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "one", "b": "two"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"][0].update(sequence=99))

        self._assert_rejected(path, document_id, "sequence")

    def test_source_hash_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(source_hash="0" * 64))

        self._assert_rejected(path, document_id, "source hash")

    def test_bom_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(bom="utf-16-le"))

        self._assert_rejected(path, document_id, "BOM")

    def test_newline_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}\n'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(newline="crlf"))

        self._assert_rejected(path, document_id, "newline")

    def test_metadata_version_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(schema_version=99))

        self._assert_rejected(path, document_id, "schema version")

    def test_parser_version_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(parser_version="2.0.0"))

        self._assert_rejected(path, document_id, "parser version")

    def test_wrong_format_envelope_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(format="txt"))

        self._assert_rejected(path, document_id, "does not match")

    def test_malformed_envelope_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
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
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET raw_bytes = ? WHERE id = ?",
                    (b'{"a": "tampered"}', document_id),
                )
        finally:
            db.close()

        self._assert_rejected(path, document_id, "raw bytes hash")

    def test_missing_locator_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.pop("locator"))

        self._assert_rejected(path, document_id, "no JSON segment locator")

    def test_segment_count_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "one", "b": "two"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"].pop())

        self._assert_rejected(path, document_id, "segment count")

    def test_cross_segment_revision_override_rejected(self, tmp_path: Path) -> None:
        raw = b'{"a": "one", "b": "two"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        ids = _ids(segments)
        _set_current_revision(path, ids[0], "一")
        _set_current_revision(path, ids[1], "二")
        rev_of_b = _add_revision(path, ids[1], "乙")
        target = _new_target(tmp_path, "rejected.json")

        with pytest.raises(ExportError, match="belongs to segment"):
            _export(path, document_id, target, revision_overrides={ids[0]: rev_of_b})
        assert not target.exists()


class TestMalformedImportRejected:
    """Malformed JSON is rejected at import without polluting the database."""

    @pytest.mark.parametrize(
        "content",
        [
            b'{"a": "x"',  # unterminated object
            b'{"a": "x",}',  # trailing comma
            b'{"a": 01}',  # leading zero
            b'{"a": 1.}',  # fraction with no digits
            b'{"a": 1e}',  # exponent with no digits
            b'{"a": "\\q"}',  # invalid escape
            b'{"a":"x"} extra',  # trailing garbage
            b"123 abc",  # trailing content after number
            b"5 6",  # trailing token after scalar root
            b'"a" 5',  # trailing token after string root
            b"true null",  # trailing token after literal root
            b"{} 5",  # trailing token after empty object
            b"[] 7",  # trailing token after empty array
            b'{"a":"x"} 5',  # trailing token after object
            b"+1",  # leading plus
            b".5",  # leading dot
            b'{"a": [1,,2]}',  # double comma
            b'"abc',  # unterminated string
            b"",  # empty file
            b"   ",  # whitespace only
            b'{"a":"x","a":"y"}',  # duplicate keys
            b'{"a": "x\t"}',  # literal tab inside string
            b"nulx",  # broken literal
        ],
    )
    def test_malformed_import_rejected_no_pollution(
        self,
        tmp_path: Path,
        content: bytes,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        source = tmp_path / "bad.json"
        source.write_bytes(content)

        with pytest.raises(JSONParseError):
            with ImportService(path, app_version=APP_VERSION) as service:
                service.import_file(project_id, source, format="json", name="bad.json")

        db = create_database(path)
        try:
            documents = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
            segments = db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        finally:
            db.close()
        assert documents == 0
        assert segments == 0

    def test_excessive_nesting_rejected_no_pollution(self, tmp_path: Path) -> None:
        deep = ("[" * 600 + "]") * 600
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        source = tmp_path / "deep.json"
        source.write_text(deep, encoding="utf-8")

        with pytest.raises(JSONParseError, match="nesting"):
            with ImportService(path, app_version=APP_VERSION) as service:
                service.import_file(project_id, source, format="json", name="deep.json")

        db = create_database(path)
        try:
            documents = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
        finally:
            db.close()
        assert documents == 0


class TestFailuresDoNotPollute:
    """Encoding/write/verification failures preserve the target and the data."""

    def test_encoding_failure_preserves_target_and_data(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw, encoding="ascii")
        _set_current_revision(path, segments[0].id or 0, "你好")
        target = _new_target(tmp_path, "translated.json")
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
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        _set_current_revision(path, segments[0].id or 0, "你好")
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("occupied", encoding="utf-8")
        target = blocker / "translated.json"

        with pytest.raises(ExportError, match="temp file"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_verification_failure_never_writes_partial_file(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_json(path, project_id, raw)
        _tamper(path, document_id, lambda env: env["locator"]["segments"][0].update(path="/wrong"))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        target = out_dir / "translated.json"

        with pytest.raises(ExportError):
            _export(path, document_id, target)

        assert list(out_dir.iterdir()) == []

    def test_missing_carrier_rejected(self, tmp_path: Path) -> None:
        """A document without raw bytes cannot be exported with fidelity."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        source = tmp_path / "source.json"
        source.write_bytes(b'{"a": "hello"}')
        with ImportService(path, app_version=APP_VERSION) as service:
            document, _ = service.import_file(
                project_id,
                source,
                format="json",
                name="source.json",
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

        target = _new_target(tmp_path, "missing.json")
        with pytest.raises(ExportError, match="no preserved original bytes"):
            _export(path, document.id, target, apply_revisions=False)
        assert not target.exists()


class TestVerticalTranslationLoop:
    """A real translation run round-trips a JSON value through export."""

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
        raw = b'{"message": "Hello world."}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_json(path, project_id, raw)
        assert len(segments) == 1
        profile = self._create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key, "こんにちは"))

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
        assert revision.text == "こんにちは"
        assert fake.calls == 1

        target = _new_target(tmp_path, "roundtrip.json")
        _export(path, document_id, target)

        assert target.read_bytes() == '{"message": "こんにちは"}'.encode()
        assert json.loads(target.read_bytes().decode("utf-8")) == {"message": "こんにちは"}

    def test_adapter_failure_finalizes_failed_attempt(self, tmp_path: Path) -> None:
        raw = b'{"message": "Hello world."}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_json(path, project_id, raw)
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
    """JSON re-imports stay idempotent under the 008 logical identity."""

    def test_reimport_same_json_is_idempotent(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello", "b": "world"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document1, segments1 = _import_json(path, project_id, raw)
        document2, segments2 = _import_json(path, project_id, raw)

        assert document1 == document2
        assert [s.id for s in segments1] == [s.id for s in segments2]
        db = create_database(path)
        try:
            count = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
        finally:
            db.close()
        assert count == 1

    def test_same_bytes_as_txt_and_json_are_separate_documents(self, tmp_path: Path) -> None:
        raw = b'{"a": "hello"}'
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        json_doc, json_segments = _import_json(path, project_id, raw, name="source.json")
        txt_source = path.parent / "source.txt"
        txt_source.write_bytes(raw)
        with ImportService(path, app_version=APP_VERSION) as service:
            txt_doc, _ = service.import_file(
                project_id,
                txt_source,
                format="txt",
                name="source.txt",
            )
        assert json_doc != txt_doc
        assert [s.source_text for s in json_segments] == ["hello"]
