"""UI regressions for readable navigation, fresh results and manual drafts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractButton, QMessageBox

from test_t04_workspace import VERSION, Endpoint, model, window
from transrealm.application.translation_facade import TranslationFacade


def prepare(qtbot: Any, tmp_path: Path, endpoint: Endpoint) -> Any:
    db = tmp_path / "workspace.sqlite"
    profile = model(db, endpoint)
    source = tmp_path / "Chapter 01.txt"
    source.write_text("First paragraph.\n\nSecond paragraph.\n", encoding="utf-8")
    with TranslationFacade(db, app_version=VERSION) as facade:
        job = facade.create_job(
            name="A quiet workspace", source_language="en", target_language="zh"
        )
        assert job.id is not None
        facade.select_active_profile(job.id, profile)
        facade.import_document(job.id, source)
    app = window(qtbot, tmp_path)
    qtbot.waitUntil(lambda: len(app._translation._workbench_progress) == 2)
    return app


def test_fresh_ai_results_and_drafts_survive_segment_document_and_page_navigation(
    qtbot: Any, tmp_path: Path
) -> None:
    endpoint = Endpoint()
    app = prepare(qtbot, tmp_path, endpoint)
    page = app._translation
    try:
        # A pristine empty editor must show the result, rather than preserve
        # its previous empty text as a spurious draft after a run.
        page._translate.click()
        qtbot.waitUntil(lambda: not page._running and len(endpoint.requests) == 2)
        qtbot.waitUntil(lambda: page._workbench_progress[0].status == "completed")
        assert page._revision_editor.translation() == "测试译文"
        assert not page._revision_editor.is_dirty()
        page._revision_editor._editor.setPlainText("First draft")
        page._segment_progress.setCurrentRow(1)
        page._revision_editor._editor.setPlainText("Second draft")
        page._segment_progress.setCurrentRow(0)
        assert page._revision_editor.translation() == "First draft"
        original_document = page._document_id

        other = tmp_path / "Chapter 02.txt"
        other.write_text("Third paragraph.\n", encoding="utf-8")
        page._job_controls.import_file(other)
        qtbot.waitUntil(lambda: page._document_id != original_document)
        qtbot.waitUntil(lambda: len(page._workbench_progress) == 1)
        index = page._document_combo.findData(original_document)
        page._document_combo.setCurrentIndex(index)
        page._on_document_selected(index)
        qtbot.waitUntil(lambda: len(page._workbench_progress) == 2)
        assert page._revision_editor.translation() == "First draft"
        app._nav_buttons[1].click()
        app._nav_buttons[0].click()
        qtbot.waitUntil(lambda: not page._pending_requests)
        assert page._revision_editor.translation() == "First draft"

        output = tmp_path / "edited.txt"
        page.export_to(output)
        assert "before exporting" in page._status.text()
        assert not output.exists()
        page._revision_editor._save.click()
        qtbot.waitUntil(lambda: page._workbench_progress[0].revision_text == "First draft")
        page._segment_progress.setCurrentRow(1)
        assert page._revision_editor.translation() == "Second draft"
        page._revision_editor._save.click()
        qtbot.waitUntil(lambda: page._workbench_progress[1].revision_text == "Second draft")
        assert not page._has_unsaved_edits()
        page.export_to(output)
        qtbot.waitUntil(output.exists)
        assert output.read_text(encoding="utf-8") == "First draft\n\nSecond draft\n"
        assert len(endpoint.requests) == 2
    finally:
        app.shutdown()
        endpoint.close()


def test_provider_creation_advances_to_models_and_navigation_is_synchronized(
    qtbot: Any, tmp_path: Path
) -> None:
    app = window(qtbot, tmp_path)
    try:
        app._nav_buttons[1].click()
        providers = app._providers
        providers._conn_name.setText("Local")
        providers._conn_endpoint.setText("http://127.0.0.1:9876/v1")
        providers._add_connection.click()
        qtbot.waitUntil(lambda: providers._profile_connection.count() == 1)
        assert providers._sections.currentIndex() == 1
        assert app._page_title.text() == "Providers"
        assert [button.isChecked() for button in app._nav_buttons] == [False, True, False]
        app._i18n.set_language("zh_CN")
        assert app._page_title.text() == "模型提供商"
        assert app._nav_buttons[0].text() == "翻译"
        app._tabs.setCurrentIndex(0)
        assert app._page_title.text() == "翻译"
        assert app._translation._progress.maximum() == 1
        assert app._translation._progress.value() == 0
        assert not app._translation._translate.isEnabled()
    finally:
        app.shutdown()


def test_close_with_unsaved_translation_keeps_window_and_workers_alive(
    qtbot: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint = Endpoint()
    app = prepare(qtbot, tmp_path, endpoint)
    try:
        app.show()
        app._translation._revision_editor._editor.setPlainText("Keep this draft")
        monkeypatch.setattr(
            QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel
        )
        assert not app.close()
        assert app._service_thread.isRunning()
        assert app._translation._revision_editor.translation() == "Keep this draft"
    finally:
        app.shutdown()
        endpoint.close()


@pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "windows"
    or not os.environ.get("TRANSREALM_GUI_EVIDENCE"),
    reason="Native Windows visual evidence requires a project-local output directory.",
)
def test_native_populated_workspace_and_three_pages(qtbot: Any, tmp_path: Path) -> None:
    endpoint = Endpoint()
    app = prepare(qtbot, tmp_path, endpoint)
    folder = Path(os.environ["TRANSREALM_GUI_EVIDENCE"])
    folder.mkdir(parents=True, exist_ok=True)
    try:
        app.show()
        qtbot.waitExposed(app)
        for language in ("en", "zh_CN"):
            app._i18n.set_language(language)
            for index in range(3):
                app._tabs.setCurrentIndex(index)
                page = (app._translation, app._providers, app._prompts)[index]
                qtbot.waitUntil(lambda: not page._pending_requests)
                qtbot.wait(100)
                assert app.grab().save(str(folder / f"page-{index}-{language}.png"))
                for button in app.findChildren(QAbstractButton):
                    if button.isVisible() and button.text():
                        text_width = button.fontMetrics().horizontalAdvance(button.text())
                        assert button.width() >= text_width
            app._tabs.setCurrentIndex(0)
            app.resize(960, 600)
            qtbot.wait(100)
            assert app.grab().save(str(folder / f"small-{language}.png"))
            save = app._translation._revision_editor._save
            assert save.mapTo(app, save.rect().bottomRight()).y() < app.height()
            app.resize(1180, 720)
        screen = QGuiApplication.primaryScreen()
        assert screen is not None
        (folder / "platform.json").write_text(
            json.dumps({"platform": QGuiApplication.platformName(),
                        "screen": [screen.size().width(), screen.size().height()],
                        "scale": app.devicePixelRatioF()}, indent=2), encoding="utf-8"
        )
    finally:
        app.shutdown()
        endpoint.close()
