"""V02-T04-M02: Workbench segment list filtering and readable details."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox

from transrealm.application.workbench import SegmentProgress
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


def _progress_items() -> list[SegmentProgress]:
    return [
        SegmentProgress(
            segment_id=1,
            stable_key="seg-1",
            source_text="Alpha",
            status="pending",
            current_revision_id=None,
            attempt_status=None,
            attempt_error=None,
        ),
        SegmentProgress(
            segment_id=2,
            stable_key="seg-2",
            source_text="Beta",
            status="completed",
            current_revision_id=7,
            attempt_status="succeeded",
            attempt_error=None,
            revision_text="贝塔",
        ),
        SegmentProgress(
            segment_id=3,
            stable_key="seg-3",
            source_text="Gamma",
            status="failed",
            current_revision_id=None,
            attempt_status="failed",
            attempt_error="timeout",
        ),
    ]


class TestWorkbenchListFilter:
    def test_status_filter_preserves_selection_and_restores_all(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        translation = window._translation
        translation._populate_workbench(None, _progress_items())

        status_filter = translation.findChild(QComboBox, "workbench-status-filter")
        assert status_filter is not None
        assert translation._segment_progress.count() == 3
        assert translation._revision_editor is None
        assert "No segment selected." in translation._segment_detail.text()

        translation._segment_progress.setCurrentRow(1)
        assert translation._segment_detail.objectName() == "segment-detail"
        assert "Beta" in translation._segment_detail.text()
        assert "贝塔" in translation._segment_detail.text()

        status_filter.setCurrentIndex(status_filter.findData("completed"))
        qtbot.waitUntil(lambda: translation._segment_progress.count() == 1, timeout=2000)
        assert translation._segment_progress.currentItem().text().startswith("seg-2")
        assert "Beta" in translation._segment_detail.text()
        assert translation._revision_editor is not None

        status_filter.setCurrentIndex(status_filter.findData("all"))
        qtbot.waitUntil(lambda: translation._segment_progress.count() == 3, timeout=2000)
        assert translation._segment_progress.currentRow() == 1
        assert "贝塔" in translation._segment_detail.text()

    def test_filter_and_details_retranslate_to_chinese(
        self,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        translation = window._translation
        translation._populate_workbench(None, _progress_items())
        translation._segment_progress.setCurrentRow(1)

        status_filter = translation.findChild(QComboBox, "workbench-status-filter")
        assert status_filter is not None
        window._i18n.set_language("zh_CN")

        assert status_filter.itemText(0) == "全部状态"
        assert status_filter.itemText(status_filter.findData("completed")) == "已完成"
        assert "源文" in translation._segment_detail.text() or "当前译文" in (
            translation._segment_detail.text()
        )
