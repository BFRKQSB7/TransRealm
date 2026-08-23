"""V02-T02-M01 acceptance for the six-format GUI journey."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.segment import Segment
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.0.0-test"
FORMATS = ("txt", "json", "srt", "ass", "ssa", "vtt")


class SequenceAdapter:
    """In-memory fake endpoint returning one valid response per segment."""

    def __init__(self, responses: list[AdapterResponse]) -> None:
        self.responses = list(responses)
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
        del request
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _response(segment: Segment, fmt: str) -> AdapterResponse:
    content = json.dumps(
        {
            "items": [
                {
                    "segment_id": segment.stable_key,
                    "translation": f"translated-{fmt}",
                },
            ],
        },
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id=f"req-{fmt}",
        raw_response=None,
    )


def _source(fmt: str) -> str:
    if fmt == "txt":
        return "Alpha line.\n"
    if fmt == "json":
        return '{"title":"Alpha line."}\n'
    if fmt == "srt":
        return "1\n00:00:01,000 --> 00:00:02,000\nAlpha line.\n"
    if fmt == "vtt":
        return "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAlpha line.\n"
    if fmt == "ass":
        return (
            "[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Alpha line.\n"
        )
    if fmt == "ssa":
        return (
            "[Script Info]\nScriptType: v4.00\n\n[Events]\n"
            "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: Marked=0,0:00:01.00,0:00:02.00,Default,,0000,0000,0000,,Alpha line.\n"
        )
    raise AssertionError(fmt)


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    created: list[MainWindow] = []

    def make() -> tuple[MainWindow, dict[str, Any]]:
        holder: dict[str, Any] = {}
        settings = QSettings(
            str(tmp_path / "settings.ini"),
            QSettings.Format.IniFormat,
        )
        window = MainWindow(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
            adapter_factory=lambda profile_id: holder["adapter"],
            settings=settings,
        )
        qtbot.addWidget(window)
        created.append(window)
        return window, holder

    yield make
    for window in created:
        window.shutdown()


def _setup_project(window: MainWindow, qtbot: Any) -> None:
    settings = window._settings
    settings._conn_name.setText("local")
    settings._conn_endpoint.setText("http://localhost:8080/v1")
    settings._add_connection.click()
    qtbot.waitUntil(lambda: settings._connections_list.count() == 1, timeout=5000)
    settings._profile_name.setText("general")
    settings._profile_model.setText("gpt-4o-mini")
    qtbot.waitUntil(lambda: settings._profile_connection.count() == 1, timeout=5000)
    settings._add_profile.click()
    qtbot.waitUntil(lambda: settings._profiles_list.count() == 1, timeout=5000)

    project = window._project
    project._project_name.setText("Six formats")
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
    qtbot.waitUntil(lambda: project._active_profile_combo.count() == 1, timeout=5000)
    project._set_active.click()
    qtbot.waitUntil(lambda: "Active:" in project._active_profile_label.text(), timeout=5000)


@pytest.mark.parametrize("fmt", FORMATS)
def test_gui_six_format_import_translate_export(
    fmt: str,
    qtbot: Any,
    window_factory: Any,
    tmp_path: Path,
) -> None:
    window, holder = window_factory()
    _setup_project(window, qtbot)
    source = tmp_path / f"source.{fmt}"
    source.write_text(_source(fmt), encoding="utf-8")

    project = window._project
    translation = window._translation
    project.import_file(source)
    qtbot.waitUntil(
        lambda: translation._document_id is not None
        and translation._document_name == source.name,
        timeout=10000,
    )
    assert translation._document_format == fmt

    repo = SegmentRepository.open(tmp_path / "project.sqlite")
    try:
        segments = repo.list_segments_by_document(translation._document_id)
    finally:
        repo.close()
    holder["adapter"] = SequenceAdapter([_response(segment, fmt) for segment in segments])

    translation.translate()
    finished = [False]
    window._translation_worker.finished.connect(lambda: finished.__setitem__(0, True))
    qtbot.waitUntil(lambda: finished[0], timeout=20000)
    assert holder["adapter"].calls == len(segments)

    target = tmp_path / f"translated.{fmt}"
    translation.export_to(target)
    qtbot.waitUntil(lambda: translation._status.text() == "Export written.", timeout=10000)
    assert target.is_file()
    assert target.suffix == source.suffix
    assert target.read_bytes() != source.read_bytes()


@pytest.mark.parametrize("fmt", FORMATS)
def test_gui_export_failure_preserves_existing_target(
    fmt: str,
    qtbot: Any,
    window_factory: Any,
    tmp_path: Path,
) -> None:
    window, _ = window_factory()
    _setup_project(window, qtbot)
    source = tmp_path / f"source.{fmt}"
    source.write_text(_source(fmt), encoding="utf-8")
    window._project.import_file(source)
    translation = window._translation
    qtbot.waitUntil(lambda: translation._document_id is not None, timeout=10000)

    target = tmp_path / f"translated.{fmt}"
    target.write_text("keep this file", encoding="utf-8")
    translation.export_to(target)
    qtbot.waitUntil(lambda: translation._status.text().startswith("Error:"), timeout=10000)
    assert target.read_text(encoding="utf-8") == "keep this file"
