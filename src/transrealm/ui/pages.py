"""PySide6 pages for the desktop shell.

Each page runs every Application Service call through a :class:`ServiceWorker`
(on a dedicated thread), so no SQLite connection or long operation ever runs on
the Qt main thread. Pages expose programmatic entry points (``import_file``,
``export_to``, ``translate``) so pytest-qt tests can drive them without modal
file dialogs.
"""

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


class WorkerPage(QWidget):
    """Base page that runs service calls through a shared ServiceWorker."""

    def __init__(self, worker: ServiceWorker) -> None:
        super().__init__()
        self._worker = worker
        self._request_counter = 0
        self._pending_request: str | None = None
        self._pending_action: str | None = None
        worker.task_done.connect(self._on_task_done)
        worker.task_error.connect(self._on_task_error)

    def _submit(self, action: str, fn: Callable[[], object]) -> None:
        self._request_counter += 1
        request_id = f"{id(self)}:{self._request_counter}"
        self._pending_request = request_id
        self._pending_action = action
        self._worker.run_requested.emit(request_id, fn)

    def _on_task_done(self, request_id: str, result: object) -> None:
        if request_id != self._pending_request:
            return
        action = self._pending_action
        self._pending_request = None
        self._pending_action = None
        if action is not None:
            self._handle_action(action, result)

    def _on_task_error(self, request_id: str, error: str) -> None:
        if request_id != self._pending_request:
            return
        self._pending_request = None
        self._pending_action = None
        self._handle_error(error)

    def _handle_action(self, action: str, result: object) -> None:
        raise NotImplementedError

    def _handle_error(self, error: str) -> None:
        raise NotImplementedError


class SettingsPage(WorkerPage):
    """Create and manage provider connections and model profiles.

    Extended for P1-T04-M04: connection/profile deletion with actionable
    in-use errors and an actionable hint when a connection's credential
    reference does not resolve on this machine.
    """

    def __init__(self, worker: ServiceWorker, *, db_path: Path, app_version: str) -> None:
        super().__init__(worker)
        self._db_path = db_path
        self._app_version = app_version

        layout = QVBoxLayout(self)

        self._status = QLabel("", self)
        layout.addWidget(self._status)

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


class ProjectPage(WorkerPage):
    """Create/select a project, choose its active profile, manage its glossary.

    Extended for P1-T04-M04: the active ModelProfile selection and the
    project-scoped Glossary (lock/priority/scope) are managed here, always
    through Application Services on the worker thread — the page never queries
    the database directly.
    """

    project_ready = Signal(int)
    document_ready = Signal(int, str, int)
    project_settings_changed = Signal(int)

    def __init__(self, worker: ServiceWorker, *, db_path: Path, app_version: str) -> None:
        super().__init__(worker)
        self._db_path = db_path
        self._app_version = app_version
        self._project_id: int | None = None

        layout = QVBoxLayout(self)
        self._status = QLabel("", self)
        layout.addWidget(self._status)

        form = QFormLayout()
        self._project_name = QLineEdit(self)
        self._source_language = QLineEdit(self)
        self._target_language = QLineEdit(self)
        self._create_project = QPushButton("Create Project", self)
        self._import_txt = QPushButton("Import TXT…", self)
        form.addRow("Name", self._project_name)
        form.addRow("Source lang", self._source_language)
        form.addRow("Target lang", self._target_language)
        form.addRow(self._create_project)
        form.addRow(self._import_txt)
        layout.addLayout(form)

        layout.addWidget(QLabel("Open project", self))
        self._project_combo = QComboBox(self)
        layout.addWidget(self._project_combo)

        active_form = QFormLayout()
        self._active_profile_combo = QComboBox(self)
        self._set_active = QPushButton("Set Active Profile", self)
        self._clear_active = QPushButton("Clear Active Profile", self)
        active_form.addRow("Active profile", self._active_profile_combo)
        active_form.addRow(self._set_active)
        active_form.addRow(self._clear_active)
        layout.addLayout(active_form)
        self._active_profile_label = QLabel("", self)
        layout.addWidget(self._active_profile_label)

        layout.addWidget(QLabel("Glossary", self))
        glossary_form = QFormLayout()
        self._gloss_source = QLineEdit(self)
        self._gloss_target = QLineEdit(self)
        self._gloss_scope = QLineEdit(self)
        self._gloss_priority = QSpinBox(self)
        self._gloss_priority.setRange(0, 100)
        self._gloss_priority.setValue(50)
        self._gloss_locked = QCheckBox("Locked (injected into prompt)", self)
        glossary_form.addRow("Source term", self._gloss_source)
        glossary_form.addRow("Target term", self._gloss_target)
        glossary_form.addRow("Scope", self._gloss_scope)
        glossary_form.addRow("Priority", self._gloss_priority)
        glossary_form.addRow(self._gloss_locked)
        layout.addLayout(glossary_form)

        glossary_buttons = QHBoxLayout()
        self._add_glossary = QPushButton("Add Entry", self)
        self._update_glossary = QPushButton("Update Entry", self)
        self._delete_glossary = QPushButton("Delete Entry", self)
        glossary_buttons.addWidget(self._add_glossary)
        glossary_buttons.addWidget(self._update_glossary)
        glossary_buttons.addWidget(self._delete_glossary)
        layout.addLayout(glossary_buttons)

        self._glossary_list = QListWidget(self)
        layout.addWidget(self._glossary_list)

        self._create_project.clicked.connect(self._on_create_project)
        self._import_txt.clicked.connect(self._on_import_txt)
        self._project_combo.activated.connect(self._on_project_selected)
        self._set_active.clicked.connect(self._on_set_active)
        self._clear_active.clicked.connect(self._on_clear_active)
        self._add_glossary.clicked.connect(self._on_add_glossary)
        self._update_glossary.clicked.connect(self._on_update_glossary)
        self._delete_glossary.clicked.connect(self._on_delete_glossary)
        self._glossary_list.itemSelectionChanged.connect(self._on_glossary_selected)

    def refresh(self) -> None:
        """Reload projects, profiles, the active selection and glossary."""
        self._submit("refresh", self._refresh_task())

    def _refresh_task(self) -> Callable[[], object]:
        project_id = self._project_id

        def task() -> object:
            with ProjectService(
                self._db_path,
                app_version=self._app_version,
            ) as projects:
                project_list = projects.list_projects()
                project = next(
                    (p for p in project_list if p.id == project_id),
                    None,
                )
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as profiles:
                profile_list = profiles.list_profiles()
                active_profile = (
                    profiles.get_profile(project.active_profile_id)
                    if project is not None and project.active_profile_id is not None
                    else None
                )
            glossary_entries: list[GlossaryEntry] = []
            if project_id is not None:
                with GlossaryService(
                    self._db_path,
                    app_version=self._app_version,
                ) as glossary:
                    glossary_entries = glossary.list_entries(project_id)
            return project_list, profile_list, project, active_profile, glossary_entries

        return task

    def _on_create_project(self) -> None:
        name = self._project_name.text().strip()
        source = self._source_language.text().strip() or "ja"
        target = self._target_language.text().strip() or "zh"
        if not name:
            self._handle_error("Project name is required.")
            return
        self._submit("create_project", self._create_project_task(name, source, target))

    def _create_project_task(
        self,
        name: str,
        source: str,
        target: str,
    ) -> Callable[[], object]:
        def task() -> object:
            with ProjectService(self._db_path, app_version=self._app_version) as service:
                return service.create_project(
                    name=name,
                    source_language=source,
                    target_language=target,
                )

        return task

    def _on_import_txt(self) -> None:
        if self._project_id is None:
            self._handle_error("Create or select a project first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import TXT",
            "",
            "Text files (*.txt);;All files (*)",
        )
        if path:
            self.import_file(Path(path))

    def import_file(self, path: Path) -> None:
        """Import ``path`` for the current project (no file dialog)."""
        if self._project_id is None:
            self._handle_error("Create or select a project first.")
            return
        project_id = self._project_id
        self._submit(
            "import_txt",
            self._import_task(project_id, path),
        )

    def _import_task(self, project_id: int, path: Path) -> Callable[[], object]:
        def task() -> object:
            with ImportService(self._db_path, app_version=self._app_version) as service:
                return service.import_txt(project_id, path, name=path.name)

        return task

    def _on_project_selected(self, index: int) -> None:
        project_id = self._project_combo.itemData(index)
        if not isinstance(project_id, int):
            self._handle_error("Select a valid project.")
            return
        self.select_project(project_id)

    def select_project(self, project_id: int) -> None:
        """Select the active project (programmatic entry point, no dialog)."""
        self._project_id = project_id
        self.project_ready.emit(project_id)
        self.refresh()

    def _on_set_active(self) -> None:
        if self._project_id is None:
            self._handle_error("Create or select a project first.")
            return
        profile_id = self._active_profile_combo.currentData()
        if not isinstance(profile_id, int):
            self._handle_error("Create a profile first.")
            return
        project_id = self._project_id
        self._submit(
            "select_active_profile",
            self._select_active_profile_task(project_id, profile_id),
        )

    def _select_active_profile_task(
        self,
        project_id: int,
        profile_id: int,
    ) -> Callable[[], object]:
        def task() -> object:
            with ProjectService(self._db_path, app_version=self._app_version) as service:
                return service.select_active_profile(project_id, profile_id)

        return task

    def _on_clear_active(self) -> None:
        if self._project_id is None:
            self._handle_error("Create or select a project first.")
            return
        project_id = self._project_id
        self._submit(
            "clear_active_profile",
            self._clear_active_profile_task(project_id),
        )

    def _clear_active_profile_task(self, project_id: int) -> Callable[[], object]:
        def task() -> object:
            with ProjectService(self._db_path, app_version=self._app_version) as service:
                return service.clear_active_profile(project_id)

        return task

    def _on_add_glossary(self) -> None:
        if self._project_id is None:
            self._handle_error("Create or select a project first.")
            return
        project_id = self._project_id
        source = self._gloss_source.text().strip()
        target = self._gloss_target.text().strip()
        scope = self._gloss_scope.text().strip()
        priority = self._gloss_priority.value()
        locked = self._gloss_locked.isChecked()
        self._submit(
            "add_glossary",
            self._add_glossary_task(project_id, source, target, scope, priority, locked),
        )

    def _add_glossary_task(
        self,
        project_id: int,
        source: str,
        target: str,
        scope: str,
        priority: int,
        locked: bool,
    ) -> Callable[[], object]:
        def task() -> object:
            with GlossaryService(self._db_path, app_version=self._app_version) as service:
                return service.create_entry(
                    project_id=project_id,
                    source_term=source,
                    target_term=target,
                    scope=scope,
                    priority=priority,
                    is_locked=locked,
                    origin="user",
                )

        return task

    def _on_update_glossary(self) -> None:
        item = self._glossary_list.currentItem()
        if item is None:
            self._handle_error("Select a glossary entry to update.")
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, GlossaryEntry) or entry.id is None:
            self._handle_error("Select a valid glossary entry.")
            return
        entry_id = entry.id
        self._submit(
            "update_glossary",
            self._update_glossary_task(
                entry_id,
                self._gloss_source.text().strip(),
                self._gloss_target.text().strip(),
                self._gloss_scope.text().strip(),
                self._gloss_priority.value(),
                self._gloss_locked.isChecked(),
            ),
        )

    def _update_glossary_task(
        self,
        entry_id: int,
        source: str,
        target: str,
        scope: str,
        priority: int,
        locked: bool,
    ) -> Callable[[], object]:
        def task() -> object:
            with GlossaryService(self._db_path, app_version=self._app_version) as service:
                return service.update_entry(
                    entry_id,
                    source_term=source,
                    target_term=target,
                    scope=scope,
                    priority=priority,
                    is_locked=locked,
                )

        return task

    def _on_delete_glossary(self) -> None:
        item = self._glossary_list.currentItem()
        if item is None:
            self._handle_error("Select a glossary entry to delete.")
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, GlossaryEntry) or entry.id is None:
            self._handle_error("Select a valid glossary entry.")
            return
        self._submit("delete_glossary", self._delete_glossary_task(entry.id))

    def _delete_glossary_task(self, entry_id: int) -> Callable[[], object]:
        def task() -> object:
            with GlossaryService(self._db_path, app_version=self._app_version) as service:
                return service.delete_entry(entry_id)

        return task

    def _on_glossary_selected(self) -> None:
        item = self._glossary_list.currentItem()
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, GlossaryEntry):
            return
        self._gloss_source.setText(entry.source_term)
        self._gloss_target.setText(entry.target_term)
        self._gloss_scope.setText(entry.scope)
        self._gloss_priority.setValue(entry.priority)
        self._gloss_locked.setChecked(entry.is_locked)

    def _handle_action(self, action: str, result: object) -> None:
        if action == "refresh":
            assert isinstance(result, tuple)
            projects, profiles, project, active_profile, glossary_entries = result
            assert isinstance(projects, list)
            assert isinstance(profiles, list)
            assert isinstance(glossary_entries, list)
            self._populate(projects, profiles, project, active_profile, glossary_entries)
        elif action == "create_project":
            assert isinstance(result, Project)
            assert result.id is not None
            self._project_id = result.id
            self._status.setText(f"Project {result.name!r} created.")
            self.project_ready.emit(result.id)
            self.refresh()
        elif action == "select_active_profile":
            assert isinstance(result, Project)
            self._status.setText(f"Active profile set for project {result.name!r}.")
            self._notify_settings_changed()
            self.refresh()
        elif action == "clear_active_profile":
            assert isinstance(result, Project)
            self._status.setText(f"Active profile cleared for project {result.name!r}.")
            self._notify_settings_changed()
            self.refresh()
        elif action == "add_glossary":
            assert isinstance(result, GlossaryEntry)
            self._status.setText(f"Added glossary entry {result.source_term!r}.")
            self.refresh()
        elif action == "update_glossary":
            assert isinstance(result, GlossaryEntry)
            self._status.setText(f"Updated glossary entry {result.source_term!r}.")
            self.refresh()
        elif action == "delete_glossary":
            self._status.setText("Glossary entry deleted.")
            self.refresh()
        elif action == "import_txt":
            assert isinstance(result, tuple)
            document, segments = result
            assert isinstance(document, SourceDocument)
            assert isinstance(segments, list)
            assert document.id is not None
            self._status.setText(
                f"Imported {document.name}: {len(segments)} segments.",
            )
            self.document_ready.emit(document.id, document.name, len(segments))
        else:
            self._handle_error(f"Unknown action: {action}")

    def _populate(
        self,
        projects: list[object],
        profiles: list[object],
        project: object,
        active_profile: object,
        glossary_entries: list[object],
    ) -> None:
        assert isinstance(project, Project | None)
        assert isinstance(active_profile, ModelProfile | None)
        self._project_combo.clear()
        for candidate in projects:
            assert isinstance(candidate, Project)
            assert candidate.id is not None
            self._project_combo.addItem(candidate.name, candidate.id)
        if self._project_id is not None:
            index = self._project_combo.findData(self._project_id)
            if index >= 0:
                self._project_combo.setCurrentIndex(index)

        self._active_profile_combo.clear()
        for candidate in profiles:
            assert isinstance(candidate, ModelProfile)
            assert candidate.id is not None
            self._active_profile_combo.addItem(
                f"{candidate.name} — {candidate.model_id}",
                candidate.id,
            )
        if project is not None and project.active_profile_id is not None:
            index = self._active_profile_combo.findData(project.active_profile_id)
            if index >= 0:
                self._active_profile_combo.setCurrentIndex(index)

        if active_profile is not None:
            self._active_profile_label.setText(
                f"Active: {active_profile.name} — {active_profile.model_id}",
            )
        elif project is not None:
            self._active_profile_label.setText("Active profile: none")
        else:
            self._active_profile_label.setText("")

        self._glossary_list.clear()
        for entry in glossary_entries:
            assert isinstance(entry, GlossaryEntry)
            assert entry.id is not None
            lock = "locked" if entry.is_locked else "unlocked"
            item = QListWidgetItem(
                f"{entry.source_term} → {entry.target_term} [{entry.scope}] "
                f"priority {entry.priority} ({lock})",
            )
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._glossary_list.addItem(item)

    def _notify_settings_changed(self) -> None:
        """Tell dependents the project's mode/profile config changed."""
        if self._project_id is not None:
            self.project_settings_changed.emit(self._project_id)

    def _handle_error(self, error: str) -> None:
        self._status.setText(f"Error: {error}")


class TranslationPage(WorkerPage):
    """Auto-mode translation journey: import -> translate -> status -> export.

    M01 ships the auto mode. The active ModelProfile is resolved from the
    project on the translation worker thread (never from a manual picker), and
    when the project has no active profile the page shows a single recoverable
    step — a button that jumps to the Project tab. The workbench surface
    (explicit profile/parameter selection) arrives in P1-T03-M02.
    """

    request_project_setup = Signal()

    def __init__(
        self,
        worker: ServiceWorker,
        *,
        translation_worker: TranslationWorker,
        db_path: Path,
        app_version: str,
    ) -> None:
        super().__init__(worker)
        self._translation_worker = translation_worker
        self._db_path = db_path
        self._app_version = app_version
        self._project_id: int | None = None
        self._document_id: int | None = None
        self._document_name = ""
        self._mode = MODE_AUTO
        self._running = False
        self._active_profile_id: int | None = None
        self._param_editor: WorkbenchParamEditor | None = None
        self._prompt_editor: WorkbenchPromptEditor | None = None
        self._revision_editor: WorkbenchRevisionEditor | None = None
        self._workbench_progress: list[SegmentProgress] = []

        layout = QVBoxLayout(self)
        self._status = QLabel("No document imported.", self)
        layout.addWidget(self._status)

        self._mode_label = QLabel("Mode: auto", self)
        layout.addWidget(self._mode_label)
        self._active_profile_label = QLabel("", self)
        layout.addWidget(self._active_profile_label)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Interaction mode:", self))
        self._mode_switch = QComboBox(self)
        self._mode_switch.addItem("Auto", MODE_AUTO)
        self._mode_switch.addItem("Workbench", MODE_WORKBENCH)
        mode_row.addWidget(self._mode_switch)
        layout.addLayout(mode_row)

        doc_row = QHBoxLayout()
        doc_row.addWidget(QLabel("Document:", self))
        self._document_combo = QComboBox(self)
        doc_row.addWidget(self._document_combo)
        layout.addLayout(doc_row)

        form = QFormLayout()
        self._translate = QPushButton("Translate", self)
        self._cancel = QPushButton("Cancel", self)
        self._cancel.setEnabled(False)
        self._export = QPushButton("Export TXT…", self)
        form.addRow(self._translate)
        form.addRow(self._cancel)
        form.addRow(self._export)
        layout.addLayout(form)

        self._config_missing_label = QLabel("", self)
        self._config_missing_label.setWordWrap(True)
        self._config_missing_label.hide()
        layout.addWidget(self._config_missing_label)

        self._set_active_profile = QPushButton("Set active profile…", self)
        self._set_active_profile.hide()
        layout.addWidget(self._set_active_profile)

        # Workbench surface (P1-T03-M02): real Segment/Attempt progress, the
        # active Profile's capability, and a parameter editor presenting only
        # the capability-supported parameters. Hidden in auto mode.
        self._workbench_container = QWidget(self)
        workbench_layout = QVBoxLayout(self._workbench_container)
        workbench_layout.setContentsMargins(0, 0, 0, 0)
        self._workbench_info = QLabel("", self._workbench_container)
        self._workbench_info.setWordWrap(True)
        workbench_layout.addWidget(self._workbench_info)
        self._param_host = QWidget(self._workbench_container)
        self._param_layout = QVBoxLayout(self._param_host)
        self._param_layout.setContentsMargins(0, 0, 0, 0)
        workbench_layout.addWidget(self._param_host)
        self._prompt_host = QWidget(self._workbench_container)
        self._prompt_layout = QVBoxLayout(self._prompt_host)
        self._prompt_layout.setContentsMargins(0, 0, 0, 0)
        workbench_layout.addWidget(self._prompt_host)
        self._segment_progress = QListWidget(self._workbench_container)
        workbench_layout.addWidget(self._segment_progress)
        self._revision_host = QWidget(self._workbench_container)
        self._revision_layout = QVBoxLayout(self._revision_host)
        self._revision_layout.setContentsMargins(0, 0, 0, 0)
        workbench_layout.addWidget(self._revision_host)
        self._workbench_container.hide()
        layout.addWidget(self._workbench_container)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._translate.clicked.connect(self._on_translate)
        self._cancel.clicked.connect(self._on_cancel)
        self._export.clicked.connect(self._on_export)
        self._set_active_profile.clicked.connect(self._on_request_project_setup)
        self._mode_switch.activated.connect(self._on_mode_switch)
        self._document_combo.activated.connect(self._on_document_selected)
        self._segment_progress.itemSelectionChanged.connect(self._on_segment_selected)

        translation_worker.progress.connect(self._on_progress)
        translation_worker.segment_completed.connect(self._on_segment_completed)
        translation_worker.segment_failed.connect(self._on_segment_failed)
        translation_worker.config_missing.connect(self._on_config_missing)
        translation_worker.finished.connect(self._on_finished)
        translation_worker.failed.connect(self._on_failed)

    def set_project(self, project_id: int) -> None:
        """Record the active project id and refresh its mode/profile status."""
        self._project_id = project_id
        self.refresh()

    def refresh(self) -> None:
        """Reload the project mode and active profile for status feedback."""
        self._submit("refresh", self._refresh_task())

    def _refresh_task(self) -> Callable[[], object]:
        project_id = self._project_id
        # Capture on the main thread at submission: the task runs on the worker
        # thread, and the current document may change (import, selector) between
        # submission and execution.
        current = self._document_id

        def task() -> object:
            if project_id is None:
                return None
            with ProjectService(
                self._db_path,
                app_version=self._app_version,
            ) as projects:
                project = projects.get_project(project_id)
            if project is None:
                return None
            active_profile = None
            override = None
            if project.active_profile_id is not None:
                with ModelProfileService(
                    self._db_path,
                    app_version=self._app_version,
                ) as profiles:
                    active_profile = profiles.get_profile(project.active_profile_id)
                    if active_profile is not None and active_profile.id is not None:
                        override = profiles.get_prompt_override(active_profile.id)
            documents: list[SourceDocument] = []
            progress: list[SegmentProgress] = []
            effective_id: int | None = None
            with TranslationRunService(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                documents = runs.list_source_documents(project_id=project_id)
                # The document selector is per-project: the recorded document is
                # kept only when it belongs to the selected project, otherwise no
                # document is active (switching projects must not leak a stale id
                # from another project into the progress view).
                if current is not None and any(doc.id == current for doc in documents):
                    effective_id = current
                if effective_id is not None:
                    progress = runs.list_segment_progress(source_document_id=effective_id)
            return project, active_profile, progress, override, documents, effective_id

        return task

    def set_document(self, source_document_id: int, name: str, count: int) -> None:
        """Record the imported document and surface its segment count."""
        self._document_id = source_document_id
        self._document_name = name
        self._status.setText(f"Document {name}: {count} segments.")
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        # The workbench segment progress (and mode/active labels) depend on the
        # selected document, so a refresh reflects the newly imported state.
        self.refresh()

    def _on_document_selected(self, index: int) -> None:
        """Load the selected project document's progress into the page."""
        if self._running:
            # Switching documents mid-run would render another document's
            # progress against the running run's results; keep the current one.
            self._restore_document_selector()
            self._status.setText(
                "A translation is running — finish or Cancel it before switching documents.",
            )
            return
        document_id = self._document_combo.itemData(index)
        if not isinstance(document_id, int) or document_id == self._document_id:
            return
        self._document_id = document_id
        self._document_name = self._document_combo.itemText(index)
        self._status.setText(f"Document {self._document_name}.")
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self.refresh()

    def _restore_document_selector(self) -> None:
        """Align the document selector with the current document (or clear it)."""
        index = (
            self._document_combo.findData(self._document_id)
            if self._document_id is not None
            else -1
        )
        self._document_combo.setCurrentIndex(index)

    def _populate_documents(
        self,
        documents: list[object],
        effective_id: int | None,
        segment_count: int,
    ) -> None:
        """Fill the per-project document selector and keep the page in sync.

        ``effective_id`` is the document whose progress ``refresh`` already
        loaded: the recorded document when it belongs to the current project,
        otherwise the project's first document (or None when it has none). The
        status is only rewritten when the effective document actually changed so
        action feedback (e.g. "Mode switched to …") is not clobbered on every
        refresh.
        """
        docs = [doc for doc in documents if isinstance(doc, SourceDocument)]
        previous = self._document_id
        self._document_combo.clear()
        self._document_combo.setEnabled(bool(docs))
        for doc in docs:
            assert doc.id is not None
            self._document_combo.addItem(doc.name, doc.id)
        self._document_id = effective_id
        self._document_name = ""
        if effective_id is not None:
            for doc in docs:
                if doc.id == effective_id:
                    self._document_name = doc.name
                    break
            if effective_id != previous:
                self._status.setText(
                    f"Document {self._document_name}: {segment_count} segments.",
                )
        else:
            self._status.setText("Select a project document.")
            self._progress.setRange(0, 0)
            self._progress.setValue(0)
        index = self._document_combo.findData(effective_id) if effective_id is not None else -1
        # With no effective document do not leave the first item highlighted:
        # the selector must not advertise a document that is not loaded.
        self._document_combo.setCurrentIndex(index)

    def _on_translate(self) -> None:
        if self._running:
            return
        if self._project_id is None or self._document_id is None:
            self._handle_error("Import a document first.")
            return
        if self._mode == MODE_WORKBENCH:
            if self._active_profile_id is None:
                self._on_config_missing(
                    "This project has no active profile. Set one in the Project tab.",
                )
                return
            params = self._param_editor.values() if self._param_editor is not None else None
            self._set_running(True)
            self._status.setText("Translating…")
            self._hide_config_missing()
            self._translation_worker.start_translate_workbench.emit(
                self._project_id,
                self._document_id,
                self._active_profile_id,
                params,
            )
            return
        self._set_running(True)
        self._status.setText("Translating…")
        self._hide_config_missing()
        self._translation_worker.start_translate_auto.emit(
            self._project_id,
            self._document_id,
        )

    def _set_running(self, running: bool) -> None:
        """Track an in-flight run and gate the run controls accordingly.

        The document selector is gated too: switching documents mid-run would
        show another document's progress against the running run's results.
        """
        self._running = running
        self._translate.setEnabled(not running)
        self._cancel.setEnabled(running)
        self._export.setEnabled(not running)
        self._document_combo.setEnabled(not running)

    def _on_mode_switch(self, index: int) -> None:
        """Persist a mode change, refusing to change it mid-run.

        While a translation is running the mode must not change in place (the
        running run keeps its Profile/Workflow/parameters), so the attempt is
        rejected with a hint to finish or Cancel first and the selector is
        restored to the current persisted mode.
        """
        if self._running:
            self._status.setText(
                "A translation is running — finish or Cancel it before switching modes.",
            )
            self._sync_mode_switch()
            return
        mode = self._mode_switch.itemData(index)
        if mode == self._mode:
            return
        project_id = self._project_id
        if project_id is None:
            self._sync_mode_switch()
            self._handle_error("Create or select a project first.")
            return
        self._submit("set_mode", self._set_mode_task(project_id, mode))

    def _set_mode_task(self, project_id: int, mode: str) -> Callable[[], object]:
        def task() -> object:
            with ProjectService(self._db_path, app_version=self._app_version) as svc:
                return svc.set_mode(project_id, mode)

        return task

    def _sync_mode_switch(self) -> None:
        """Align the mode selector with the persisted mode."""
        index = self._mode_switch.findData(self._mode)
        if index >= 0:
            self._mode_switch.setCurrentIndex(index)

    def _on_cancel(self) -> None:
        self._status.setText("Cancelling after the current segment…")
        self._translation_worker.request_stop()

    def translate(self) -> None:
        """Programmatic entry point mirroring the Translate button (no dialog)."""
        self._on_translate()

    def _on_config_missing(self, reason: str) -> None:
        self._set_running(False)
        self._status.setText("Translation needs configuration.")
        self._config_missing_label.setText(reason)
        self._config_missing_label.show()
        self._set_active_profile.show()

    def _hide_config_missing(self) -> None:
        self._config_missing_label.hide()
        self._set_active_profile.hide()

    def _on_request_project_setup(self) -> None:
        self.request_project_setup.emit()

    def _on_progress(self, done: int, total: int, stable_key: str) -> None:
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(done)
        if total > 0:
            self._status.setText(f"Translated {done}/{total} ({stable_key}).")

    def _on_segment_completed(self, stable_key: str, revision_id: int) -> None:
        self._status.setText(f"Segment {stable_key} translated (revision {revision_id}).")

    def _on_segment_failed(self, stable_key: str, error: str) -> None:
        self._status.setText(f"Segment {stable_key} failed: {error}")

    def _on_finished(self) -> None:
        self._set_running(False)
        if not self._config_missing_label.isHidden():
            return
        # The workbench progress list reflects the persisted state, so re-read
        # it after a run so the segments show their completed/failed outcome.
        if self._mode == MODE_WORKBENCH:
            self.refresh()
        # A run with no pending segments never emits progress, so replace the
        # placeholder status instead of leaving "Translating…" forever.
        if self._status.text() == "Translating…":
            self._status.setText("Translation finished.")

    def _on_failed(self, error: str) -> None:
        self._set_running(False)
        self._status.setText(f"Translation failed: {error}")

    def _on_export(self) -> None:
        if self._document_id is None:
            self._handle_error("Import a document first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export TXT",
            f"{self._document_name}.txt",
            "Text files (*.txt);;All files (*)",
        )
        if path:
            self.export_to(Path(path))

    def export_to(self, target_path: Path) -> None:
        """Export the document through the worker (no file dialog)."""
        if self._document_id is None:
            self._handle_error("Import a document first.")
            return
        document_id = self._document_id
        self._submit("export", self._export_task(document_id, target_path))

    def _export_task(self, document_id: int, target_path: Path) -> Callable[[], object]:
        def task() -> object:
            from transrealm.application.exporter import TxtExporter

            exporter = TxtExporter(self._db_path, app_version=self._app_version)
            try:
                exporter.export_document(
                    source_document_id=document_id,
                    target_path=target_path,
                )
            finally:
                exporter.close()
            return None

        return task

    def _handle_action(self, action: str, result: object) -> None:
        if action == "refresh":
            if result is None:
                self._mode_label.setText("Mode: auto")
                self._active_profile_label.setText("")
                self._sync_mode_switch()
                self._mode_switch.setEnabled(False)
                self._document_combo.clear()
                self._document_combo.setEnabled(False)
                self._document_id = None
                self._document_name = ""
                self._progress.setRange(0, 0)
                self._progress.setValue(0)
                self._hide_workbench()
                return
            assert isinstance(result, tuple)
            project, active_profile, progress, override, documents, effective_id = result
            assert isinstance(project, Project)
            assert isinstance(progress, list)
            assert isinstance(documents, list)
            self._mode = project.mode
            self._mode_label.setText(
                "Mode: workbench" if project.mode == MODE_WORKBENCH else "Mode: auto",
            )
            self._mode_switch.setEnabled(True)
            self._sync_mode_switch()
            self._active_profile_id = project.active_profile_id
            if isinstance(active_profile, ModelProfile):
                self._active_profile_label.setText(
                    f"Active profile: {active_profile.name} — {active_profile.model_id}",
                )
                self._hide_config_missing()
            elif project.mode == MODE_AUTO:
                self._active_profile_label.setText("Active profile: none")
            else:
                self._active_profile_label.setText("")
            self._populate_documents(documents, effective_id, len(progress))
            if project.mode == MODE_WORKBENCH:
                self._populate_workbench(active_profile, progress, override)
                if active_profile is None:
                    self._on_config_missing(
                        "This project has no active profile. Set one in the Project tab.",
                    )
            else:
                self._hide_workbench()
        elif action == "set_mode":
            assert isinstance(result, Project)
            # Reflect the persisted mode synchronously so a later failed refresh
            # cannot leave the selector showing the pre-switch mode.
            self._mode = result.mode
            self._sync_mode_switch()
            self._status.setText(f"Mode switched to {result.mode}.")
            self.refresh()
        elif action == "save_override":
            self._status.setText("Prompt override saved.")
            self.refresh()
        elif action == "clear_override":
            self._status.setText("Prompt override cleared.")
            self.refresh()
        elif action == "save_revision":
            self._status.setText("Manual translation saved.")
            self.refresh()
        elif action == "lock_revision":
            self._status.setText("Current translation locked.")
            self.refresh()
        elif action == "unlock_revision":
            self._status.setText("Current translation unlocked.")
            self.refresh()
        elif action == "export":
            self._status.setText("Export written.")
        else:
            self._handle_error(f"Unknown action: {action}")

    def _populate_workbench(
        self,
        active_profile: object,
        progress: list[object],
        override: object = None,
    ) -> None:
        """Show real Segment/Attempt progress and the active Profile's surface."""
        items: list[SegmentProgress] = []
        for entry in progress:
            assert isinstance(entry, SegmentProgress)
            items.append(entry)
        previous_id = self._selected_segment_id()
        revision_draft = (
            self._revision_editor.translation() if self._revision_editor is not None else None
        )

        self._workbench_container.show()
        self._workbench_progress = items
        self._segment_progress.clear()
        for item in items:
            label = f"{item.stable_key}: {item.status}"
            if item.current_revision_id is not None:
                label += f" (rev {item.current_revision_id})"
            if item.attempt_status is not None:
                label += f" · attempt {item.attempt_status}"
                if item.attempt_error:
                    label += f": {item.attempt_error}"
            self._segment_progress.addItem(label)
        if previous_id is not None:
            for index, item in enumerate(items):
                if item.segment_id == previous_id:
                    self._segment_progress.setCurrentRow(index)
                    break
        selected = self._selected_segment_item()
        if selected is not None:
            keep_draft = selected.segment_id == previous_id
            self._rebuild_revision_editor(
                selected,
                initial=revision_draft if keep_draft else None,
            )
        else:
            self._clear_revision_editor()

        if not isinstance(active_profile, ModelProfile):
            self._workbench_info.setText("")
            self._clear_param_editor()
            self._clear_prompt_editor()
            return

        try:
            capability = active_profile.get_capability()
        except ModelCapabilityError:
            capability = None
        if capability is None:
            self._workbench_info.setText(
                f"Profile: {active_profile.name} — {active_profile.model_id} "
                "(no capability snapshot — parameters unavailable).",
            )
            self._clear_param_editor()
            self._clear_prompt_editor()
            return

        supported = ", ".join(presented_parameters(capability)) or "(none)"
        self._workbench_info.setText(
            f"Profile: {active_profile.name} — {active_profile.model_id} · "
            f"context {capability.context_window} · output ≤ "
            f"{capability.max_output_tokens} · supported: {supported}",
        )
        # Preserve the user's current parameter draft across a refresh (e.g.
        # after a run finishes) so the progress read never resets their edits.
        draft = self._param_editor.values() if self._param_editor is not None else None
        self._rebuild_param_editor(capability, active_profile.default_params, initial=draft)
        # Prompt override editor (P1-T03-M03): read-only preset + editable copy.
        prompt_draft = self._prompt_editor.text() if self._prompt_editor is not None else None
        self._rebuild_prompt_editor(override, initial=prompt_draft)

    def _rebuild_param_editor(
        self,
        capability: ModelCapability,
        default_params: dict[str, object],
        *,
        initial: dict[str, object] | None = None,
    ) -> None:
        self._clear_param_editor()
        editor = WorkbenchParamEditor(
            capability,
            default_params,
            self._param_host,
            initial=initial,
        )
        self._param_editor = editor
        self._param_layout.addWidget(editor)

    def _clear_param_editor(self) -> None:
        while self._param_layout.count():
            child = self._param_layout.takeAt(0)
            if child is None:
                break
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._param_editor = None

    def _rebuild_prompt_editor(
        self,
        override: object,
        *,
        initial: str | None = None,
    ) -> None:
        """Show the read-only preset with an editable override copy.

        ``override`` is the persisted PromptOverride for the active profile (or
        None). The editor is seeded with the saved override text, the preset
        text, or the preserved draft (in that order of preference). A stale
        override (parent preset version no longer matches) surfaces a warning so
        the user can re-save or clear it instead of every segment failing at
        translate time.
        """
        self._clear_prompt_editor()
        preset = current_preset()
        override_text = None
        parent_version = None
        stale = False
        if isinstance(override, PromptOverride):
            override_text = override.template_text
            parent_version = override.parent_template_version
            stale = override.parent_template_version != preset.version
        editor = WorkbenchPromptEditor(
            preset.template_text,
            override_text=override_text,
            override_parent_version=parent_version,
            initial=initial,
            stale=stale,
            parent=self._prompt_host,
        )
        editor.save_requested.connect(self._on_save_override)
        editor.clear_requested.connect(self._on_clear_override)
        self._prompt_editor = editor
        self._prompt_layout.addWidget(editor)

    def _clear_prompt_editor(self) -> None:
        while self._prompt_layout.count():
            child = self._prompt_layout.takeAt(0)
            if child is None:
                break
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._prompt_editor = None

    def _selected_segment_item(self) -> SegmentProgress | None:
        row = self._segment_progress.currentRow()
        if row < 0 or row >= len(self._workbench_progress):
            return None
        return self._workbench_progress[row]

    def _selected_segment_id(self) -> int | None:
        item = self._selected_segment_item()
        return item.segment_id if item is not None else None

    def _on_segment_selected(self) -> None:
        """Show the manual translation editor for the newly selected segment."""
        selected = self._selected_segment_item()
        if selected is None:
            self._clear_revision_editor()
            return
        self._rebuild_revision_editor(selected)

    def _rebuild_revision_editor(
        self,
        item: SegmentProgress,
        *,
        initial: str | None = None,
    ) -> None:
        """Show the selected segment's manual translation editor.

        ``initial`` preserves the user's unsaved edit across a refresh when the
        selected segment has not changed (matching the parameter/prompt drafts).
        """
        self._clear_revision_editor()
        editor = WorkbenchRevisionEditor(
            source_text=item.source_text,
            revision_text=item.revision_text,
            locked=item.revision_locked,
            initial=initial,
            parent=self._revision_host,
        )
        editor.save_requested.connect(self._on_save_revision)
        editor.lock_requested.connect(self._on_lock_revision)
        editor.unlock_requested.connect(self._on_unlock_revision)
        self._revision_editor = editor
        self._revision_layout.addWidget(editor)

    def _clear_revision_editor(self) -> None:
        while self._revision_layout.count():
            child = self._revision_layout.takeAt(0)
            if child is None:
                break
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._revision_editor = None

    def _on_save_revision(self, text: str) -> None:
        selected = self._selected_segment_item()
        if selected is None:
            self._handle_error("Select a segment to save a translation for.")
            return
        self._submit("save_revision", self._save_revision_task(selected.segment_id, text))

    def _save_revision_task(self, segment_id: int, text: str) -> Callable[[], object]:
        def task() -> object:
            with TranslationRunService(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.append_user_revision(segment_id=segment_id, text=text)

        return task

    def _on_lock_revision(self) -> None:
        selected = self._selected_segment_item()
        if selected is None:
            self._handle_error("Select a segment to lock.")
            return
        self._submit("lock_revision", self._lock_revision_task(selected.segment_id))

    def _lock_revision_task(self, segment_id: int) -> Callable[[], object]:
        def task() -> object:
            with TranslationRunService(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.lock_current_revision(segment_id=segment_id)

        return task

    def _on_unlock_revision(self) -> None:
        selected = self._selected_segment_item()
        if selected is None:
            self._handle_error("Select a segment to unlock.")
            return
        self._submit("unlock_revision", self._unlock_revision_task(selected.segment_id))

    def _unlock_revision_task(self, segment_id: int) -> Callable[[], object]:
        def task() -> object:
            with TranslationRunService(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.unlock_current_revision(segment_id=segment_id)

        return task

    def _on_save_override(self, text: str) -> None:
        if self._active_profile_id is None:
            self._handle_error("No active profile to save the override to.")
            return
        profile_id = self._active_profile_id
        self._submit("save_override", self._save_override_task(profile_id, text))

    def _save_override_task(self, profile_id: int, text: str) -> Callable[[], object]:
        def task() -> object:
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as profiles:
                return profiles.set_prompt_override(profile_id, text)

        return task

    def _on_clear_override(self) -> None:
        if self._active_profile_id is None:
            self._handle_error("No active profile to clear the override for.")
            return
        profile_id = self._active_profile_id
        self._submit("clear_override", self._clear_override_task(profile_id))

    def _clear_override_task(self, profile_id: int) -> Callable[[], object]:
        def task() -> object:
            with ModelProfileService(
                self._db_path,
                app_version=self._app_version,
            ) as profiles:
                return profiles.clear_prompt_override(profile_id)

        return task

    def _hide_workbench(self) -> None:
        self._workbench_container.hide()
        self._clear_param_editor()
        self._clear_prompt_editor()
        self._clear_revision_editor()
        self._segment_progress.clear()
        self._workbench_progress = []

    def _handle_error(self, error: str) -> None:
        # A failed mode change must not leave the selector showing a mode that
        # was never persisted; re-align it with the current project's mode.
        self._sync_mode_switch()
        self._status.setText(f"Error: {error}")
