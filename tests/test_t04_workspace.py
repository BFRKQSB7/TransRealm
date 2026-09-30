"""Unified workspace acceptance through the real HTTP adapter and worker threads."""

from __future__ import annotations

import http.server
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDropEvent, QGuiApplication
from PySide6.QtWidgets import QAbstractButton

from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_facade import TranslationFacade
from transrealm.domain.model_profile import ModelCapability
from transrealm.ui.main_window import MainWindow
from transrealm.ui.page_base import WorkerPage
from transrealm.ui.worker import ServiceWorker

VERSION = "0.2.0-test"


class Endpoint:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail_once = False
        self.db: Path | None = None
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                owner.entered.set()
                if owner.block:
                    owner.release.wait(5)
                status = 503 if owner.fail_once else 200
                owner.fail_once = False
                prompt = body["messages"][0]["content"]
                content = "测试译文"
                if "Return only a JSON object" in prompt:
                    current = prompt.split("Current segment:\n", 1)[1].split("\n\nContext:", 1)[0]
                    assert owner.db is not None
                    with TranslationFacade(owner.db, app_version=VERSION) as facade:
                        segments = [
                            segment
                            for job in facade.list_jobs()
                            if job.id is not None
                            for document in facade.list_documents(job.id)
                            if document.id is not None
                            for segment in facade.list_segments(document.id)
                        ]
                    key = next(
                        segment.stable_key for segment in segments if segment.source_text == current
                    )
                    content = json.dumps({"items": [{"segment_id": key, "translation": content}]})
                payload = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": content},
                                "finish_reason": "stop",
                            }
                        ]
                    }
                    if status == 200
                    else {"error": {"message": "temporary failure"}}
                ).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def endpoint() -> Iterator[Endpoint]:
    server = Endpoint()
    try:
        yield server
    finally:
        server.close()


def model(db: Path, endpoint: Endpoint) -> int:
    endpoint.db = db
    with ProviderConnectionService(db, app_version=VERSION) as providers:
        provider = providers.create_connection(
            name="Loopback",
            provider_type="openai-compatible",
            endpoint=f"http://127.0.0.1:{endpoint.server.server_port}/v1",
            timeout_seconds=5,
            max_retries=0,
            retry_delay_seconds=0,
        )
    assert provider.id is not None
    with ModelProfileService(db, app_version=VERSION) as models:
        profile = models.create_profile(
            name="Model",
            provider_connection_id=provider.id,
            model_id="controlled",
            template_version="1.0.0",
            output_protocol="text",
            capability=ModelCapability(8192, 1024, False, False, {"max_tokens"}),
            context_budget={"total": 8192, "reserved_output": 1024, "reserved_prompt": 512},
            default_params={"max_tokens": 1024},
        )
    assert profile.id is not None
    return profile.id


def window(qtbot: Any, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "language.ini"), QSettings.Format.IniFormat)
    settings.setValue("language", "en")
    result = MainWindow(tmp_path / "workspace.sqlite", app_version=VERSION, settings=settings)
    qtbot.addWidget(result)
    result._i18n.set_language("en")
    return result


def test_two_file_stop_reopen_resume_edit_lock_notes_export(
    qtbot: Any,
    tmp_path: Path,
    endpoint: Endpoint,
) -> None:
    db = tmp_path / "workspace.sqlite"
    profile_id = model(db, endpoint)
    source = tmp_path / "first.txt"
    source.write_bytes(b"First.\r\n\r\nSecond.\r\n")
    second = tmp_path / "second.json"
    second.write_bytes(b'{"label":"Other file","number":3}')
    first = window(qtbot, tmp_path)
    reopened: MainWindow | None = None
    try:
        page = first._translation
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source)), QUrl.fromLocalFile(str(second))])
        page.dropEvent(
            QDropEvent(
                QPointF(20, 20),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        qtbot.waitUntil(lambda: page._document_combo.count() == 2)
        assert first._project.parent() is not None
        assert page._project_id is not None
        page._provider_combo.setCurrentIndex(0)
        page._on_provider_selected(0)
        qtbot.waitUntil(lambda: page._active_profile_id == profile_id)
        page._document_combo.setCurrentIndex(page._document_combo.findText("first.txt"))
        page._on_document_selected(page._document_combo.currentIndex())
        qtbot.waitUntil(lambda: page._segment_progress.count() == 2)
        first._project._notes.setPlainText("Use formal language.")
        first._project._save_notes.click()
        qtbot.waitUntil(lambda: "Notes saved" in first._project._notes_status.text())
        first._project._gloss_source.setText("First")
        first._project._gloss_target.setText("第一")
        first._project._gloss_locked.setChecked(True)
        first._project._add_glossary.click()
        qtbot.waitUntil(lambda: first._project._glossary_list.count() == 1)
        endpoint.block = True
        page.translate()
        qtbot.waitUntil(endpoint.entered.is_set)
        assert not page._job_controls.isEnabled()
        page._cancel.click()
        endpoint.release.set()
        qtbot.waitUntil(lambda: not page._running)
        assert "stopped" in page._status.text()
        assert len(endpoint.requests) == 1
        assert "Use formal language." in json.dumps(endpoint.requests[0])
        with TranslationFacade(db, app_version=VERSION) as facade:
            run_id = facade.runs(page._project_id)[0].id
            assert run_id is not None and page._document_id is not None
            first_segment_id = facade.list_segments(page._document_id)[0].id
            assert first_segment_id is not None
            assert len(facade.attempts(run_id)) == 1
            assert len(facade.revisions(first_segment_id)) == 1
        job_id, document_id = page._project_id, page._document_id
        first.shutdown()
        reopened = window(qtbot, tmp_path)
        page = reopened._translation
        qtbot.waitUntil(lambda: page._document_combo.count() == 2)
        page._document_combo.setCurrentIndex(page._document_combo.findData(document_id))
        page._on_document_selected(page._document_combo.currentIndex())
        qtbot.waitUntil(lambda: page._active_profile_id == profile_id)
        endpoint.block = False
        page.translate()
        qtbot.waitUntil(lambda: len(endpoint.requests) == 2)
        qtbot.waitUntil(lambda: not page._running)
        qtbot.waitUntil(lambda: len(page._workbench_progress) == 2)
        page._segment_progress.setCurrentRow(0)
        qtbot.waitUntil(lambda: page._revision_editor is not None)
        assert page._revision_editor is not None
        page._revision_editor._editor.setPlainText("手工译文")
        page._revision_editor._save.click()
        qtbot.waitUntil(lambda: "Manual translation saved" in page._status.text())
        qtbot.waitUntil(
            lambda: page._revision_editor is not None and page._revision_editor._lock.isEnabled()
        )
        page._revision_editor._lock.click()
        qtbot.waitUntil(lambda: "locked" in page._status.text())
        qtbot.waitUntil(
            lambda: page._revision_editor is not None and page._revision_editor._unlock.isEnabled()
        )
        assert not page._retranslate.isEnabled()
        out = tmp_path / "translated.txt"
        page.export_to(out)
        qtbot.waitUntil(lambda: "Export written" in page._status.text())
        assert out.read_bytes() == "手工译文\r\n\r\n测试译文\r\n".encode()
        with TranslationFacade(db, app_version=VERSION) as facade:
            assert facade.notes(job_id) == "Use formal language."
            assert facade.glossary(job_id)[0].target_term == "第一"
    finally:
        endpoint.release.set()
        first.shutdown()
        if reopened is not None:
            reopened.shutdown()


def test_failed_retry_and_single_segment_only(
    qtbot: Any, tmp_path: Path, endpoint: Endpoint
) -> None:
    db = tmp_path / "workspace.sqlite"
    profile_id = model(db, endpoint)
    with TranslationFacade(db, app_version=VERSION) as facade:
        job = facade.create_job(name="Retry", source_language="en", target_language="zh")
        assert job.id is not None
        facade.select_active_profile(job.id, profile_id)
    source = tmp_path / "retry.txt"
    source.write_text("First.\nSecond.\n", encoding="utf-8")
    app = window(qtbot, tmp_path)
    try:
        page = app._translation
        qtbot.waitUntil(lambda: page._project_id is not None)
        page.import_file(source)
        qtbot.waitUntil(lambda: page._segment_progress.count() == 2)
        endpoint.fail_once = True
        page.translate()
        qtbot.waitUntil(lambda: len(endpoint.requests) == 2)
        qtbot.waitUntil(lambda: not page._running)
        assert "finished" not in page._status.text()
        qtbot.waitUntil(lambda: page._workbench_progress[0].status == "failed")
        assert "HTTP 503" in page._status.text()
        page._segment_progress.setCurrentRow(0)
        page._retry_failed.click()
        qtbot.waitUntil(lambda: page._workbench_progress[0].status == "pending")
        page.translate()
        qtbot.waitUntil(lambda: len(endpoint.requests) == 3)
        qtbot.waitUntil(lambda: not page._running)
        qtbot.waitUntil(lambda: page._workbench_progress[0].status == "completed")
        page._segment_progress.setCurrentRow(1)
        page._retranslate.click()
        qtbot.waitUntil(lambda: len(endpoint.requests) == 4)
        qtbot.waitUntil(lambda: not page._running)
        with TranslationFacade(db, app_version=VERSION) as facade:
            assert page._document_id is not None
            segments = facade.list_segments(page._document_id)
            first_id, second_id = segments[0].id, segments[1].id
            assert first_id is not None and second_id is not None
            assert len(facade.revisions(first_id)) == 1
            assert len(facade.revisions(second_id)) == 2
    finally:
        app.shutdown()


def test_worker_page_keeps_mutation_result_when_read_is_submitted(qtbot: Any) -> None:
    class Page(WorkerPage):
        def __init__(self) -> None:
            super().__init__(ServiceWorker())
            self.results: list[str] = []

        def _handle_action(self, action: str, result: object) -> None:
            self.results.append(action)

        def _handle_error(self, error: str) -> None:
            raise AssertionError(error)

    page = Page()
    qtbot.addWidget(page)
    page._pending_requests = {"mutation": "save_revision", "read": "refresh"}
    page._latest_reads = {"refresh": "read"}
    page._on_task_done("mutation", None)
    page._on_task_done("read", None)
    assert page.results == ["save_revision", "refresh"]


def test_six_formats_import_translate_and_fidelity_export_through_workspace(
    qtbot: Any,
    tmp_path: Path,
    endpoint: Endpoint,
) -> None:
    db = tmp_path / "workspace.sqlite"
    profile_id = model(db, endpoint)
    events = (
        "[Script Info]\nTitle: Subtitle\nScriptType: v4.00+\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hello\n"
    )
    contents = {
        "txt": "Hello\r\n",
        "json": '{"label":"Hello","count":7,"enabled":true}',
        "srt": "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        "vtt": "WEBVTT\n\ncue-one\n00:00:00.000 --> 00:00:01.000\nHello\n\n",
        "ass": events,
        "ssa": events.replace("v4.00+", "v4.00")
        .replace("Layer", "Marked")
        .replace("Dialogue: 0,", "Dialogue: Marked=0,"),
    }
    sources = []
    for extension, content in contents.items():
        path = tmp_path / f"字幕 資料.{extension}"
        path.write_bytes(content.encode("utf-8"))
        sources.append(path)
    app = window(qtbot, tmp_path)
    try:
        if os.environ.get("QT_QPA_PLATFORM") == "windows":
            app.show()
            qtbot.waitExposed(app)
        page = app._translation
        page._job_controls.import_files(sources)
        qtbot.waitUntil(lambda: page._document_combo.count() == 6)
        qtbot.waitUntil(lambda: page._models != [])
        page._model_combo.setCurrentIndex(page._model_combo.findData(profile_id))
        page._on_model_selected(0)
        qtbot.waitUntil(lambda: page._active_profile_id == profile_id)
        for index, source in enumerate(sources):
            page._document_combo.setCurrentIndex(index)
            page._on_document_selected(index)
            qtbot.waitUntil(lambda: page._document_name == source.name)
            qtbot.waitUntil(lambda: bool(page._workbench_progress))
            page._translate.click()
            qtbot.waitUntil(lambda: len(endpoint.requests) == index + 1)
            qtbot.waitUntil(lambda: not page._running)
            qtbot.waitUntil(lambda: page._workbench_progress[0].status == "completed")
            target = tmp_path / f"export-{source.name}"
            page.export_to(target)
            qtbot.waitUntil(target.exists)
            assert target.read_bytes() == source.read_bytes().replace(
                b"Hello", "测试译文".encode()
            )
        assert all("response_format" not in request for request in endpoint.requests)
        assert all(
            "Return only the translation" in request["messages"][0]["content"]
            for request in endpoint.requests
        )
    finally:
        app.shutdown()


@pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "windows",
    reason="Actual Windows GUI evidence runs separately with the native Qt platform.",
)
def test_native_windows_workspace_visuals(qtbot: Any, tmp_path: Path, endpoint: Endpoint) -> None:
    evidence = Path(os.environ["TRANSREALM_GUI_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    app = window(qtbot, tmp_path)
    try:
        app.show()
        qtbot.waitExposed(app)
        assert QGuiApplication.platformName() == "windows"
        for language in ("en", "zh_CN"):
            app._i18n.set_language(language)
            qtbot.wait(100)
            assert app.grab().save(str(evidence / f"translation-empty-{language}.png"))
            for button in app._translation.findChildren(QAbstractButton):
                if button.isVisible() and button.text():
                    assert button.width() >= button.fontMetrics().horizontalAdvance(button.text())
            app._translation._on_config_missing("Choose a Provider and model before translating.")
            assert not app._translation._translate.isEnabled()
            assert app.grab().save(str(evidence / f"translation-guidance-{language}.png"))
        (evidence / "platform.json").write_text(
            json.dumps(
                {
                    "platform": QGuiApplication.platformName(),
                    "scale": os.environ.get("QT_SCALE_FACTOR", "1"),
                    "size": [app.width(), app.height()],
                    "screen": app.screen().geometry().getRect(),
                }
            ),
            encoding="utf-8",
        )
    finally:
        app.shutdown()
