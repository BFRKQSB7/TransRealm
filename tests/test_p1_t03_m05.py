"""P1-T03-M05: mode switching and the GUI Gate.

M05 ships the last P1-T03 GUI surface: an interaction-mode selector that
persists ``projects.mode`` through the worker and refuses to change mode while a
translation is running (the running run keeps its Profile/Workflow/parameters —
the user must finish or Cancel first), plus a per-project document selector so
switching projects never leaks a stale document id and imported documents stay
reachable after a window restart. The Gate verifies that cancel works in
workbench mode, that closing the window converges and leaves a recoverable
state, and that mode / active profile / document / translation results and
locks all survive a window restart.

Service-level test: the new ``list_source_documents`` read surface. pytest-qt
tests cover mode switching, the running-guard, workbench cancel, close
convergence, restart persistence, project-switch document reset, and the
workbench missing-active-profile guidance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.application.import_service import ImportService
from transrealm.application.project_service import ProjectService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.project import MODE_AUTO, MODE_WORKBENCH
from transrealm.domain.segment import Segment
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.1.0"


# --------------------------------------------------------------------------- #
# Service-level: document read surface for the document selector
# --------------------------------------------------------------------------- #


def test_list_source_documents_returns_project_documents(tmp_path: Path) -> None:
    db = tmp_path / "project.db"
    with ProjectService(db, app_version=APP_VERSION) as svc:
        project_a = svc.create_project(name="A", source_language="ja", target_language="zh")
        project_b = svc.create_project(name="B", source_language="ja", target_language="zh")
        assert project_a.id is not None and project_b.id is not None
        a_id, b_id = project_a.id, project_b.id

    source_a = tmp_path / "a.txt"
    source_a.write_text("Alpha.\n", encoding="utf-8")
    source_b = tmp_path / "b.txt"
    source_b.write_text("Beta.\n", encoding="utf-8")
    with ImportService(db, app_version=APP_VERSION) as importer:
        importer.import_txt(a_id, source_a, name="a.txt")
        importer.import_txt(a_id, source_b, name="b.txt")
        importer.import_txt(b_id, source_a, name="a.txt")

    with TranslationRunService(db, app_version=APP_VERSION) as runs:
        assert [doc.name for doc in runs.list_source_documents(project_id=a_id)] == [
            "a.txt",
            "b.txt",
        ]
        assert [doc.name for doc in runs.list_source_documents(project_id=b_id)] == ["a.txt"]
        assert runs.list_source_documents(project_id=9999) == []


# --------------------------------------------------------------------------- #
# pytest-qt: mode switching, running guard, cancel, close, restart
# --------------------------------------------------------------------------- #


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
        import asyncio

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
        request_id="req-m05",
        raw_response=None,
    )


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build MainWindows against a shared database path and per-window adapters."""
    created: list[MainWindow] = []

    def make(db_path: Path | None = None) -> tuple[MainWindow, dict[str, Any]]:
        holder: dict[str, Any] = {}
        window = MainWindow(
            db_path or (tmp_path / "project.sqlite"),
            app_version=APP_VERSION,
            adapter_factory=lambda profile_id: holder["adapter"],
        )
        qtbot.addWidget(window)
        created.append(window)
        return window, holder

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
    done = [False]

    def mark() -> None:
        done[0] = True

    worker.finished.connect(mark)
    qtbot.waitUntil(lambda: done[0], timeout=20000)


def _setup_profile(qtbot: Any, window: MainWindow) -> None:
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
    *,
    set_active: bool = True,
) -> tuple[int, int]:
    """Create a project (+ optional active profile) and import ``content``."""
    _setup_profile(qtbot, window)
    project = window._project
    translation = window._translation

    project._project_name.setText("Demo")
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
    assert project._project_id is not None
    project_id = project._project_id

    if set_active:
        qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
        project._active_profile_combo.setCurrentIndex(
            project._active_profile_combo.findData(
                project._active_profile_combo.itemData(0),
            ),
        )
        project._set_active.click()
        qtbot.waitUntil(
            lambda: "Active:" in project._active_profile_label.text(),
            timeout=5000,
        )

    source = tmp_path / "source.txt"
    source.write_text(content, encoding="utf-8")
    project.import_file(source)
    qtbot.waitUntil(lambda: translation._document_id is not None, timeout=5000)
    assert translation._document_id is not None
    return project_id, translation._document_id


def _switch_mode(qtbot: Any, translation: Any, mode: str) -> None:
    """Drive the mode selector through the worker and wait for persistence.

    Waits on the mode label (which reflects the persisted ``projects.mode``
    after a refresh) rather than the transient status message, because the
    refresh that follows a successful switch can overwrite the status (e.g. the
    workbench missing-config guidance).
    """
    index = translation._mode_switch.findData(mode)
    assert index >= 0
    translation._on_mode_switch(index)
    qtbot.waitUntil(
        lambda: f"Mode: {mode}" in translation._mode_label.text(),
        timeout=5000,
    )


class TestModeSwitching:
    """The interaction-mode selector persists and toggles the workbench surface."""

    def test_mode_switch_persists_and_toggles_workbench_surface(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _ = window_factory()
        _setup_project_and_document(window, qtbot, tmp_path, "Alpha.\nBeta.\n")
        translation = window._translation
        qtbot.waitUntil(lambda: "Mode: auto" in translation._mode_label.text(), timeout=5000)

        _switch_mode(qtbot, translation, MODE_WORKBENCH)
        assert translation._mode == MODE_WORKBENCH
        assert "Mode: workbench" in translation._mode_label.text()
        assert translation._mode_switch.currentData() == MODE_WORKBENCH
        assert not translation._workbench_container.isHidden()

        _switch_mode(qtbot, translation, MODE_AUTO)
        assert translation._mode == MODE_AUTO
        assert "Mode: auto" in translation._mode_label.text()
        assert translation._workbench_container.isHidden()

    def test_mode_switch_refused_while_running(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        _, document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\nBeta.\nGamma.\n",
        )
        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = SequenceAdapter(
            [_valid_response(segments[i].stable_key, f"T{i}") for i in range(len(segments))],
            delay=0.5,
        )
        translation = window._translation

        translation.translate()
        qtbot.waitUntil(lambda: translation._running, timeout=5000)

        # Attempting to switch modes mid-run is refused with a hint and the
        # selector is restored: the running run keeps its strategy in place.
        translation._on_mode_switch(1)
        assert "running" in translation._status.text()
        assert translation._mode == MODE_AUTO
        assert "Mode: auto" in translation._mode_label.text()
        assert translation._mode_switch.currentData() == MODE_AUTO

        translation._on_cancel()
        _wait_finished(qtbot, window._translation_worker)
        assert not translation._running

        # After the run ends the same switch is allowed.
        _switch_mode(qtbot, translation, MODE_WORKBENCH)
        assert translation._mode == MODE_WORKBENCH

    def test_workbench_mode_without_active_profile_shows_guidance(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        project_id, _ = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\n",
            set_active=False,
        )
        holder["adapter"] = SequenceAdapter([])
        translation = window._translation

        _switch_mode(qtbot, translation, MODE_WORKBENCH)
        assert not translation._config_missing_label.isHidden()
        assert not translation._set_active_profile.isHidden()

        # In workbench mode the missing active profile short-circuits on the
        # main thread (no worker round trip), so no run is created and the
        # adapter is never called.
        translation.translate()
        assert not translation._config_missing_label.isHidden()
        assert holder["adapter"].calls == 0
        with TranslationRunService(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
        ) as svc:
            assert svc.list_runs_for_project(project_id) == []


    def test_mode_switch_without_project_reports_error(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _ = window_factory()
        translation = window._translation
        assert translation._mode_switch.currentData() == MODE_AUTO

        # With no project the mode selector is restored to the default and a
        # clear error is reported instead of a phantom switch.
        translation._on_mode_switch(1)
        assert "project" in translation._status.text().lower()
        assert translation._mode_switch.currentData() == MODE_AUTO

    def test_document_switch_refused_while_running(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        project_id, document_id1 = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\nBeta.\n",
        )
        # Import a second document so there is something to switch to.
        source2 = tmp_path / "second.txt"
        source2.write_text("Gamma.\nDelta.\n", encoding="utf-8")
        window._project.import_file(source2)
        qtbot.waitUntil(
            lambda: window._translation._document_combo.count() == 2,
            timeout=5000,
        )
        translation = window._translation
        assert translation._document_id is not None
        document2_id = translation._document_id
        assert document2_id != document_id1

        # Make document1 current through the selector.
        translation._document_combo.setCurrentIndex(
            translation._document_combo.findData(document_id1),
        )
        translation._on_document_selected(translation._document_combo.currentIndex())
        qtbot.waitUntil(lambda: translation._document_id == document_id1, timeout=5000)

        segments = _segments(tmp_path / "project.sqlite", document_id1)
        holder["adapter"] = SequenceAdapter(
            [_valid_response(segments[i].stable_key, f"T{i}") for i in range(len(segments))],
            delay=0.5,
        )
        translation.translate()
        qtbot.waitUntil(lambda: translation._running, timeout=5000)

        # The selector is locked while running and a switch attempt is rejected.
        assert not translation._document_combo.isEnabled()
        translation._on_document_selected(
            translation._document_combo.findData(document2_id),
        )
        assert translation._document_id == document_id1
        assert "running" in translation._status.text()

        translation._on_cancel()
        _wait_finished(qtbot, window._translation_worker)

        # After the run the selector is usable again.
        assert translation._document_combo.isEnabled()


class TestCancelAndClose:
    """Cancel and window close converge in workbench mode like in auto mode."""

    def test_workbench_translate_cancel_stops_before_completion(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        project_id, document_id = _setup_project_and_document(
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
        _switch_mode(qtbot, translation, MODE_WORKBENCH)

        translation.translate()
        qtbot.waitUntil(lambda: translation._progress.value() >= 1, timeout=5000)
        translation._on_cancel()
        _wait_finished(qtbot, window._translation_worker)

        assert 1 <= translation._progress.value() < 3
        with TranslationRunService(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
        ) as svc:
            runs = svc.list_runs_for_project(project_id)
            assert runs and runs[-1].status == "cancelled"

    def test_close_during_workbench_converges(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        project_id, document_id = _setup_project_and_document(
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
        _switch_mode(qtbot, translation, MODE_WORKBENCH)

        translation.translate()
        qtbot.waitUntil(lambda: translation._progress.value() >= 1, timeout=5000)

        window.close()

        db_path = tmp_path / "project.sqlite"
        state = _segments(db_path, document_id)
        assert all(segment.status in {"completed", "pending"} for segment in state)
        with TranslationRunService(db_path, app_version=APP_VERSION) as svc:
            runs = svc.list_runs_for_project(project_id)
            assert runs and runs[-1].status == "cancelled"
            assert runs[-1].id is not None
            attempts = svc.list_attempts_for_run(runs[-1].id)
            assert all(
                attempt.status in {"succeeded", "failed", "cancelled"}
                for attempt in attempts
            )


class TestRestartPersistence:
    """Mode, active profile, documents, results and locks survive a restart."""

    def test_restart_preserves_mode_active_document_results_and_lock(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "project.sqlite"

        window1, holder = window_factory(db_path)
        project_id, document_id = _setup_project_and_document(
            window1,
            qtbot,
            tmp_path,
            "Alpha.\nBeta.\n",
        )
        translation = window1._translation
        _switch_mode(qtbot, translation, MODE_WORKBENCH)

        segments = _segments(db_path, document_id)
        holder["adapter"] = SequenceAdapter([
            _valid_response(segments[0].stable_key, "甲"),
            _valid_response(segments[1].stable_key, "乙"),
        ])
        translation.translate()
        _wait_finished(qtbot, window1._translation_worker)
        assert translation._progress.value() == 2

        # Manually revise segment 0 and lock it.
        translation._segment_progress.setCurrentRow(0)
        qtbot.waitUntil(lambda: translation._revision_editor is not None, timeout=5000)
        translation._revision_editor._editor.setPlainText("手译A")
        translation._revision_editor._save.click()
        qtbot.waitUntil(
            lambda: "Manual translation saved." in translation._status.text(),
            timeout=5000,
        )
        qtbot.waitUntil(
            lambda: (
                translation._revision_editor is not None
                and translation._revision_editor._lock.isEnabled()
            ),
            timeout=5000,
        )
        translation._revision_editor._lock.click()
        qtbot.waitUntil(
            lambda: "Current translation locked." in translation._status.text(),
            timeout=5000,
        )

        window1.shutdown()

        # A fresh window against the same database keeps everything.
        window2, _ = window_factory(db_path)
        window2._project.select_project(project_id)
        translation2 = window2._translation
        qtbot.waitUntil(
            lambda: "Mode: workbench" in translation2._mode_label.text(),
            timeout=5000,
        )
        qtbot.waitUntil(
            lambda: "Active profile:" in translation2._active_profile_label.text(),
            timeout=5000,
        )
        qtbot.waitUntil(lambda: translation2._document_combo.count() == 1, timeout=5000)
        # The selector is populated after restart but no document is
        # auto-selected; choosing it loads the persisted progress.
        translation2._document_combo.setCurrentIndex(0)
        translation2._on_document_selected(0)
        qtbot.waitUntil(lambda: translation2._document_id == document_id, timeout=5000)
        qtbot.waitUntil(
            lambda: translation2._segment_progress.count() == 2,
            timeout=5000,
        )

        translation2._segment_progress.setCurrentRow(0)
        qtbot.waitUntil(lambda: translation2._revision_editor is not None, timeout=5000)
        assert translation2._revision_editor._editor.toPlainText() == "手译A"
        assert translation2._revision_editor._unlock.isEnabled()
        assert not translation2._revision_editor._lock.isEnabled()


class TestProjectSwitch:
    """Switching projects resets the document context instead of leaking it."""

    def test_project_switch_resets_document_context(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _ = window_factory()
        project = window._project
        translation = window._translation

        # Project A with an imported document.
        project._project_name.setText("A")
        project._create_project.click()
        qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
        assert project._project_id is not None
        project_a = project._project_id

        source = tmp_path / "a.txt"
        source.write_text("Alpha.\nBeta.\n", encoding="utf-8")
        project.import_file(source)
        qtbot.waitUntil(lambda: translation._document_id is not None, timeout=5000)
        document_a = translation._document_id
        assert document_a is not None

        # Project B has no documents: the translation page must not keep A's id.
        project._project_name.setText("B")
        project._create_project.click()
        qtbot.waitUntil(lambda: project._project_id == project_a + 1, timeout=5000)
        qtbot.waitUntil(lambda: translation._document_combo.count() == 0, timeout=5000)
        assert translation._document_id is None
        assert "Select a project document." in translation._status.text()

        # Switching back to A repopulates the selector with A's document, but no
        # document is auto-selected (no stale id is guessed); choosing it from
        # the selector loads its progress.
        project.select_project(project_a)
        qtbot.waitUntil(lambda: translation._document_combo.count() == 1, timeout=5000)
        assert translation._document_id is None
        translation._document_combo.setCurrentIndex(0)
        translation._on_document_selected(0)
        qtbot.waitUntil(lambda: translation._document_id == document_a, timeout=5000)
        assert translation._document_name == "a.txt"
