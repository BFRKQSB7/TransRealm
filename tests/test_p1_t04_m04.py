"""Tests for P1-T04-M04: the thin management UI.

The Settings page manages provider connections and model profiles (including
deletion with actionable in-use errors and credential-availability hints); the
Project page manages the project list, the active Profile selection and the
project-scoped Glossary (lock/priority/scope). Every Application Service call
goes through the worker thread, so the UI never queries the database directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt

from transrealm.application.glossary_service import GlossaryService
from transrealm.application.project_service import ProjectService
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.0.0-test"


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build a MainWindow against a fresh database in a temp directory."""
    created: list[MainWindow] = []

    def make() -> MainWindow:
        window = MainWindow(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
        )
        qtbot.addWidget(window)
        created.append(window)
        return window

    yield make
    for window in created:
        window.shutdown()


def _setup_connection(
    qtbot: Any,
    window: MainWindow,
    *,
    name: str = "local",
    endpoint: str = "http://localhost:8080/v1",
    credential: str | None = None,
) -> None:
    settings = window._settings
    settings._conn_name.setText(name)
    settings._conn_endpoint.setText(endpoint)
    if credential is not None:
        settings._conn_credential.setText(credential)
    settings._add_connection.click()
    qtbot.waitUntil(
        lambda: settings._connections_list.count() >= 1,
        timeout=5000,
    )


def _setup_profile(qtbot: Any, window: MainWindow, *, name: str = "general") -> None:
    settings = window._settings
    qtbot.waitUntil(lambda: settings._profile_connection.count() >= 1, timeout=5000)
    settings._profile_name.setText(name)
    settings._profile_model.setText("gpt-4o-mini")
    settings._add_profile.click()
    qtbot.waitUntil(lambda: settings._profiles_list.count() >= 1, timeout=5000)


def _create_project(qtbot: Any, window: MainWindow, *, name: str = "Demo") -> None:
    project = window._project
    project._project_name.setText(name)
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
    qtbot.waitUntil(lambda: project._project_combo.count() >= 1, timeout=5000)


def _profile_ids(window: MainWindow) -> list[int]:
    settings = window._settings
    ids: list[int] = []
    for index in range(settings._profiles_list.count()):
        item = settings._profiles_list.item(index)
        assert item is not None
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        assert isinstance(profile_id, int)
        ids.append(profile_id)
    return ids


class TestActiveProfileSelection:
    """The Project page sets and clears the active ModelProfile."""

    def test_set_and_clear_active_profile(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _setup_connection(qtbot, window)
        _setup_profile(qtbot, window, name="general")
        _create_project(qtbot, window)

        project = window._project
        qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
        profile_id = _profile_ids(window)[0]

        project._active_profile_combo.setCurrentIndex(
            project._active_profile_combo.findData(profile_id),
        )
        project._set_active.click()
        qtbot.waitUntil(
            lambda: "Active profile set" in project._status.text(),
            timeout=5000,
        )
        qtbot.waitUntil(
            lambda: "general" in project._active_profile_label.text(),
            timeout=5000,
        )

        db_path = tmp_path / "project.sqlite"
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            project_entity = service.open_project()
            assert project_entity is not None
            assert project_entity.active_profile_id == profile_id

        project._clear_active.click()
        qtbot.waitUntil(
            lambda: "Active profile cleared" in project._status.text(),
            timeout=5000,
        )
        qtbot.waitUntil(
            lambda: "Active profile: none" in project._active_profile_label.text(),
            timeout=5000,
        )

        with ProjectService(db_path, app_version=APP_VERSION) as service:
            project_entity = service.open_project()
            assert project_entity is not None
            assert project_entity.active_profile_id is None

    def test_active_profile_defaults_to_selected_when_reopened(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _setup_connection(qtbot, window)
        _setup_profile(qtbot, window, name="general")
        _create_project(qtbot, window)

        project = window._project
        qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
        profile_id = _profile_ids(window)[0]
        project._active_profile_combo.setCurrentIndex(
            project._active_profile_combo.findData(profile_id),
        )
        project._set_active.click()
        qtbot.waitUntil(
            lambda: "Active profile set" in project._status.text(),
            timeout=5000,
        )

        # A reopened window reflects the persisted selection for the project.
        window2 = window_factory()
        project2 = window2._project
        qtbot.waitUntil(lambda: project2._project_combo.count() >= 1, timeout=5000)
        assert project._project_id is not None
        project2.select_project(project._project_id)
        qtbot.waitUntil(
            lambda: "general" in project2._active_profile_label.text(),
            timeout=5000,
        )


class TestGlossaryManagement:
    """The Project page manages Glossary lock/priority/scope."""

    def test_add_update_lock_delete_entry(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _create_project(qtbot, window)
        project = window._project
        assert project._project_id is not None
        project_id: int = project._project_id

        project._gloss_source.setText("Apple")
        project._gloss_target.setText("苹果")
        project._gloss_scope.setText("noun")
        project._gloss_priority.setValue(90)
        project._gloss_locked.setChecked(True)
        project._add_glossary.click()
        qtbot.waitUntil(lambda: project._glossary_list.count() == 1, timeout=5000)

        db_path = tmp_path / "project.sqlite"
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            entries = service.list_entries(project_id)
            assert len(entries) == 1
            assert entries[0].source_term == "Apple"
            assert entries[0].target_term == "苹果"
            assert entries[0].scope == "noun"
            assert entries[0].priority == 90
            assert entries[0].is_locked is True
            entry_id = entries[0].id
            assert entry_id is not None

        # Selecting the row repopulates the form.
        project._glossary_list.setCurrentRow(0)
        assert project._gloss_source.text() == "Apple"
        assert project._gloss_target.text() == "苹果"
        assert project._gloss_scope.text() == "noun"
        assert project._gloss_priority.value() == 90
        assert project._gloss_locked.isChecked() is True

        project._gloss_target.setText("苹果（修正）")
        project._gloss_scope.setText("proper-noun")
        project._gloss_priority.setValue(10)
        project._gloss_locked.setChecked(False)
        project._update_glossary.click()
        qtbot.waitUntil(
            lambda: "Updated glossary entry" in project._status.text(),
            timeout=5000,
        )

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            updated = service.get_entry(entry_id)
            assert updated is not None
            assert updated.target_term == "苹果（修正）"
            assert updated.scope == "proper-noun"
            assert updated.priority == 10
            assert updated.is_locked is False

        project._delete_glossary.click()
        # The update refreshed the list, so re-select the entry before deleting.
        project._glossary_list.setCurrentRow(0)
        project._delete_glossary.click()
        qtbot.waitUntil(
            lambda: "Glossary entry deleted" in project._status.text(),
            timeout=5000,
        )
        qtbot.waitUntil(lambda: project._glossary_list.count() == 0, timeout=5000)
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            assert service.list_entries(project_id) == []

    def test_duplicate_source_term_is_actionable_and_non_polluting(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _create_project(qtbot, window)
        project = window._project
        assert project._project_id is not None
        project_id: int = project._project_id

        project._gloss_source.setText("Apple")
        project._gloss_target.setText("苹果")
        project._gloss_scope.setText("noun")
        project._add_glossary.click()
        qtbot.waitUntil(lambda: project._glossary_list.count() == 1, timeout=5000)

        project._gloss_source.setText("Apple")
        project._gloss_target.setText("另一译文")
        project._add_glossary.click()
        qtbot.waitUntil(
            lambda: "already exists" in project._status.text(),
            timeout=5000,
        )
        qtbot.waitUntil(lambda: project._glossary_list.count() == 1, timeout=5000)

        db_path = tmp_path / "project.sqlite"
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            entries = service.list_entries(project_id)
            assert len(entries) == 1
            assert entries[0].target_term == "苹果"

    def test_empty_source_term_shows_validation_error(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _create_project(qtbot, window)
        project = window._project
        project._gloss_source.setText("   ")
        project._gloss_target.setText("苹果")
        project._gloss_scope.setText("noun")
        project._add_glossary.click()
        qtbot.waitUntil(
            lambda: "source_term is required" in project._status.text(),
            timeout=5000,
        )
        assert project._glossary_list.count() == 0

    def test_only_locked_entries_are_reported_locked(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _create_project(qtbot, window)
        project = window._project
        assert project._project_id is not None
        project_id: int = project._project_id

        project._gloss_source.setText("LockedTerm")
        project._gloss_target.setText("锁定词")
        project._gloss_scope.setText("noun")
        project._gloss_priority.setValue(80)
        project._gloss_locked.setChecked(True)
        project._add_glossary.click()
        qtbot.waitUntil(lambda: project._glossary_list.count() == 1, timeout=5000)

        project._gloss_source.setText("FreeTerm")
        project._gloss_target.setText("自由词")
        project._gloss_scope.setText("noun")
        project._gloss_priority.setValue(80)
        project._gloss_locked.setChecked(False)
        project._add_glossary.click()
        qtbot.waitUntil(lambda: project._glossary_list.count() == 2, timeout=5000)

        db_path = tmp_path / "project.sqlite"
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            locked = service.list_locked_entries(project_id)
            assert [entry.source_term for entry in locked] == ["LockedTerm"]
            unlocked = service.list_entries(project_id)
            assert {entry.source_term for entry in unlocked} == {
                "LockedTerm",
                "FreeTerm",
            }


class TestActionableDeletes:
    """Referenced deletions surface actionable errors; free ones succeed."""

    def test_delete_profile_blocked_when_active_project(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _setup_connection(qtbot, window)
        _setup_profile(qtbot, window, name="general")
        _create_project(qtbot, window)

        project = window._project
        qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
        profile_id = _profile_ids(window)[0]
        project._active_profile_combo.setCurrentIndex(
            project._active_profile_combo.findData(profile_id),
        )
        project._set_active.click()
        qtbot.waitUntil(
            lambda: "Active profile set" in project._status.text(),
            timeout=5000,
        )

        settings = window._settings
        settings._profiles_list.setCurrentRow(0)
        settings._delete_profile.click()
        qtbot.waitUntil(
            lambda: "active profile" in settings._status.text(),
            timeout=5000,
        )
        assert settings._profiles_list.count() == 1

        # Clearing the active profile releases the deletion guard.
        project._clear_active.click()
        qtbot.waitUntil(
            lambda: "Active profile cleared" in project._status.text(),
            timeout=5000,
        )
        settings._profiles_list.setCurrentRow(0)
        settings._delete_profile.click()
        qtbot.waitUntil(lambda: settings._profiles_list.count() == 0, timeout=5000)

    def test_delete_connection_blocked_when_referenced_by_profile(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _setup_connection(qtbot, window)
        _setup_profile(qtbot, window, name="bound")

        settings = window._settings
        settings._connections_list.setCurrentRow(0)
        settings._delete_connection.click()
        qtbot.waitUntil(
            lambda: "referenced by" in settings._status.text(),
            timeout=5000,
        )
        assert settings._connections_list.count() == 1
        assert "bound" in settings._status.text()

    def test_delete_unreferenced_connection_and_profile(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _setup_connection(qtbot, window, name="spare")
        settings = window._settings

        # The connection itself is unreferenced and can be deleted.
        settings._connections_list.setCurrentRow(0)
        settings._delete_connection.click()
        qtbot.waitUntil(lambda: settings._connections_list.count() == 0, timeout=5000)

        # A profile without project/attempt references can be deleted too.
        _setup_connection(qtbot, window, name="host")
        _setup_profile(qtbot, window, name="free")
        settings._profiles_list.setCurrentRow(0)
        settings._delete_profile.click()
        qtbot.waitUntil(lambda: settings._profiles_list.count() == 0, timeout=5000)


class TestConnectionDeleteGuard:
    """P1-T04-M04 ADAPT: connection deletion gives an actionable in-use error."""

    def test_referenced_connection_delete_raises_with_profile_names(
        self,
        tmp_path: Path,
    ) -> None:
        from transrealm.application.model_profile_service import ModelProfileService
        from transrealm.application.provider_connection_service import (
            ProviderConnectionService,
        )
        from transrealm.domain.provider_connection import ProviderConnectionInUseError

        db = tmp_path / "project.sqlite"
        with ProviderConnectionService(db, app_version=APP_VERSION) as connections:
            connection = connections.create_connection(
                name="host",
                provider_type="openai-compatible",
                endpoint="https://api.example.com/v1",
            )
            assert connection.id is not None
            connection_id: int = connection.id
            with ModelProfileService(db, app_version=APP_VERSION) as profiles:
                profiles.create_profile(
                    name="bound",
                    provider_connection_id=connection_id,
                    model_id="x",
                    template_version="1.0",
                    output_protocol="json",
                )
            with pytest.raises(ProviderConnectionInUseError) as exc_info:
                connections.delete_connection(connection_id)
            assert "bound" in str(exc_info.value)
            assert connections.get_connection(connection_id) is not None

    def test_unreferenced_connection_delete_still_succeeds(self, tmp_path: Path) -> None:
        from transrealm.application.provider_connection_service import (
            ProviderConnectionService,
        )

        db = tmp_path / "project.sqlite"
        with ProviderConnectionService(db, app_version=APP_VERSION) as connections:
            connection = connections.create_connection(
                name="spare",
                provider_type="openai-compatible",
                endpoint="https://api.example.com/v1",
            )
            assert connection.id is not None
            assert connections.delete_connection(connection.id) is True
            assert connections.delete_connection(connection.id) is False


class TestCredentialHints:
    """Missing credentials surface an actionable hint, never a secret."""

    def test_missing_env_credential_shows_actionable_hint(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        monkeypatch.delenv("TRANSREALM_MISSING_TEST", raising=False)
        window = window_factory()
        _setup_connection(
            qtbot,
            window,
            name="remote",
            endpoint="https://api.example.com/v1",
            credential="env:TRANSREALM_MISSING_TEST",
        )
        settings = window._settings
        qtbot.waitUntil(
            lambda: "Missing credentials" in settings._credential_status.text(),
            timeout=5000,
        )
        assert "TRANSREALM_MISSING_TEST" in settings._credential_status.text()
        assert "Set the environment variable" in settings._credential_status.text()

    def test_available_or_absent_credential_shows_no_warning(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        monkeypatch.setenv("TRANSREALM_PRESENT_TEST", "some-secret-value")
        window = window_factory()
        _setup_connection(
            qtbot,
            window,
            name="present",
            endpoint="https://api.example.com/v1",
            credential="env:TRANSREALM_PRESENT_TEST",
        )
        _setup_connection(
            qtbot,
            window,
            name="no-credential",
            endpoint="https://api.example.com/v1",
        )
        settings = window._settings
        qtbot.waitUntil(
            lambda: settings._connections_list.count() == 2,
            timeout=5000,
        )
        # The secret value never appears; an available reference shows no warning.
        assert "some-secret-value" not in settings._credential_status.text()
        assert settings._credential_status.text() == ""


class TestSettingsSelectionPreserved:
    """A mid-form connection choice survives a Settings refresh (Review MINOR)."""

    def test_add_profile_connection_selection_survives_refresh(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window = window_factory()
        _setup_connection(qtbot, window, name="host-a")
        _setup_connection(qtbot, window, name="host-b")
        settings = window._settings
        qtbot.waitUntil(
            lambda: settings._profile_connection.findText("host-b") >= 0,
            timeout=5000,
        )

        index_b = settings._profile_connection.findText("host-b")
        settings._profile_connection.setCurrentIndex(index_b)
        assert settings._profile_connection.currentText() == "host-b"

        settings.refresh()
        qtbot.waitUntil(
            lambda: settings._connections_list.count() == 2,
            timeout=5000,
        )
        assert settings._profile_connection.currentText() == "host-b"


class TestThinUiBoundary:
    """The UI layers never reach into the database directly."""

    def test_ui_modules_do_not_import_repositories(self) -> None:
        import inspect

        import transrealm.ui.main_window
        import transrealm.ui.pages

        for module in (transrealm.ui.main_window, transrealm.ui.pages):
            source = inspect.getsource(module)
            assert "infrastructure.repositories" not in source, module.__name__
            assert "import sqlite3" not in source, module.__name__
