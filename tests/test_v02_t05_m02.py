"""Acceptance tests for V02-T05-M02 first-use guidance and safe GUI errors."""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings

from transrealm.application.translation_run_service import TranslationRunService
from transrealm.ui.main_window import MainWindow
from transrealm.ui.page_base import safe_error_message

APP_VERSION = "0.0.0-test"


class _LoopbackServer:
    """Small loopback-only OpenAI-compatible endpoint for the real GUI path."""

    def __init__(self, response: Callable[[], bytes]) -> None:
        self.records: list[dict[str, Any]] = []
        self._response = response
        self._httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            self._handler_type(),
        )
        self.port = int(self._httpd.server_address[1])
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def _handler_type(self) -> type[http.server.BaseHTTPRequestHandler]:
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                server.records.append(
                    {
                        "path": self.path,
                        "body": body.decode("utf-8", "replace"),
                        "headers": {key.lower(): value for key, value in self.headers.items()},
                    },
                )
                payload = server._response()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@contextmanager
def _loopback_server(response: Callable[[], bytes]) -> Generator[_LoopbackServer, None, None]:
    server = _LoopbackServer(response)
    try:
        yield server
    finally:
        server.close()


def _success_body(stable_key: str, translation: str) -> bytes:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return json.dumps(
        {
            "id": "m02-gui",
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                },
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build windows against an isolated database and language settings file."""
    created: list[MainWindow] = []
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("language", "en")
    settings.sync()

    def make() -> MainWindow:
        window = MainWindow(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
            settings=settings,
        )
        # Force a translator refresh so this fixture is isolated from earlier
        # Qt windows that may have installed a different language translator.
        window._i18n.set_language("zh_CN")
        window._i18n.set_language("en")
        qtbot.addWidget(window)
        created.append(window)
        return window

    yield make
    for window in created:
        window._i18n.set_language("en")
        window.shutdown()


def _wait_status(qtbot: Any, page: Any, text: str) -> None:
    qtbot.waitUntil(lambda: text in page._status.text(), timeout=5000)


def _create_project(qtbot: Any, window: MainWindow) -> None:
    project = window._project
    project._project_name.setText("m02-project")
    project._source_language.setText("en")
    project._target_language.setText("zh")
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)


class TestM02Guidance:
    def test_settings_explains_connection_and_model_profile(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        settings = window._settings
        qtbot.waitUntil(lambda: settings._setup_hint.text() != "", timeout=5000)

        assert "service" in settings._connection_help.text().lower()
        assert "model" in settings._profile_help.text().lower()
        assert "Connection" in settings._setup_hint.text(), (
            settings._setup_hint.text(),
            window._i18n.current_language,
            settings._language_combo.currentData(),
        )

        window._i18n.set_language("zh_CN")
        assert "服务" in settings._connection_help.text()
        assert "模型" in settings._profile_help.text()

    def test_project_missing_profile_points_to_settings(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        _create_project(qtbot, window)
        project = window._project
        qtbot.waitUntil(lambda: not project._open_settings.isHidden(), timeout=5000)
        assert "Model Profile" in project._profile_setup_hint.text()

        project._open_settings.click()
        qtbot.waitUntil(lambda: window._tabs.currentIndex() == 0, timeout=1000)

    def test_auto_mode_missing_profile_is_actionable(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _create_project(qtbot, window)
        source = tmp_path / "sample.txt"
        source.write_text("Hello world.\n", encoding="utf-8")
        window._project.import_file(source)
        qtbot.waitUntil(lambda: window._translation._document_id is not None, timeout=5000)
        qtbot.waitUntil(
            lambda: not window._translation._config_missing_label.isHidden(),
            timeout=5000,
        )

        assert not window._translation._configure_settings.isHidden()
        assert "Connection" in window._translation._config_missing_label.text()


class TestM02Errors:
    def test_duplicate_connection_is_actionable_and_redacted(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        settings = window._settings
        qtbot.waitUntil(lambda: settings._setup_hint.text() != "", timeout=5000)

        settings._conn_name.setText("local")
        settings._conn_endpoint.setText("http://127.0.0.1:1/v1")
        settings._add_connection.click()
        qtbot.waitUntil(lambda: settings._connections_list.count() == 1, timeout=5000)

        settings._conn_name.setText("local")
        settings._conn_endpoint.setText("http://127.0.0.1:2/v1")
        settings._add_connection.click()
        _wait_status(qtbot, settings, "already exists")
        message = settings._status.text()
        assert "UNIQUE" not in message
        assert "SQL" not in message
        assert "project.sqlite" not in message
        assert "C:\\" not in message
        assert settings._connections_list.count() == 1

    def test_generic_error_removes_path_sql_and_keeps_safe_fallback(self) -> None:
        raw = (
            "Integrity constraint (path: C:\\Users\\sample\\.transrealm\\project.sqlite); "
            "SQL: INSERT INTO provider_connections VALUES (?)"
        )
        safe = safe_error_message(raw)
        assert "project.sqlite" not in safe
        assert "C:\\" not in safe
        assert "SQL:" not in safe
        assert safe
        assert "operation could not be completed" in safe_error_message("")


class TestM02GuiJourney:
    def test_real_gui_http_create_import_translate_export_reopen(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        stable_key = ""

        def response() -> bytes:
            return _success_body(stable_key, "你好")

        with _loopback_server(response) as server:
            window = window_factory()
            _create_project(qtbot, window)
            source = tmp_path / "journey.txt"
            source.write_text("Hello world.\n", encoding="utf-8")
            window._project.import_file(source)
            qtbot.waitUntil(lambda: window._translation._document_id is not None, timeout=5000)

            settings = window._settings
            settings._conn_name.setText("loopback")
            settings._conn_endpoint.setText(server.base_url)
            settings._add_connection.click()
            qtbot.waitUntil(lambda: settings._connections_list.count() == 1, timeout=5000)
            settings._profile_name.setText("local-model")
            settings._profile_model.setText("synthetic-model")
            settings._add_profile.click()
            qtbot.waitUntil(lambda: settings._profiles_list.count() == 1, timeout=5000)

            project = window._project
            project.refresh()
            qtbot.waitUntil(lambda: project._active_profile_combo.count() == 1, timeout=5000)
            project._active_profile_combo.setCurrentIndex(0)
            project._set_active.click()
            qtbot.waitUntil(
                lambda: project._active_profile_label.text().startswith("Active:"),
                timeout=5000,
            )
            qtbot.waitUntil(
                lambda: window._translation._active_profile_id is not None,
                timeout=5000,
            )

            with TranslationRunService(
                tmp_path / "project.sqlite",
                app_version=APP_VERSION,
            ) as runs:
                progress = runs.list_segment_progress(
                    source_document_id=window._translation._document_id,
                )
            stable_key = progress[0].stable_key if progress else ""
            window._translation.translate()
            qtbot.waitUntil(lambda: len(server.records) == 1, timeout=5000)
            qtbot.waitUntil(lambda: not window._translation._running, timeout=5000)
            assert "Translation finished" in window._translation._status.text(), (
                window._translation._status.text()
            )
            assert server.records[0]["path"] == "/v1/chat/completions"

            target = tmp_path / "translated.txt"
            window._translation.export_to(target)
            qtbot.waitUntil(
                lambda: "Export written" in window._translation._status.text(),
                timeout=5000,
            )
            assert target.read_text(encoding="utf-8") == "你好\n"

            window.shutdown()
            reopened = window_factory()
            qtbot.waitUntil(lambda: reopened._project._project_combo.count() == 1, timeout=5000)
            qtbot.waitUntil(
                lambda: reopened._translation._active_profile_id is not None,
                timeout=5000,
            )
            assert reopened._translation._document_id is not None
