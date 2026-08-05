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
    QComboBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.project import Project
from transrealm.domain.provider_connection import ProviderConnection
from transrealm.domain.segment import SourceDocument
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
    """Create and list provider connections and model profiles."""

    profiles_changed = Signal(object)

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

        self._add_connection.clicked.connect(self._on_add_connection)
        self._add_profile.clicked.connect(self._on_add_profile)

    def refresh(self) -> None:
        """Reload connections and profiles through the worker."""
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
            return connection_list, profile_list

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

    def _handle_action(self, action: str, result: object) -> None:
        if action == "refresh":
            assert isinstance(result, tuple)
            connections, profiles = result
            assert isinstance(connections, list)
            assert isinstance(profiles, list)
            self._populate(connections, profiles)
            self._status.setText("Ready")
        elif action in {"add_connection", "add_profile"}:
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
            item = QListWidgetItem(f"{connection.name} — {connection.endpoint}")
            self._connections_list.addItem(item)

        self._profile_connection.clear()
        for connection in connections:
            assert isinstance(connection, ProviderConnection)
            assert connection.id is not None
            self._profile_connection.addItem(connection.name, connection.id)

        self._profiles_list.clear()
        for profile in profiles:
            assert isinstance(profile, ModelProfile)
            item = QListWidgetItem(f"{profile.name} — {profile.model_id}")
            assert profile.id is not None
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self._profiles_list.addItem(item)
        self.profiles_changed.emit(profiles)

    def _handle_error(self, error: str) -> None:
        self._status.setText(f"Error: {error}")


class ProjectPage(WorkerPage):
    """Create a project and import a TXT source document."""

    project_ready = Signal(int)
    document_ready = Signal(int, str, int)

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

        self._create_project.clicked.connect(self._on_create_project)
        self._import_txt.clicked.connect(self._on_import_txt)

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
            self._handle_error("Create a project first.")
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
            self._handle_error("Create a project first.")
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

    def _handle_action(self, action: str, result: object) -> None:
        if action == "create_project":
            assert isinstance(result, Project)
            assert result.id is not None
            self._project_id = result.id
            self._status.setText(f"Project {result.name!r} created.")
            self.project_ready.emit(result.id)
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

    def _handle_error(self, error: str) -> None:
        self._status.setText(f"Error: {error}")


class TranslationPage(WorkerPage):
    """Translate the imported document and export the result as TXT."""

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

        layout = QVBoxLayout(self)
        self._status = QLabel("No document imported.", self)
        layout.addWidget(self._status)

        form = QFormLayout()
        self._profile_combo = QComboBox(self)
        self._translate = QPushButton("Translate", self)
        self._cancel = QPushButton("Cancel", self)
        self._cancel.setEnabled(False)
        self._export = QPushButton("Export TXT…", self)
        form.addRow("Profile", self._profile_combo)
        form.addRow(self._translate)
        form.addRow(self._cancel)
        form.addRow(self._export)
        layout.addLayout(form)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._translate.clicked.connect(self._on_translate)
        self._cancel.clicked.connect(self._on_cancel)
        self._export.clicked.connect(self._on_export)

        translation_worker.progress.connect(self._on_progress)
        translation_worker.segment_completed.connect(self._on_segment_completed)
        translation_worker.segment_failed.connect(self._on_segment_failed)
        translation_worker.finished.connect(self._on_finished)
        translation_worker.failed.connect(self._on_failed)

    def set_project(self, project_id: int) -> None:
        """Record the active project id."""
        self._project_id = project_id

    def set_document(self, source_document_id: int, name: str, count: int) -> None:
        """Record the imported document and surface its segment count."""
        self._document_id = source_document_id
        self._document_name = name
        self._status.setText(f"Document {name}: {count} segments. Select a profile.")
        self._progress.setRange(0, 0)
        self._progress.setValue(0)

    def set_profiles(self, profiles: list[object]) -> None:
        """Populate the profile selector (ids are stored as user data)."""
        self._profile_combo.clear()
        for profile in profiles:
            assert isinstance(profile, ModelProfile)
            assert profile.id is not None
            self._profile_combo.addItem(f"{profile.name} — {profile.model_id}", profile.id)

    def _on_translate(self) -> None:
        if self._project_id is None or self._document_id is None:
            self._handle_error("Import a document first.")
            return
        profile_id = self._profile_combo.currentData()
        if not isinstance(profile_id, int):
            self._handle_error("Select a profile first.")
            return
        self._translate.setEnabled(False)
        self._cancel.setEnabled(True)
        self._export.setEnabled(False)
        self._status.setText("Translating…")
        self._translation_worker.start_translate.emit(
            self._project_id,
            self._document_id,
            profile_id,
        )

    def _on_cancel(self) -> None:
        self._status.setText("Cancelling after the current segment…")
        self._translation_worker.request_stop()

    def translate(self) -> None:
        """Programmatic entry point mirroring the Translate button (no dialog)."""
        self._on_translate()

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
        self._translate.setEnabled(True)
        self._cancel.setEnabled(False)
        self._export.setEnabled(True)
        self._status.setText(self._status.text() or "Translation finished.")

    def _on_failed(self, error: str) -> None:
        self._translate.setEnabled(True)
        self._cancel.setEnabled(False)
        self._export.setEnabled(True)
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
        if action == "export":
            self._status.setText("Export written.")
        else:
            self._handle_error(f"Unknown action: {action}")

    def _handle_error(self, error: str) -> None:
        self._status.setText(f"Error: {error}")
