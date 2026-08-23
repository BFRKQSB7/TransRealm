"""Acceptance tests for V02-T04-M01 Auto overview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QGroupBox

from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.0.0-test"


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build isolated windows with an isolated language preference."""
    created: list[MainWindow] = []
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def make() -> MainWindow:
        window = MainWindow(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
            settings=settings,
        )
        qtbot.addWidget(window)
        created.append(window)
        return window

    yield make
    for window in created:
        window._i18n.set_language("en")
        window.shutdown()


class TestAutoOverview:
    def test_primary_journey_is_grouped_and_workbench_stays_hidden(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        translation = window._translation
        qtbot.waitUntil(lambda: translation._mode_label.text() == "Mode: auto", timeout=5000)

        overview = translation.findChild(QGroupBox, "auto-overview-section")
        assert overview is not None
        assert overview.title() == "Auto overview"
        assert translation._status.objectName() == "status-banner"
        assert translation._workbench_container.isHidden()
        assert not translation._translate.isHidden()
        assert not translation._cancel.isHidden()
        assert not translation._export.isHidden()
        assert not translation._progress.isHidden()

    def test_missing_profile_guidance_remains_recoverable_and_translates(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        translation = window._translation
        translation._on_config_missing(
            "This project has no active profile. Set one in the Project tab.",
        )

        assert not translation._config_missing_label.isHidden()
        assert not translation._set_active_profile.isHidden()
        assert not translation._workbench_container.isVisible()

        window._i18n.set_language("zh_CN")
        overview = translation.findChild(QGroupBox, "auto-overview-section")
        assert overview is not None
        assert overview.title() == "自动总览"
