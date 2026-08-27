"""V02-T04-M04: recovery, lock persistence and final workbench continuity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings

from transrealm.application.import_service import ImportService
from transrealm.application.project_service import ProjectService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.workbench import SegmentProgress
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.2.0-test"


def _create_project_and_segment(path: Path) -> tuple[int, int]:
    with ProjectService(path, app_version=APP_VERSION) as projects:
        project = projects.create_project(
            name="Recovery project",
            source_language="en",
            target_language="zh",
        )
        assert project.id is not None
        project_id = project.id
    source = path.parent / "recovery.txt"
    source.write_text("Hello\n", encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as importer:
        document, segments = importer.import_txt(project_id, source, name="recovery.txt")
    assert document.id is not None
    assert segments[0].id is not None
    return document.id, segments[0].id


def test_current_revision_and_lock_survive_service_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    document_id, segment_id = _create_project_and_segment(db_path)

    with TranslationRunService(db_path, app_version=APP_VERSION) as runs:
        first = runs.append_user_revision(segment_id=segment_id, text="一")
        second = runs.append_user_revision(segment_id=segment_id, text="二")
        assert first.id is not None
        assert second.id is not None
        runs.set_current_revision(segment_id=segment_id, revision_id=first.id)
        locked = runs.lock_current_revision(segment_id=segment_id)
        assert locked.id == first.id
        assert locked.is_locked

    with TranslationRunService(db_path, app_version=APP_VERSION) as reopened:
        history = reopened.list_revisions_for_segment(segment_id=segment_id)
        progress = reopened.list_segment_progress(source_document_id=document_id)

    assert [revision.text for revision in history] == ["一", "二"]
    assert len(progress) == 1
    assert progress[0].current_revision_id == first.id
    assert progress[0].revision_text == "一"
    assert progress[0].revision_locked


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    created: list[MainWindow] = []

    def make() -> MainWindow:
        settings = QSettings(
            str(tmp_path / "settings.ini"),
            QSettings.Format.IniFormat,
        )
        window = MainWindow(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
            adapter_factory=lambda _profile_id: None,  # type: ignore[arg-type, return-value]
            settings=settings,
        )
        qtbot.addWidget(window)
        window._i18n.set_language("en")
        created.append(window)
        return window

    yield make
    for window in created:
        window.shutdown()


def test_refresh_preserves_locked_editor_and_unsaved_draft(window_factory: Any) -> None:
    window = window_factory()
    translation = window._translation
    locked_segment = SegmentProgress(
        1,
        "seg-1",
        "Alpha source",
        "completed",
        2,
        "succeeded",
        None,
        "一",
        True,
    )

    translation._populate_workbench(None, [locked_segment])
    translation._segment_progress.setCurrentRow(0)
    assert translation._revision_editor is not None
    translation._revision_editor._editor.setPlainText("未保存草稿")

    translation._populate_workbench(None, [locked_segment])

    assert translation._revision_editor is not None
    assert translation._revision_editor.translation() == "未保存草稿"
    assert translation._revision_editor._unlock.isEnabled()
    assert not translation._revision_editor._lock.isEnabled()
