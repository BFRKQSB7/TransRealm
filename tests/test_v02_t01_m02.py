"""M02 acceptance for the desktop shell, navigation, and light theme."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QScrollArea, QTabWidget

from transrealm.ui.main_window import MainShell, MainWindow
from transrealm.ui.theme import LIGHT_TOKENS, build_stylesheet


def test_main_window_exposes_hierarchical_shell_and_navigation(
    qtbot: object,
    tmp_path: Path,
) -> None:
    window = MainWindow(tmp_path / "project.sqlite", app_version="0.0.0-test")
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    try:
        tabs = window.findChild(QTabWidget, "main-tabs")
        title = window.findChild(QLabel, "app-title")

        assert tabs is not None
        assert title is not None
        assert title.text() == "TransRealm"
        assert tabs.count() == 3
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            "Settings",
            "Project",
            "Translation",
        ]
        assert tabs.documentMode()
        assert all(isinstance(tabs.widget(i), QScrollArea) for i in range(tabs.count()))
        for index in range(tabs.count()):
            scroll = tabs.widget(index)
            assert isinstance(scroll, QScrollArea)
            expected_surface = QColor(LIGHT_TOKENS["surface"])
            assert scroll.viewport().palette().color(
                scroll.viewport().backgroundRole(),
            ) == expected_surface
            assert scroll.widget() is not None
            assert scroll.widget().palette().color(
                scroll.widget().backgroundRole(),
            ) == expected_surface
        assert window.minimumWidth() >= 960
        assert window.minimumHeight() >= 600
    finally:
        window.shutdown()


def test_light_theme_has_shared_tokens_and_interaction_states() -> None:
    stylesheet = build_stylesheet()

    assert LIGHT_TOKENS["window"] in stylesheet
    assert LIGHT_TOKENS["accent"] in stylesheet
    assert LIGHT_TOKENS["on_accent"] in stylesheet
    for selector in (
        "QPushButton:hover",
        "QPushButton:disabled",
        "QLineEdit:focus",
        "QTabBar::tab:selected",
    ):
        assert selector in stylesheet


def test_project_setup_signal_navigates_to_project_tab(
    qtbot: object,
    tmp_path: Path,
) -> None:
    window = MainWindow(tmp_path / "project.sqlite", app_version="0.0.0-test")
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    try:
        tabs = window.findChild(QTabWidget, "main-tabs")
        assert tabs is not None
        tabs.setCurrentIndex(0)

        window._translation.request_project_setup.emit()

        assert tabs.currentIndex() == 1
        shell = window.centralWidget()
        assert isinstance(shell, MainShell)
        assert shell.count() == 3
        assert [shell.tabText(i) for i in range(shell.count())] == [
            "Settings",
            "Project",
            "Translation",
        ]
        assert shell.currentWidget() is tabs.widget(1)
    finally:
        window.shutdown()
