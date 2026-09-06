"""PySide6 pages for the desktop shell.

Each page runs every Application Service call through a :class:`ServiceWorker`
(on a dedicated thread), so no SQLite connection or long operation ever runs on
the Qt main thread. Pages expose programmatic entry points (``import_file``,
``export_to``, ``translate``) so pytest-qt tests can drive them without modal
file dialogs.
"""

# ruff: noqa: F401
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QToolButton,
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
from transrealm.ui.page_base import WorkerPage, safe_error_message
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
        self._connections_by_id: dict[int, ProviderConnection] = {}
        self._profiles_by_id: dict[int, ModelProfile] = {}
        self._connection_editing_id: int | None = None
        self._profile_editing_id: int | None = None

        layout = QVBoxLayout(self)

        self._status = QLabel("", self)
        self._status.setObjectName("status-banner")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._connection_count = 0
        self._profile_count = 0
        self._setup_hint = QLabel(self)
        self._setup_hint.setWordWrap(True)
        self._setup_hint.setObjectName("setup-hint")
        self._setup_hint.setProperty("transrealm_i18n_dynamic", True)
        layout.addWidget(self._setup_hint)

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

        connection_section = QGroupBox("Connections", self)
        connection_section.setObjectName("connections-section")
        connection_layout = QVBoxLayout(connection_section)
        self._connection_help = QLabel(
            "Connection = where/how to reach the local OpenAI-compatible service; "
            "it does not choose a model.",
            connection_section,
        )
        self._connection_help.setWordWrap(True)
        self._connection_help.setProperty("transrealm_i18n_dynamic", True)
        connection_layout.addWidget(self._connection_help)
        connection_form = QFormLayout()
        self._conn_name = QLineEdit(self)
        self._conn_endpoint = QLineEdit(self)
        self._conn_endpoint.setPlaceholderText("e.g. http://127.0.0.1:<port>/v1")
        self._conn_credential = QLineEdit(self)
        self._conn_timeout = QSpinBox(self)
        self._conn_timeout.setRange(1, 3600)
        self._conn_timeout.setValue(30)
        self._conn_timeout.setObjectName("connection-timeout")
        self._conn_retries = QSpinBox(self)
        self._conn_retries.setRange(0, 20)
        self._conn_retries.setValue(0)
        self._conn_retries.setObjectName("connection-retries")
        self._conn_retry_delay = QDoubleSpinBox(self)
        self._conn_retry_delay.setRange(0.0, 3600.0)
        self._conn_retry_delay.setDecimals(2)
        self._conn_retry_delay.setValue(0.0)
        self._conn_retry_delay.setObjectName("connection-retry-delay")
        self._add_connection = QPushButton("Add Connection", self)
        self._edit_connection = QPushButton("Edit Selected Connection", self)
        self._save_connection = QPushButton("Save Connection", self)
        self._cancel_connection = QPushButton("Cancel Connection Edit", self)
        connection_form.addRow("Name", self._conn_name)
        connection_form.addRow("Endpoint", self._conn_endpoint)
        connection_form.addRow("Timeout (seconds)", self._conn_timeout)
        connection_form.addRow("Max retries", self._conn_retries)
        connection_form.addRow("Retry delay (seconds)", self._conn_retry_delay)
        connection_form.addRow("Credential ref", self._conn_credential)
        connection_form.addRow(self._add_connection)
        connection_form.addRow(self._edit_connection)
        connection_form.addRow(self._save_connection)
        connection_form.addRow(self._cancel_connection)
        connection_layout.addLayout(connection_form)
        self._connections_list = QListWidget(self)
        connection_layout.addWidget(self._connections_list)
        self._delete_connection = QPushButton("Delete Selected Connection", self)
        connection_layout.addWidget(self._delete_connection)

        self._credential_status = QLabel("", self)
        self._credential_status.setWordWrap(True)
        connection_layout.addWidget(self._credential_status)
        layout.addWidget(connection_section)

        profile_section = QGroupBox("Profiles", self)
        profile_section.setObjectName("profiles-section")
        profile_layout = QVBoxLayout(profile_section)
        self._profile_help = QLabel(
            "Model Profile = which model and translation parameters to use; "
            "select an existing Connection first.",
            profile_section,
        )
        self._profile_help.setWordWrap(True)
        self._profile_help.setProperty("transrealm_i18n_dynamic", True)
        profile_layout.addWidget(self._profile_help)
        profile_form = QFormLayout()
        self._profile_name = QLineEdit(self)
        self._profile_model = QLineEdit(self)
        self._profile_connection = QComboBox(self)
        self._add_profile = QPushButton("Add Profile", self)
        self._edit_profile = QPushButton("Edit Selected Profile", self)
        self._save_profile = QPushButton("Save Profile", self)
        self._cancel_profile = QPushButton("Cancel Profile Edit", self)
        profile_form.addRow("Name", self._profile_name)
        profile_form.addRow("Model id", self._profile_model)
        profile_form.addRow("Connection", self._profile_connection)
        profile_form.addRow(self._add_profile)
        profile_form.addRow(self._edit_profile)
        profile_form.addRow(self._save_profile)
        profile_form.addRow(self._cancel_profile)
        profile_layout.addLayout(profile_form)

        self._profile_advanced_toggle = QToolButton(self)
        self._profile_advanced_toggle.setText("Advanced Profile Settings")
        self._profile_advanced_toggle.setCheckable(True)
        self._profile_advanced_toggle.setChecked(False)
        self._profile_advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._profile_advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
        )
        profile_layout.addWidget(self._profile_advanced_toggle)

        self._profile_advanced = QWidget(self)
        advanced_form = QFormLayout(self._profile_advanced)
        self._profile_template_version = QLineEdit("1.0.0", self._profile_advanced)
        self._profile_output_protocol = QLineEdit("json", self._profile_advanced)
        self._profile_context_total = QSpinBox(self._profile_advanced)
        self._profile_context_total.setRange(1, 10_000_000)
        self._profile_context_total.setValue(8192)
        self._profile_reserved_output = QSpinBox(self._profile_advanced)
        self._profile_reserved_output.setRange(0, 10_000_000)
        self._profile_reserved_output.setValue(1024)
        self._profile_reserved_prompt = QSpinBox(self._profile_advanced)
        self._profile_reserved_prompt.setRange(0, 10_000_000)
        self._profile_reserved_prompt.setValue(1024)
        self._profile_default_params = QLineEdit(
            '{"temperature": 0.3}',
            self._profile_advanced,
        )
        self._profile_capability_context = QSpinBox(self._profile_advanced)
        self._profile_capability_context.setRange(1, 10_000_000)
        self._profile_capability_context.setValue(128_000)
        self._profile_capability_output = QSpinBox(self._profile_advanced)
        self._profile_capability_output.setRange(1, 10_000_000)
        self._profile_capability_output.setValue(8192)
        self._profile_supports_streaming = QCheckBox(self._profile_advanced)
        self._profile_supports_structured = QCheckBox(self._profile_advanced)
        self._profile_supported_parameters = QLineEdit(
            "temperature, max_tokens",
            self._profile_advanced,
        )
        advanced_form.addRow("Template version", self._profile_template_version)
        advanced_form.addRow("Output protocol", self._profile_output_protocol)
        advanced_form.addRow("Context budget", self._profile_context_total)
        advanced_form.addRow("Reserved output", self._profile_reserved_output)
        advanced_form.addRow("Reserved prompt", self._profile_reserved_prompt)
        advanced_form.addRow("Default params (JSON)", self._profile_default_params)
        advanced_form.addRow("Capability context", self._profile_capability_context)
        advanced_form.addRow("Capability output", self._profile_capability_output)
        advanced_form.addRow("Supports streaming", self._profile_supports_streaming)
        advanced_form.addRow("Supports structured output", self._profile_supports_structured)
        advanced_form.addRow("Supported parameters", self._profile_supported_parameters)
        self._profile_advanced.setVisible(False)
        profile_layout.addWidget(self._profile_advanced)

        self._profiles_list = QListWidget(self)
        profile_layout.addWidget(self._profiles_list)
        self._delete_profile = QPushButton("Delete Selected Profile", self)
        profile_layout.addWidget(self._delete_profile)
        layout.addWidget(profile_section)

        self._add_connection.clicked.connect(self._on_add_connection)
        self._edit_connection.clicked.connect(self._on_edit_connection)
        self._save_connection.clicked.connect(self._on_save_connection)
        self._cancel_connection.clicked.connect(self._cancel_connection_edit)
        self._add_profile.clicked.connect(self._on_add_profile)
        self._edit_profile.clicked.connect(self._on_edit_profile)
        self._save_profile.clicked.connect(self._on_save_profile)
        self._cancel_profile.clicked.connect(self._cancel_profile_edit)
        self._delete_connection.clicked.connect(self._on_delete_connection)
        self._delete_profile.clicked.connect(self._on_delete_profile)
        self._connections_list.currentItemChanged.connect(self._on_connection_selected)
        self._profiles_list.currentItemChanged.connect(self._on_profile_selected)
        self._profile_advanced_toggle.toggled.connect(self._toggle_profile_advanced)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._i18n.language_changed.connect(self._sync_language_selection)
        self._i18n.language_changed.connect(lambda _language: self._refresh_setup_copy())
        self._i18n.bind_tree(self)
        self._refresh_setup_copy()
        self._save_connection.setEnabled(False)
        self._cancel_connection.setEnabled(False)
        self._save_profile.setEnabled(False)
        self._cancel_profile.setEnabled(False)

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
        if not name or not endpoint:
            self._handle_error("Connection name and endpoint are required.")
            return
        credential, valid = self._read_credential_reference()
        if not valid:
            return
        self._submit(
            "add_connection",
            self._create_connection_task(
                name,
                endpoint,
                credential,
                self._conn_timeout.value(),
                self._conn_retries.value(),
                self._conn_retry_delay.value(),
            ),
        )

    def _create_connection_task(
        self,
        name: str,
        endpoint: str,
        credential: str | None,
        timeout_seconds: int,
        max_retries: int,
        retry_delay_seconds: float,
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
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    retry_delay_seconds=retry_delay_seconds,
                    credential_reference=credential,
                )

        return task

    def _on_edit_connection(self) -> None:
        item = self._connections_list.currentItem()
        if item is None:
            self._handle_error("Select a connection to edit.")
            return
        connection_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(connection_id, int):
            self._handle_error("Select a valid connection to edit.")
            return
        self._connection_editing_id = connection_id
        self._save_connection.setEnabled(True)
        self._cancel_connection.setEnabled(True)

    def _on_save_connection(self) -> None:
        connection_id = self._connection_editing_id
        if connection_id is None:
            self._handle_error("Select a connection to edit.")
            return
        name = self._conn_name.text().strip()
        endpoint = self._conn_endpoint.text().strip()
        if not name or not endpoint:
            self._handle_error("Connection name and endpoint are required.")
            return
        credential, valid = self._read_credential_reference()
        if not valid:
            return
        self._submit(
            "update_connection",
            self._update_connection_task(
                connection_id,
                name,
                endpoint,
                credential,
                self._conn_timeout.value(),
                self._conn_retries.value(),
                self._conn_retry_delay.value(),
            ),
        )

    def _update_connection_task(
        self,
        connection_id: int,
        name: str,
        endpoint: str,
        credential: str | None,
        timeout_seconds: int,
        max_retries: int,
        retry_delay_seconds: float,
    ) -> Callable[[], object]:
        def task() -> object:
            with ProviderConnectionService(
                self._db_path,
                app_version=self._app_version,
            ) as service:
                return service.update_connection(
                    connection_id,
                    name=name,
                    endpoint=endpoint,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    retry_delay_seconds=retry_delay_seconds,
                    credential_reference=credential,
                )

        return task

    def _cancel_connection_edit(self) -> None:
        self._connection_editing_id = None
        self._save_connection.setEnabled(False)
        self._cancel_connection.setEnabled(False)

    def _read_credential_reference(self) -> tuple[str | None, bool]:
        credential = self._conn_credential.text().strip() or None
        if credential is not None and not credential.startswith(("env:", "wincred:")):
            self._handle_error("Credential reference must use env: or wincred: scheme.")
            return None, False
        return credential, True

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
        payload = self._read_profile_advanced_values()
        if payload is None:
            return
        self._submit(
            "add_profile",
            self._create_profile_task(name, model_id, connection_id, payload),
        )

    def _create_profile_task(
        self,
        name: str,
        model_id: str,
        connection_id: int,
        payload: tuple[str, str, dict[str, object], dict[str, object], ModelCapability],
    ) -> Callable[[], object]:
        template_version, output_protocol, context_budget, default_params, capability = payload

        def task() -> object:
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as service:
                return service.create_profile(
                    name=name,
                    provider_connection_id=connection_id,
                    model_id=model_id,
                    template_version=template_version,
                    output_protocol=output_protocol,
                    context_budget=context_budget,
                    default_params=default_params,
                    capability=capability,
                )

        return task

    def _on_edit_profile(self) -> None:
        item = self._profiles_list.currentItem()
        if item is None:
            self._handle_error("Select a profile to edit.")
            return
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(profile_id, int):
            self._handle_error("Select a valid profile to edit.")
            return
        self._profile_editing_id = profile_id
        self._save_profile.setEnabled(True)
        self._cancel_profile.setEnabled(True)

    def _on_save_profile(self) -> None:
        profile_id = self._profile_editing_id
        if profile_id is None:
            self._handle_error("Select a profile to edit.")
            return
        name = self._profile_name.text().strip()
        model_id = self._profile_model.text().strip()
        connection_id = self._profile_connection.currentData()
        if not name or not model_id:
            self._handle_error("Profile name and model id are required.")
            return
        if not isinstance(connection_id, int):
            self._handle_error("Select a connection first.")
            return
        payload = self._read_profile_advanced_values()
        if payload is None:
            return
        self._submit(
            "update_profile",
            self._update_profile_task(profile_id, name, model_id, connection_id, payload),
        )

    def _update_profile_task(
        self,
        profile_id: int,
        name: str,
        model_id: str,
        connection_id: int,
        payload: tuple[str, str, dict[str, object], dict[str, object], ModelCapability],
    ) -> Callable[[], object]:
        template_version, output_protocol, context_budget, default_params, capability = payload

        def task() -> object:
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as service:
                return service.update_profile(
                    profile_id,
                    name=name,
                    provider_connection_id=connection_id,
                    model_id=model_id,
                    template_version=template_version,
                    output_protocol=output_protocol,
                    context_budget=context_budget,
                    default_params=default_params,
                    capability=capability,
                )

        return task

    def _cancel_profile_edit(self) -> None:
        self._profile_editing_id = None
        self._save_profile.setEnabled(False)
        self._cancel_profile.setEnabled(False)

    def _read_profile_advanced_values(
        self,
    ) -> tuple[str, str, dict[str, object], dict[str, object], ModelCapability] | None:
        try:
            default_params = json.loads(self._profile_default_params.text())
            if not isinstance(default_params, dict):
                raise ValueError
            supported_parameters = {
                item.strip()
                for item in self._profile_supported_parameters.text().split(",")
                if item.strip()
            }
            capability = ModelCapability(
                context_window=self._profile_capability_context.value(),
                max_output_tokens=self._profile_capability_output.value(),
                supports_streaming=self._profile_supports_streaming.isChecked(),
                supports_structured_output=self._profile_supports_structured.isChecked(),
                supported_parameters=supported_parameters,
            )
        except (TypeError, ValueError, KeyError):
            self._handle_error(
                "Default params must be a JSON object and capability values must be valid.",
            )
            return None
        context_budget: dict[str, object] = {
            "total": self._profile_context_total.value(),
            "reserved_output": self._profile_reserved_output.value(),
            "reserved_prompt": self._profile_reserved_prompt.value(),
        }
        total = context_budget["total"]
        reserved_output = context_budget["reserved_output"]
        reserved_prompt = context_budget["reserved_prompt"]
        if isinstance(total, int) and isinstance(reserved_output, int) and isinstance(
            reserved_prompt,
            int,
        ) and reserved_output + reserved_prompt > total:
            self._handle_error("Reserved context budget must not exceed total.")
            return None
        return (
            self._profile_template_version.text().strip(),
            self._profile_output_protocol.text().strip(),
            context_budget,
            {str(key): value for key, value in default_params.items()},
            capability,
        )

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
        elif action == "add_connection":
            self._status.setText("Connection added.")
            self.refresh()
        elif action == "update_connection":
            self._status.setText("Connection updated.")
            self.refresh()
        elif action == "add_profile":
            self._status.setText("Profile added.")
            self.refresh()
        elif action == "update_profile":
            self._status.setText("Profile updated.")
            self.refresh()
        elif action == "delete_connection":
            self._status.setText("Connection deleted.")
            self.refresh()
        elif action == "delete_profile":
            self._status.setText("Profile deleted.")
            self.refresh()
        else:
            self._handle_error(f"Unknown action: {action}")

    def _populate(
        self,
        connections: list[object],
        profiles: list[object],
    ) -> None:
        self._connections_by_id = {
            connection.id: connection
            for connection in connections
            if isinstance(connection, ProviderConnection) and connection.id is not None
        }
        self._profiles_by_id = {
            profile.id: profile
            for profile in profiles
            if isinstance(profile, ModelProfile) and profile.id is not None
        }
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
        self._show_setup_hint(len(self._connections_by_id), len(self._profiles_by_id))

    def _on_connection_selected(self, current: QListWidgetItem | None, _previous: object) -> None:
        if current is None:
            return
        connection_id = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(connection_id, int):
            return
        connection = self._connections_by_id.get(connection_id)
        if connection is None:
            return
        self._connection_editing_id = connection_id
        self._conn_name.setText(connection.name)
        self._conn_endpoint.setText(connection.endpoint)
        self._conn_credential.setText(connection.credential_reference or "")
        self._conn_timeout.setValue(connection.timeout_seconds)
        self._conn_retries.setValue(connection.max_retries)
        self._conn_retry_delay.setValue(connection.retry_delay_seconds)
        self._save_connection.setEnabled(True)
        self._cancel_connection.setEnabled(True)

    def _on_profile_selected(self, current: QListWidgetItem | None, _previous: object) -> None:
        if current is None:
            return
        profile_id = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(profile_id, int):
            return
        profile = self._profiles_by_id.get(profile_id)
        if profile is None:
            return
        self._profile_editing_id = profile_id
        self._profile_name.setText(profile.name)
        self._profile_model.setText(profile.model_id)
        connection_index = self._profile_connection.findData(profile.provider_connection_id)
        if connection_index >= 0:
            self._profile_connection.setCurrentIndex(connection_index)
        self._profile_template_version.setText(profile.template_version)
        self._profile_output_protocol.setText(profile.output_protocol)
        total = profile.context_budget.get("total", 8192)
        reserved_output = profile.context_budget.get("reserved_output", 1024)
        reserved_prompt = profile.context_budget.get("reserved_prompt", 1024)
        self._profile_context_total.setValue(total if isinstance(total, int) else 8192)
        self._profile_reserved_output.setValue(
            reserved_output if isinstance(reserved_output, int) else 1024,
        )
        self._profile_reserved_prompt.setValue(
            reserved_prompt if isinstance(reserved_prompt, int) else 1024,
        )
        self._profile_default_params.setText(json.dumps(profile.default_params))
        try:
            capability = profile.get_capability()
        except ModelCapabilityError:
            capability = None
        if capability is not None:
            self._profile_capability_context.setValue(capability.context_window)
            self._profile_capability_output.setValue(capability.max_output_tokens)
            self._profile_supports_streaming.setChecked(capability.supports_streaming)
            self._profile_supports_structured.setChecked(
                capability.supports_structured_output,
            )
            self._profile_supported_parameters.setText(
                ", ".join(sorted(capability.supported_parameters)),
            )
        self._save_profile.setEnabled(True)
        self._cancel_profile.setEnabled(True)

    def _toggle_profile_advanced(self, expanded: bool) -> None:
        self._profile_advanced.setVisible(expanded)
        self._profile_advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow,
        )

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
        raw_credential = self._conn_credential.text().strip()
        if raw_credential:
            error = error.replace(raw_credential, "[credential reference]")
        self._status.setText(f"Error: {safe_error_message(error)}")

    def _refresh_setup_copy(self) -> None:
        """Retranslate the first-use explanation after a language change."""
        self._connection_help.setText(
            self._translate_copy(
                "Connection = where/how to reach the local OpenAI-compatible service; "
                "it does not choose a model.",
            ),
        )
        self._profile_help.setText(
            self._translate_copy(
                "Model Profile = which model and translation parameters to use; "
                "select an existing Connection first.",
            ),
        )
        self._show_setup_hint(self._connection_count, self._profile_count)

    def _show_setup_hint(self, connection_count: int, profile_count: int) -> None:
        """Show the next first-use configuration step without probing the endpoint."""
        self._connection_count = connection_count
        self._profile_count = profile_count
        if connection_count == 0:
            source = (
                "Add a Connection with the API address of your already-running "
                "local OpenAI-compatible service."
            )
        elif profile_count == 0:
            source = "Connection saved. Next, create a Model Profile and choose this Connection."
        else:
            source = (
                "Connection and Model Profile are ready. Next, select the active "
                "Profile in Project."
            )
        self._setup_hint.setText(self._translate_copy(source))

    def _translate_copy(self, source: str) -> str:
        """Use source copy for English and Qt translation for other languages."""
        return source if self._i18n.current_language == "en" else self._i18n.tr(source)
