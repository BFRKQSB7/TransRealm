"""V02-T04-M03: Revision history/current and controlled retry controls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox, QListWidget, QPushButton

from transrealm.application.import_service import ImportService
from transrealm.application.project_service import ProjectService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.workbench import SegmentProgress
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.2.0-test"


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


def _create_project_and_segment(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as projects:
        project = projects.create_project(
            name="Revision project",
            source_language="en",
            target_language="zh",
        )
        assert project.id is not None
        project_id = project.id
    source = path.parent / "source.txt"
    source.write_text("Hello\n", encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as importer:
        _document, segments = importer.import_txt(project_id, source, name="source.txt")
    assert segments[0].id is not None
    return segments[0].id


def _revision(revision_id: int, segment_id: int, text: str) -> TranslationRevision:
    return TranslationRevision(
        id=revision_id,
        segment_id=segment_id,
        text=text,
        origin="ai" if revision_id == 1 else "user",
        attempt_id=None,
        is_locked=False,
        created_at=None,
    )


def test_run_service_lists_all_revisions_without_mutating_current(tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    segment_id = _create_project_and_segment(db_path)
    with TranslationRunService(db_path, app_version=APP_VERSION) as runs:
        first = runs.append_user_revision(segment_id=segment_id, text="一")
        second = runs.append_user_revision(segment_id=segment_id, text="二")
        assert first.id is not None
        assert second.id is not None
        history = runs.list_revisions_for_segment(segment_id=segment_id)
        assert [revision.text for revision in history] == ["一", "二"]
        first_revision = runs.get_revision(first.id)
        second_revision = runs.get_revision(second.id)
        assert first_revision is not None
        assert second_revision is not None
        assert first_revision.text == "一"
        assert second_revision.text == "二"


class TestRevisionHistoryControls:
    def test_history_and_retry_controls_use_selected_segment(
        self,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        translation = window._translation
        translation._populate_workbench(
            None,
            [
                SegmentProgress(
                    1,
                    "seg-1",
                    "Alpha",
                    "completed",
                    2,
                    "succeeded",
                    None,
                    "二",
                ),
                SegmentProgress(
                    2,
                    "seg-2",
                    "Beta",
                    "failed",
                    None,
                    "failed",
                    "timeout",
                ),
            ],
        )

        history = translation.findChild(QListWidget, "revision-history")
        use_revision = translation.findChild(QPushButton, "use-selected-revision")
        retry = translation.findChild(QPushButton, "retry-failed-segment")
        status_filter = translation.findChild(QComboBox, "workbench-status-filter")
        assert history is not None
        assert use_revision is not None
        assert retry is not None
        assert status_filter is not None

        translation._segment_progress.setCurrentRow(0)
        revisions = [_revision(1, 1, "一"), _revision(2, 1, "二")]
        translation._handle_action("load_revision_history", (1, revisions))
        assert history.count() == 2
        history.setCurrentRow(0)
        assert use_revision.isEnabled()
        assert history.currentItem().data(0x0100) == 1
        assert not retry.isEnabled()

        translation._segment_progress.setCurrentRow(1)
        assert retry.isEnabled()
        assert not use_revision.isEnabled()
