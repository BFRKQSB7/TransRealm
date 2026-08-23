"""Acceptance tests for V02-T03-M01 Connection/Profile editing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt

from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.provider_connection_service import ProviderConnectionService
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


def _create_connection(qtbot: Any, window: MainWindow) -> int:
    settings = window._settings
    settings._conn_name.setText("local")
    settings._conn_endpoint.setText("http://localhost:8080/v1")
    settings._conn_credential.setText("env:TRANSREALM_TEST_KEY")
    settings._add_connection.click()
    qtbot.waitUntil(lambda: settings._connections_list.count() == 1, timeout=5000)
    item = settings._connections_list.item(0)
    assert item is not None
    connection_id = item.data(Qt.ItemDataRole.UserRole)
    assert isinstance(connection_id, int)
    return connection_id


def _create_profile(qtbot: Any, window: MainWindow) -> int:
    settings = window._settings
    qtbot.waitUntil(lambda: settings._profile_connection.count() == 1, timeout=5000)
    settings._profile_name.setText("general")
    settings._profile_model.setText("gpt-4o-mini")
    settings._add_profile.click()
    qtbot.waitUntil(lambda: settings._profiles_list.count() == 1, timeout=5000)
    item = settings._profiles_list.item(0)
    assert item is not None
    profile_id = item.data(Qt.ItemDataRole.UserRole)
    assert isinstance(profile_id, int)
    return profile_id


class TestConnectionEditing:
    def test_edit_persists_fields_and_reopens(self, qtbot: Any, window_factory: Any) -> None:
        window = window_factory()
        settings = window._settings
        connection_id = _create_connection(qtbot, window)

        settings._connections_list.setCurrentRow(0)
        settings._conn_name.setText("local-edited")
        settings._conn_endpoint.setText("https://localhost:9443/v1")
        settings._conn_credential.setText("wincred:transrealm/test-key")
        settings._conn_timeout.setValue(45)
        settings._conn_retries.setValue(3)
        settings._conn_retry_delay.setValue(1.5)
        settings._save_connection.click()
        _wait_status(qtbot, settings, "Connection updated")

        with ProviderConnectionService(
            settings._db_path,
            app_version=APP_VERSION,
        ) as service:
            saved = service.get_connection(connection_id)
            assert saved is not None
            assert saved.name == "local-edited"
            assert saved.endpoint == "https://localhost:9443/v1"
            assert saved.timeout_seconds == 45
            assert saved.max_retries == 3
            assert saved.retry_delay_seconds == 1.5
            assert saved.credential_reference == "wincred:transrealm/test-key"

        window.shutdown()
        reopened = window_factory()
        reopened_settings = reopened._settings
        qtbot.waitUntil(
            lambda: reopened_settings._connections_list.count() == 1,
            timeout=5000,
        )
        reopened_settings._connections_list.setCurrentRow(0)
        assert reopened_settings._conn_name.text() == "local-edited"
        assert reopened_settings._conn_endpoint.text() == "https://localhost:9443/v1"
        assert reopened_settings._conn_timeout.value() == 45
        assert reopened_settings._conn_retries.value() == 3
        assert reopened_settings._conn_retry_delay.value() == 1.5
        assert reopened_settings._conn_credential.text() == "wincred:transrealm/test-key"

    def test_invalid_edit_does_not_persist_or_leak_raw_credential(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        settings = window._settings
        connection_id = _create_connection(qtbot, window)
        settings._connections_list.setCurrentRow(0)

        settings._conn_endpoint.setText("not-a-url")
        settings._save_connection.click()
        qtbot.waitUntil(lambda: settings._status.text().startswith("Error:"), timeout=5000)
        with ProviderConnectionService(settings._db_path, app_version=APP_VERSION) as service:
            saved = service.get_connection(connection_id)
            assert saved is not None
            assert saved.endpoint == "http://localhost:8080/v1"

        raw_secret = "sk-live-should-never-appear"
        settings._conn_endpoint.setText("http://localhost:8080/v1")
        settings._conn_credential.setText(raw_secret)
        settings._save_connection.click()
        qtbot.waitUntil(lambda: settings._status.text().startswith("Error:"), timeout=5000)
        assert raw_secret not in settings._status.text()
        with ProviderConnectionService(settings._db_path, app_version=APP_VERSION) as service:
            saved = service.get_connection(connection_id)
            assert saved is not None
            assert saved.credential_reference == "env:TRANSREALM_TEST_KEY"


class TestProfileEditing:
    def test_invalid_context_budget_does_not_persist(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        settings = window._settings
        _create_connection(qtbot, window)
        profile_id = _create_profile(qtbot, window)
        settings._profiles_list.setCurrentRow(0)
        settings._profile_advanced_toggle.click()
        settings._profile_context_total.setValue(2048)
        settings._profile_reserved_output.setValue(2000)
        settings._profile_reserved_prompt.setValue(2000)
        settings._save_profile.click()
        qtbot.waitUntil(
            lambda: "must not exceed total" in settings._status.text(),
            timeout=5000,
        )

        with ModelProfileService(settings._db_path, app_version=APP_VERSION) as service:
            saved = service.get_profile(profile_id)
            assert saved is not None
            assert saved.context_budget == {
                "total": 8192,
                "reserved_output": 1024,
                "reserved_prompt": 1024,
            }

    def test_edit_advanced_fields_reopens_and_translates(
        self,
        qtbot: Any,
        window_factory: Any,
    ) -> None:
        window = window_factory()
        settings = window._settings
        _create_connection(qtbot, window)
        profile_id = _create_profile(qtbot, window)
        settings._profiles_list.setCurrentRow(0)

        assert settings._profile_advanced.isHidden()
        settings._profile_advanced_toggle.click()
        assert not settings._profile_advanced.isHidden()
        settings._profile_name.setText("general-edited")
        settings._profile_model.setText("gpt-4.1-mini")
        settings._profile_template_version.setText("2.0.0")
        settings._profile_output_protocol.setText("jsonl")
        settings._profile_context_total.setValue(16384)
        settings._profile_reserved_output.setValue(2048)
        settings._profile_reserved_prompt.setValue(2048)
        settings._profile_default_params.setText(
            '{"temperature": 0.7, "max_tokens": 2048}',
        )
        settings._profile_capability_context.setValue(16384)
        settings._profile_capability_output.setValue(4096)
        settings._profile_supports_streaming.setChecked(True)
        settings._profile_supports_structured.setChecked(True)
        settings._profile_supported_parameters.setText("temperature, top_p, max_tokens")
        settings._save_profile.click()
        _wait_status(qtbot, settings, "Profile updated")

        with ModelProfileService(settings._db_path, app_version=APP_VERSION) as service:
            saved = service.get_profile(profile_id)
            assert saved is not None
            assert saved.name == "general-edited"
            assert saved.model_id == "gpt-4.1-mini"
            assert saved.template_version == "2.0.0"
            assert saved.output_protocol == "jsonl"
            assert saved.context_budget == {
                "total": 16384,
                "reserved_output": 2048,
                "reserved_prompt": 2048,
            }
            assert saved.default_params == {"temperature": 0.7, "max_tokens": 2048}
            capability = saved.get_capability()
            assert capability.context_window == 16384
            assert capability.max_output_tokens == 4096
            assert capability.supports_streaming is True
            assert capability.supports_structured_output is True
            assert capability.supported_parameters == {
                "temperature",
                "top_p",
                "max_tokens",
            }

        window._settings._i18n.set_language("zh_CN")
        assert "编辑" in settings._edit_profile.text()
        assert "高级" in settings._profile_advanced_toggle.text()

        window.shutdown()
        reopened = window_factory()
        reopened_settings = reopened._settings
        qtbot.waitUntil(
            lambda: reopened_settings._profiles_list.count() == 1,
            timeout=5000,
        )
        reopened_settings._profiles_list.setCurrentRow(0)
        assert reopened_settings._profile_name.text() == "general-edited"
        assert reopened_settings._profile_model.text() == "gpt-4.1-mini"
        assert reopened_settings._profile_template_version.text() == "2.0.0"
        assert reopened_settings._profile_output_protocol.text() == "jsonl"
        assert reopened_settings._profile_context_total.value() == 16384
        assert reopened_settings._profile_default_params.text() == (
            '{"temperature": 0.7, "max_tokens": 2048}'
        )
