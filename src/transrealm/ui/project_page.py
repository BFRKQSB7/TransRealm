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
from transrealm.ui.page_base import WorkerPage
from transrealm.ui.workbench import (
    WorkbenchParamEditor,
    WorkbenchPromptEditor,
    WorkbenchRevisionEditor,
)
from transrealm.ui.worker import ServiceWorker, TranslationWorker


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
        self._import_file = QPushButton("Import file…", self)
        # Keep the old private hook usable for existing UI tests/integrations.
        self._import_txt = self._import_file
        form.addRow("Name", self._project_name)
        form.addRow("Source lang", self._source_language)
        form.addRow("Target lang", self._target_language)
        form.addRow(self._create_project)
        form.addRow(self._import_file)
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
        self._import_file.clicked.connect(self._on_import_file)
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

    def _on_import_file(self) -> None:
        if self._project_id is None:
            self._handle_error("Create or select a project first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import source file",
            "",
            "Source files (*.txt *.json *.srt *.ass *.ssa *.vtt);;All files (*)",
        )
        if path:
            self.import_file(Path(path))

    def _on_import_txt(self) -> None:
        """Preserve the legacy programmatic slot name."""
        self._on_import_file()

    def import_file(self, path: Path) -> None:
        """Import ``path`` for the current project (no file dialog)."""
        if self._project_id is None:
            self._handle_error("Create or select a project first.")
            return
        project_id = self._project_id
        self._submit("import_file", self._import_task(project_id, path))

    def _import_task(self, project_id: int, path: Path) -> Callable[[], object]:
        def task() -> object:
            with ImportService(self._db_path, app_version=self._app_version) as service:
                return service.import_file(project_id, path, name=path.name)

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
        elif action in {"import_file", "import_txt"}:
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
