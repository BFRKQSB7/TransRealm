"""Tests for P0-T08-M05: the non-blocking desktop shell.

The main window drives the full flow (Settings -> Project -> Translation)
through Application Services on worker threads, so the Qt main thread never
runs SQLite, parsing or model calls. pytest-qt proves the main thread stays
responsive during translation, cancel stops at a segment boundary, and window
close converges the worker threads instead of killing them.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QTimer

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.segment import Segment
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.0.0-test"


class SequenceAdapter:
    """In-memory adapter returning a fixed response sequence, optionally slowly."""

    def __init__(self, responses: list[AdapterResponse], delay: float = 0.0) -> None:
        self.responses = list(responses)
        self.delay = delay
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
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.responses[index]


def _valid_response(stable_key: str, translation: str) -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-ui",
        raw_response=None,
    )


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build a MainWindow that translates through a test-provided adapter."""
    created: list[MainWindow] = []

    def make(adapter_holder: dict[str, Any]) -> MainWindow:
        window = MainWindow(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
            adapter_factory=lambda profile_id: adapter_holder["adapter"],
        )
        qtbot.addWidget(window)
        created.append(window)
        return window

    yield make
    for window in created:
        window.shutdown()


def _segments(db_path: Path, document_id: int) -> list[Segment]:
    repo = SegmentRepository.open(db_path)
    try:
        return repo.list_segments_by_document(document_id)
    finally:
        repo.close()


def _wait_finished(qtbot: Any, worker: Any) -> None:
    """Wait for a worker's finished signal via a connected flag.

    Cross-thread ``qtbot.waitSignal`` can return before the worker's slot has
    run; waiting on a flag updated by a queued connection is reliable.
    """
    done = [False]

    def mark() -> None:
        done[0] = True

    worker.finished.connect(mark)
    qtbot.waitUntil(lambda: done[0], timeout=20000)


def _setup_profile(qtbot: Any, window: MainWindow) -> None:
    """Drive the Settings page to create a connection and a profile."""
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


def _setup_project_and_document(
    window: MainWindow,
    qtbot: Any,
    tmp_path: Path,
    content: str,
) -> int:
    """Create a project and import ``content``; returns the document id."""
    _setup_profile(qtbot, window)
    project = window._project
    translation = window._translation

    project._project_name.setText("Demo")
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)

    source = tmp_path / "source.txt"
    source.write_text(content, encoding="utf-8")
    project.import_file(source)
    qtbot.waitUntil(lambda: translation._document_id is not None, timeout=5000)
    assert translation._document_id is not None
    return translation._document_id


class TestFullFlow:
    """The whole desktop loop: settings, project, translation, export."""

    def test_settings_project_translate_export(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        holder: dict[str, Any] = {}
        window = window_factory(holder)
        document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha line.\nBeta line.\n",
        )

        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = SequenceAdapter([
            _valid_response(segments[0].stable_key, "甲"),
            _valid_response(segments[1].stable_key, "乙"),
        ])

        translation = window._translation
        qtbot.waitUntil(lambda: translation._profile_combo.count() == 1, timeout=5000)
        translation.translate()
        _wait_finished(qtbot, window._translation_worker)

        adapter = holder["adapter"]
        assert adapter.calls == 2, (
            f"adapter.calls={adapter.calls} status={translation._status.text()!r} "
            f"progress={translation._progress.value()}"
        )
        assert translation._progress.value() == 2
        assert translation._progress.maximum() == 2

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        target = out_dir / "translated.txt"
        translation.export_to(target)
        qtbot.waitUntil(lambda: "Export written" in translation._status.text(), timeout=5000)
        assert target.read_text(encoding="utf-8") == "甲\n乙\n"


class TestNonBlocking:
    """The main thread stays responsive while translation runs on a worker."""

    def test_main_thread_responsive_during_translation(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        holder: dict[str, Any] = {}
        window = window_factory(holder)
        document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\nBeta.\nGamma.\n",
        )
        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = SequenceAdapter(
            [_valid_response(segments[i].stable_key, f"T{i}") for i in range(len(segments))],
            delay=0.3,
        )

        translation = window._translation
        qtbot.waitUntil(lambda: translation._profile_combo.count() >= 1, timeout=5000)

        ticks = {"n": 0}

        def tick() -> None:
            ticks["n"] += 1

        timer = QTimer()
        timer.setInterval(150)
        timer.timeout.connect(tick)
        timer.start()
        try:
            translation.translate()
            # A main-thread QTimer firing while translation is still running
            # proves the event loop is not blocked by the worker.
            qtbot.waitUntil(lambda: ticks["n"] > 0, timeout=4000)
            assert translation._progress.value() < 3
            _wait_finished(qtbot, window._translation_worker)
        finally:
            timer.stop()

        assert ticks["n"] > 0
        assert translation._progress.value() == 3

    def test_cancel_stops_before_completion(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        holder: dict[str, Any] = {}
        window = window_factory(holder)
        document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\nBeta.\nGamma.\n",
        )
        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = SequenceAdapter(
            [_valid_response(segments[i].stable_key, f"T{i}") for i in range(len(segments))],
            delay=0.8,
        )

        translation = window._translation
        qtbot.waitUntil(lambda: translation._profile_combo.count() >= 1, timeout=5000)
        translation.translate()
        qtbot.waitUntil(lambda: translation._progress.value() >= 1, timeout=5000)
        translation._cancel.click()
        _wait_finished(qtbot, window._translation_worker)

        assert 1 <= translation._progress.value() < 3


class TestCloseConvergence:
    """Closing the window stops work and leaves a consistent, recoverable state."""

    def test_close_converges_without_processing_left(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        holder: dict[str, Any] = {}
        window = window_factory(holder)
        project = window._project
        document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\nBeta.\nGamma.\n",
        )
        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = SequenceAdapter(
            [_valid_response(segments[i].stable_key, f"T{i}") for i in range(len(segments))],
            delay=0.3,
        )

        translation = window._translation
        qtbot.waitUntil(lambda: translation._profile_combo.count() >= 1, timeout=5000)
        translation.translate()
        qtbot.waitUntil(lambda: translation._progress.value() >= 1, timeout=5000)

        window.close()

        db_path = tmp_path / "project.sqlite"
        state = _segments(db_path, document_id)
        assert all(segment.status in {"completed", "pending"} for segment in state)

        project_id = project._project_id
        assert project_id is not None
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            runs = service.list_runs_for_project(project_id)
            assert runs
            assert runs[-1].id is not None
            assert runs[-1].status == "cancelled"
            attempts = service.list_attempts_for_run(runs[-1].id)
            assert all(
                attempt.status in {"succeeded", "failed", "cancelled"}
                for attempt in attempts
            )

    def test_close_waits_for_slow_request_without_destroying_thread(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        holder: dict[str, Any] = {}
        window = window_factory(holder)
        document_id = _setup_project_and_document(window, qtbot, tmp_path, "Alpha.\n")
        segment = _segments(tmp_path / "project.sqlite", document_id)[0]
        holder["adapter"] = SequenceAdapter([_valid_response(segment.stable_key, "甲")], delay=5.5)

        translation = window._translation
        qtbot.waitUntil(lambda: translation._profile_combo.count() >= 1, timeout=5000)
        translation.translate()
        qtbot.waitUntil(lambda: holder["adapter"].calls == 1, timeout=5000)

        assert window.close() is False
        assert window._translation_thread.isRunning()
        _wait_finished(qtbot, window._translation_worker)
        assert window.close() is True
        qtbot.waitUntil(lambda: not window._translation_thread.isRunning(), timeout=5000)
