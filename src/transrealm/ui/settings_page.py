"""PySide6 pages for the desktop shell.

Each page runs every Application Service call through a :class:`ServiceWorker`
(on a dedicated thread), so no SQLite connection or long operation ever runs on
the Qt main thread. Pages expose programmatic entry points (``import_file``,
``export_to``, ``translate``) so pytest-qt tests can drive them without modal
file dialogs.
"""

# ruff: noqa: F401
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from transrealm.application.credential_status import (
    CredentialStatus,
    report_credential_availability,
)
from transrealm.application.glossary_service import GlossaryService
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.preset_templates import current_preset
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.workbench import SegmentProgress, presented_parameters
from transrealm.domain.glossary_entry import GlossaryEntry
from transrealm.domain.model_profile import ModelCapability, ModelCapabilityError, ModelProfile
from transrealm.domain.project import MODE_AUTO, MODE_WORKBENCH, Project
from transrealm.domain.prompt_override import PromptOverride
from transrealm.domain.provider_connection import ProviderConnection
from transrealm.domain.segment import SourceDocument
from transrealm.ui.i18n import LanguageManager
from transrealm.ui.page_base import WorkerPage
from transrealm.ui.workbench import (
    WorkbenchParamEditor,
    WorkbenchPromptEditor,
    WorkbenchRevisionEditor,
)
from transrealm.ui.worker import ServiceWorker, TranslationWorker

_DEFAULT_BUDGET: dict[str, object] = {
    "total": 8192,
    "reserved_output": 1024,
    "reserved_prompt": 1024,
}


class SettingsPage(WorkerPage):
    """Create and manage provider connections and model profiles.

    Extended for P1-T04-M04: connection/profile deletion with actionable
    in-use errors and an actionable hint when a connection's credential
    reference does not resolve on this machine.
    """

    def __init__(
        self,
        worker: ServiceWorker,
        *,
        db_path: Path,
        app_version: str,
        i18n: LanguageManager | None = None,
    ) -> None:
        super().__init__(worker)
        self._db_path = db_path
        self._app_version = app_version
        self._i18n = i18n or LanguageManager(parent=self)

        layout = QVBoxLayout(self)

        self._status = QLabel("", self)
        layout.addWidget(self._status)

        language_form = QFormLayout()
        self._language_combo = QComboBox(self)
        self._language_combo.setObjectName("language-selector")
        self._language_combo.addItem("English", "en")
        self._language_combo.addItem("简体中文", "zh_CN")
        self._language_combo.setProperty("transrealm_i18n_static_items", True)
        language_index = self._language_combo.findData(self._i18n.current_language)
        if language_index >= 0:
            self._language_combo.setCurrentIndex(language_index)
        language_form.addRow("Language", self._language_combo)
        layout.addLayout(language_form)

        connection_form = QFormLayout()
        self._conn_name = QLineEdit(self)
        self._conn_endpoint = QLineEdit(self)
        self._conn_credential = QLineEdit(self)
        self._add_connection = QPushButton("Add Connection", self)
        connection_form.addRow("Name", self._conn_name)
        connection_form.addRow("Endpoint", self._conn_endpoint)
        connection_form.addRow("Credential ref", self._conn_credential)
        connection_form.addRow(self._add_connection)
        layout.addLayout(connection_form)

        layout.addWidget(QLabel("Connections", self))
        self._connections_list = QListWidget(self)
        layout.addWidget(self._connections_list)
        self._delete_connection = QPushButton("Delete Selected Connection", self)
        layout.addWidget(self._delete_connection)

        self._credential_status = QLabel("", self)
        self._credential_status.setWordWrap(True)
        layout.addWidget(self._credential_status)

        profile_form = QFormLayout()
        self._profile_name = QLineEdit(self)
        self._profile_model = QLineEdit(self)
        self._profile_connection = QComboBox(self)
        self._add_profile = QPushButton("Add Profile", self)
        profile_form.addRow("Name", self._profile_name)
        profile_form.addRow("Model id", self._profile_model)
        profile_form.addRow("Connection", self._profile_connection)
        profile_form.addRow(self._add_profile)
        layout.addLayout(profile_form)

        layout.addWidget(QLabel("Profiles", self))
        self._profiles_list = QListWidget(self)
        layout.addWidget(self._profiles_list)
        self._delete_profile = QPushButton("Delete Selected Profile", self)
        layout.addWidget(self._delete_profile)

        self._add_connection.clicked.connect(self._on_add_connection)
        self._add_profile.clicked.connect(self._on_add_profile)
        self._delete_connection.clicked.connect(self._on_delete_connection)
        self._delete_profile.clicked.connect(self._on_delete_profile)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._i18n.language_changed.connect(self._sync_language_selection)
        self._i18n.bind_tree(self)

    def _on_language_changed(self, index: int) -> None:
        language = self._language_combo.itemData(index)
        if isinstance(language, str):
            self._i18n.set_language(language)

    def _sync_language_selection(self, language: str) -> None:
        index = self._language_combo.findData(language)
        if index >= 0 and index != self._language_combo.currentIndex():
            self._language_combo.setCurrentIndex(index)

    def refresh(self) -> None:
        """Reload connections, profiles and credential availability."""
        self._submit("refresh", self._refresh_task())

    def _refresh_task(self) -> Callable[[], object]:
        def task() -> object:
            with ProviderConnectionService(
                self._db_path,
                app_version=self._app_version,
            ) as connections:
                connection_list = connections.list_connections()
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as profiles:
                profile_list = profiles.list_profiles()
            statuses = report_credential_availability(connection_list)
            return connection_list, profile_list, statuses

        return task

    def _on_add_connection(self) -> None:
        name = self._conn_name.text().strip()
        endpoint = self._conn_endpoint.text().strip()
        credential = self._conn_credential.text().strip() or None
        if not name or not endpoint:
            self._handle_error("Connection name and endpoint are required.")
            return
        self._submit("add_connection", self._create_connection_task(name, endpoint, credential))

    def _create_connection_task(
        self,
        name: str,
        endpoint: str,
        credential: str | None,
    ) -> Callable[[], object]:
        def task() -> object:
            with ProviderConnectionService(
                self._db_path,
                app_version=self._app_version,
            ) as service:
                return service.create_connection(
                    name=name,
                    provider_type="openai-compatible",
                    endpoint=endpoint,
                    credential_reference=credential,
                )

        return task

    def _on_add_profile(self) -> None:
        name = self._profile_name.text().strip()
        model_id = self._profile_model.text().strip()
        connection_id = self._profile_connection.currentData()
        if not name or not model_id:
            self._handle_error("Profile name and model id are required.")
            return
        if not isinstance(connection_id, int):
            self._handle_error("Select a connection first.")
            return
        self._submit("add_profile", self._create_profile_task(name, model_id, connection_id))

    def _create_profile_task(
        self,
        name: str,
        model_id: str,
        connection_id: int,
    ) -> Callable[[], object]:
        def task() -> object:
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as service:
                return service.create_profile(
                    name=name,
                    provider_connection_id=connection_id,
                    model_id=model_id,
                    template_version="1.0.0",
                    output_protocol="json",
                    context_budget=_DEFAULT_BUDGET,
                    default_params={"temperature": 0.3},
                    capability=ModelCapability(
                        context_window=128000,
                        max_output_tokens=8192,
                        supports_streaming=False,
                        supports_structured_output=False,
                        supported_parameters={"temperature", "max_tokens"},
                    ),
                )

        return task

    def _on_delete_connection(self) -> None:
        item = self._connections_list.currentItem()
        if item is None:
            self._handle_error("Select a connection to delete.")
            return
        connection_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(connection_id, int):
            self._handle_error("Select a valid connection to delete.")
            return
        self._submit(
            "delete_connection",
            self._delete_connection_task(connection_id),
        )

    def _delete_connection_task(self, connection_id: int) -> Callable[[], object]:
        def task() -> object:
            with ProviderConnectionService(
                self._db_path,
                app_version=self._app_version,
            ) as service:
                return service.delete_connection(connection_id)

        return task

    def _on_delete_profile(self) -> None:
        item = self._profiles_list.currentItem()
        if item is None:
            self._handle_error("Select a profile to delete.")
            return
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(profile_id, int):
            self._handle_error("Select a valid profile to delete.")
            return
        self._submit("delete_profile", self._delete_profile_task(profile_id))

    def _delete_profile_task(self, profile_id: int) -> Callable[[], object]:
        def task() -> object:
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as service:
                return service.delete_profile(profile_id)

        return task

    def _handle_action(self, action: str, result: object) -> None:
        if action == "refresh":
            assert isinstance(result, tuple)
            connections, profiles, statuses = result
            assert isinstance(connections, list)
            assert isinstance(profiles, list)
            assert isinstance(statuses, list)
            self._populate(connections, profiles)
            self._show_credential_status(statuses)
        elif action in {"add_connection", "add_profile"}:
            self.refresh()
        elif action in {"delete_connection", "delete_profile"}:
            self.refresh()
        else:
            self._handle_error(f"Unknown action: {action}")

    def _populate(
        self,
        connections: list[object],
        profiles: list[object],
    ) -> None:
        self._connections_list.clear()
        for connection in connections:
            assert isinstance(connection, ProviderConnection)
            assert connection.id is not None
            item = QListWidgetItem(f"{connection.name} — {connection.endpoint}")
            item.setData(Qt.ItemDataRole.UserRole, connection.id)
            self._connections_list.addItem(item)

        previous_connection_id = self._profile_connection.currentData()
        self._profile_connection.clear()
        for connection in connections:
            assert isinstance(connection, ProviderConnection)
            assert connection.id is not None
            self._profile_connection.addItem(connection.name, connection.id)
        if isinstance(previous_connection_id, int):
            index = self._profile_connection.findData(previous_connection_id)
            if index >= 0:
                self._profile_connection.setCurrentIndex(index)

        self._profiles_list.clear()
        for profile in profiles:
            assert isinstance(profile, ModelProfile)
            item = QListWidgetItem(f"{profile.name} — {profile.model_id}")
            assert profile.id is not None
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self._profiles_list.addItem(item)

    def _show_credential_status(self, statuses: list[CredentialStatus]) -> None:
        missing = [status for status in statuses if not status.available]
        if not missing:
            self._credential_status.setText("")
            return
        lines = [
            f"{status.connection_name} ({status.credential_reference}): {status.hint}"
            for status in missing
            if status.hint is not None
        ]
        self._credential_status.setText("Missing credentials:\n" + "\n".join(lines))

    def _handle_error(self, error: str) -> None:
        self._status.setText(f"Error: {error}")
