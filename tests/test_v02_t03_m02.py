"""Acceptance tests for V02-T03-M02 Settings grouping and feedback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QGroupBox

from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.0.0-test"


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build and clean up MainWindow instances against one test database."""
    created: list[MainWindow] = []

    def make() -> MainWindow:
        window = MainWindow(tmp_path / "project.sqlite", app_version=APP_VERSION)
        qtbot.addWidget(window)
        created.append(window)
        return window

    yield make
    for window in created:
        window._settings._i18n.set_language("en")
        window.shutdown()


def _wait_status(qtbot: Any, settings: Any, text: str) -> None:
    qtbot.waitUntil(lambda: text in settings._status.text(), timeout=5000)


def _create_connection(qtbot: Any, window: MainWindow) -> None:
    settings = window._settings
    settings._conn_name.setText("local")
    settings._conn_endpoint.setText("http://localhost:8080/v1")
    settings._conn_credential.setText("env:TRANSREALM_M02_MISSING")
    settings._add_connection.click()
    qtbot.waitUntil(lambda: settings._connections_list.count() == 1, timeout=5000)


def _create_profile(qtbot: Any, window: MainWindow) -> None:
    settings = window._settings
    qtbot.waitUntil(lambda: settings._profile_connection.count() == 1, timeout=5000)
    settings._profile_name.setText("general")
    settings._profile_model.setText("gpt-4o-mini")
    settings._add_profile.click()
    qtbot.waitUntil(lambda: settings._profiles_list.count() == 1, timeout=5000)


class TestSettingsGroupingAndFeedback:
    def test_sections_and_feedback_keep_next_action_visible(
        self,
        qtbot: Any,
        window_factory: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("TRANSREALM_M02_MISSING", raising=False)
        window = window_factory()
        settings = window._settings
        connections_section = settings.findChild(QGroupBox, "connections-section")
        profiles_section = settings.findChild(QGroupBox, "profiles-section")
        assert connections_section is not None
        assert profiles_section is not None
        assert connections_section.title() == "Connections"
        assert profiles_section.title() == "Profiles"
        assert settings._status.objectName() == "status-banner"

        _create_connection(qtbot, window)
        _wait_status(qtbot, settings, "Connection added")
        qtbot.waitUntil(
            lambda: "Set the environment variable" in settings._credential_status.text(),
            timeout=5000,
        )
        assert "TRANSREALM_M02_MISSING" in settings._credential_status.text()

        _create_profile(qtbot, window)
        _wait_status(qtbot, settings, "Profile added")
        settings._connections_list.setCurrentRow(0)
        settings._delete_connection.click()
        _wait_status(qtbot, settings, "Delete or repoint those profiles first")
        assert settings._connections_list.count() == 1
        assert settings._profiles_list.count() == 1

        settings._profiles_list.setCurrentRow(0)
        settings._delete_profile.click()
        _wait_status(qtbot, settings, "Profile deleted")
        qtbot.waitUntil(lambda: settings._profiles_list.count() == 0, timeout=5000)

        settings._connections_list.setCurrentRow(0)
        settings._delete_connection.click()
        _wait_status(qtbot, settings, "Connection deleted")
        qtbot.waitUntil(lambda: settings._connections_list.count() == 0, timeout=5000)

        settings._i18n.set_language("zh_CN")
        assert connections_section.title() == "连接"
        assert profiles_section.title() == "配置"
