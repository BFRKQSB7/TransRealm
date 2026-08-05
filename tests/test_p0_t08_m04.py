"""Tests for P0-T08-M04: Revision-driven TXT export.

The exporter writes each segment's current revision (or an explicitly
validated override) in original sequence order. Missing/cross-segment/invalid
revisions, encoding failures and unwritable targets fail without leaving a
half file, and never fall back to source text or unverified output.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.application.exporter import ExportError, TxtExporter
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_service import TranslationService
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.segment import Segment
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}


class SequenceAdapter:
    """In-memory ModelAdapter returning a fixed sequence of valid responses."""

    def __init__(self, responses: list[AdapterResponse]) -> None:
        self.responses = responses
        self.calls = 0

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
        index = min(self.calls - 1, len(self.responses) - 1)
        return self.responses[index]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _create_project(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="M04",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_txt(path: Path, project_id: int, content: str) -> tuple[int, list[Segment]]:
    txt_path = path.parent / "source.txt"
    txt_path.write_text(content, encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_txt(project_id, txt_path, name="source.txt")
    assert document.id is not None
    return document.id, segments


def _create_profile(path: Path) -> int:
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.create_connection(
            name="local",
            provider_type="openai-compatible",
            endpoint="http://localhost:8080/v1",
            timeout_seconds=30,
            max_retries=0,
            retry_delay_seconds=0.0,
            credential_reference=None,
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
    return profile.id


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


def _translate_all(
    path: Path,
    project_id: int,
    segments: list[Segment],
    profile_id: int,
    translations: list[str],
) -> None:
    adapter = SequenceAdapter(
        [_valid_response(segments[i].stable_key, translations[i]) for i in range(len(segments))],
    )
    with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
        run = service.create_run(project_id=project_id)
        assert run.id is not None
        for segment in segments:
            assert segment.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=segment.id,
                    profile_id=profile_id,
                ),
            )


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


def _export(
    path: Path,
    source_document_id: int,
    target_path: Path,
    **kwargs: Any,
) -> None:
    exporter = TxtExporter(path, app_version=APP_VERSION)
    try:
        exporter.export_document(
            source_document_id=source_document_id,
            target_path=target_path,
            **kwargs,
        )
    finally:
        exporter.close()


def _list_segments(path: Path, document_id: int) -> list[Segment]:
    repo = SegmentRepository.open(path)
    try:
        return repo.list_segments_by_document(document_id)
    finally:
        repo.close()


def _translated_document(
    tmp_path: Path,
    content: str,
    translations: list[str],
) -> tuple[Path, int, list[Segment], int]:
    path = tmp_path / "project.sqlite"
    project_id = _create_project(path)
    document_id, segments = _import_txt(path, project_id, content)
    profile_id = _create_profile(path)
    _translate_all(path, project_id, segments, profile_id, translations)
    # Re-fetch so current_revision_id reflects the completed translations.
    return path, document_id, _list_segments(path, document_id), profile_id


class TestDefaultExport:
    """Current revisions are exported in original sequence order."""

    def test_exports_current_revisions_in_order(self, tmp_path: Path) -> None:
        path, document_id, segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\nBeta line.\nGamma line.\n",
            ["甲行", "乙行", "丙行"],
        )
        target = tmp_path / "export" / "translated.txt"
        target.parent.mkdir()
        _export(path, document_id, target)

        assert target.read_text(encoding="utf-8") == "甲行\n乙行\n丙行\n"
        assert len(segments) == 3

    def test_order_matches_source_sequence(self, tmp_path: Path) -> None:
        path, document_id, _segments, _ = _translated_document(
            tmp_path,
            "First.\nSecond.\nThird.\n",
            ["one", "two", "three"],
        )
        target = tmp_path / "export" / "translated.txt"
        target.parent.mkdir()
        _export(path, document_id, target)

        lines = target.read_text(encoding="utf-8").splitlines()
        assert lines == ["one", "two", "three"]

    def test_unicode_translation_round_trips_utf8(self, tmp_path: Path) -> None:
        path, document_id, _segments, _ = _translated_document(
            tmp_path,
            "こんにちは世界。\n",
            ["Hello, world!"],
        )
        target = tmp_path / "export" / "translated.txt"
        target.parent.mkdir()
        _export(path, document_id, target)

        assert target.read_text(encoding="utf-8") == "Hello, world!\n"


class TestMissingAndInvalidRevisions:
    """Failures never write a file or fall back to source text."""

    def test_missing_current_revision_fails_without_file(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _segments = _import_txt(path, project_id, "Alpha line.\n")

        target = tmp_path / "export" / "translated.txt"
        with pytest.raises(ExportError, match="no current revision"):
            _export(path, document_id, target)

        assert not target.exists()

    def test_partial_translation_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_txt(
            path,
            project_id,
            "Alpha line.\nBeta line.\n",
        )
        profile_id = _create_profile(path)
        # Translate only the first segment.
        adapter = SequenceAdapter([_valid_response(segments[0].stable_key, "甲")])
        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            assert segments[0].id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=segments[0].id,
                    profile_id=profile_id,
                ),
            )

        target = tmp_path / "export" / "translated.txt"
        with pytest.raises(ExportError, match="no current revision"):
            _export(path, document_id, target)

        assert not target.exists()

    def test_invalid_revision_override_fails(self, tmp_path: Path) -> None:
        path, document_id, segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\n",
            ["甲"],
        )
        assert segments[0].id is not None
        target = tmp_path / "export" / "translated.txt"
        with pytest.raises(ExportError, match="does not exist"):
            _export(
                path,
                document_id,
                target,
                revision_overrides={segments[0].id: 999999},
            )
        assert not target.exists()

    def test_cross_segment_revision_override_fails(self, tmp_path: Path) -> None:
        path, document_id, segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\nBeta line.\n",
            ["甲", "乙"],
        )
        assert segments[0].id is not None
        assert segments[1].id is not None
        target = tmp_path / "export" / "translated.txt"
        with pytest.raises(ExportError, match="belongs to segment"):
            _export(
                path,
                document_id,
                target,
                revision_overrides={segments[0].id: segments[1].current_revision_id or 0},
            )
        assert not target.exists()

    def test_override_for_unknown_segment_fails(self, tmp_path: Path) -> None:
        path, document_id, _segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\n",
            ["甲"],
        )
        target = tmp_path / "export" / "translated.txt"
        with pytest.raises(ExportError, match="not in this document"):
            _export(path, document_id, target, revision_overrides={424242: 1})
        assert not target.exists()

    def test_unknown_document_fails(self, tmp_path: Path) -> None:
        path, _document_id, _segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\n",
            ["甲"],
        )
        target = tmp_path / "export" / "translated.txt"
        with pytest.raises(ExportError, match="SourceDocument"):
            _export(path, 999999, target)
        assert not target.exists()


class TestExplicitRevision:
    """An explicit valid revision is used and validated."""

    def test_override_uses_non_current_valid_revision(self, tmp_path: Path) -> None:
        path, document_id, segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\n",
            ["当前版本"],
        )
        assert segments[0].id is not None
        historical_id = _add_revision(path, segments[0].id, "历史版本")

        default_target = tmp_path / "export" / "default.txt"
        override_target = tmp_path / "export" / "override.txt"
        default_target.parent.mkdir()
        _export(path, document_id, default_target)
        _export(
            path,
            document_id,
            override_target,
            revision_overrides={segments[0].id: historical_id},
        )

        assert default_target.read_text(encoding="utf-8") == "当前版本\n"
        assert override_target.read_text(encoding="utf-8") == "历史版本\n"


class TestWriteFailureAtomicity:
    """Encoding and target failures leave no half file and preserve targets."""

    def test_encoding_failure_preserves_existing_target(self, tmp_path: Path) -> None:
        path, document_id, _segments, _ = _translated_document(
            tmp_path,
            "こんにちは世界。\n",
            ["你好世界"],
        )
        out_dir = tmp_path / "export"
        out_dir.mkdir()
        target = out_dir / "translated.txt"
        target.write_text("OLD CONTENT", encoding="utf-8")

        with pytest.raises(ExportError, match="encode"):
            _export(path, document_id, target, encoding="ascii")

        assert target.read_text(encoding="utf-8") == "OLD CONTENT"
        assert list(out_dir.iterdir()) == [target]

    def test_revision_failure_preserves_existing_target(self, tmp_path: Path) -> None:
        path, document_id, segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\nBeta line.\n",
            ["甲", "乙"],
        )
        assert segments[0].id is not None
        assert segments[1].id is not None
        out_dir = tmp_path / "export"
        out_dir.mkdir()
        target = out_dir / "translated.txt"
        target.write_text("OLD CONTENT", encoding="utf-8")

        with pytest.raises(ExportError, match="belongs to segment"):
            _export(
                path,
                document_id,
                target,
                revision_overrides={segments[0].id: segments[1].current_revision_id or 0},
            )

        assert target.read_text(encoding="utf-8") == "OLD CONTENT"
        assert list(out_dir.iterdir()) == [target]

    def test_missing_target_directory_fails(self, tmp_path: Path) -> None:
        path, document_id, _segments, _ = _translated_document(
            tmp_path,
            "Alpha line.\n",
            ["甲"],
        )
        target = tmp_path / "missing" / "translated.txt"
        with pytest.raises(ExportError, match="Target directory"):
            _export(path, document_id, target)
        assert not target.exists()
