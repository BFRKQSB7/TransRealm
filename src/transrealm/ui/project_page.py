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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from transrealm.application.project_service import ProjectDeletionSummary
from transrealm.application.translation_facade import TranslationFacade
from transrealm.domain.glossary_entry import GlossaryEntry
from transrealm.domain.model_profile import ModelProfile
from transrealm.domain.project import Project
from transrealm.domain.segment import SourceDocument
from transrealm.ui.i18n import LanguageManager
from transrealm.ui.page_base import WorkerPage, safe_error_message
from transrealm.ui.worker import ServiceWorker


class ProjectPage(WorkerPage):
    """Create/select a project, choose its active profile, manage its glossary.

    Extended for P1-T04-M04: the active ModelProfile selection and the
    project-scoped Glossary (lock/priority/scope) are managed here, always
    through Application Services on the worker thread — the page never queries
    the database directly.
    """

    project_ready = Signal(int)
    project_deleted = Signal(int)
    document_ready = Signal(int, str, int)
    project_settings_changed = Signal(int)
    request_settings_setup = Signal()

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
        self._project_id: int | None = None
        self._deletion_summary_data: ProjectDeletionSummary | None = None
        self._has_profiles = False
        self._has_project = False
        self._has_active_profile = False
        self._allow_initial_project_restore = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Open Job", self))
        self._project_combo = QComboBox(self)
        self._project_combo.setMinimumWidth(140)
        toolbar.addWidget(self._project_combo, 1)
        self._import_file = QPushButton("Import file…", self)
        self._import_txt = self._import_file
        toolbar.addWidget(self._import_file)
        self._details_toggle = QPushButton("Job settings", self)
        self._details_toggle.setCheckable(True)
        toolbar.addWidget(self._details_toggle)
        outer.addLayout(toolbar)
        self._details = QTabWidget(self)
        self._details.setMaximumHeight(240)
        self._details.hide()
        self._details_toggle.toggled.connect(self._details.setVisible)
        outer.addWidget(self._details)
        job_panel = QWidget(self)
        self._add_panel(job_panel, "Job and files")
        layout = QVBoxLayout(job_panel)
        self._status = QLabel("", self)
        self._status.setWordWrap(True)
        self._status.setProperty("role", "muted")
        outer.addWidget(self._status)

        create_box = QGroupBox("New Job", self)
        self._create_box = create_box
        create_box.setCheckable(True)
        create_box.setChecked(False)
        create_content = QWidget(create_box)
        create_layout = QVBoxLayout(create_box)
        create_layout.addWidget(create_content)
        create_box.toggled.connect(create_content.setVisible)
        create_content.hide()
        form = QFormLayout(create_content)
        self._project_name = QLineEdit(self)
        self._source_language = QLineEdit(self)
        self._source_language.setPlaceholderText("ja")
        self._target_language = QLineEdit(self)
        self._target_language.setPlaceholderText("zh")
        self._create_project = QPushButton("Create Job", self)
        form.addRow("Name", self._project_name)
        form.addRow("Source lang", self._source_language)
        form.addRow("Target lang", self._target_language)
        form.addRow(self._create_project)
        layout.addWidget(create_box)
        import_help = QLabel(
            "Drop files to start a Job. Default languages: ja → zh; change them in New Job.", self
        )
        import_help.setWordWrap(True)
        layout.addWidget(import_help)

        delete_box = QGroupBox("Delete Job", self)
        delete_box.setCheckable(True)
        delete_box.setChecked(False)
        delete_content = QWidget(delete_box)
        delete_layout = QVBoxLayout(delete_box)
        delete_layout.addWidget(delete_content)
        delete_box.toggled.connect(delete_content.setVisible)
        delete_content.hide()
        delete_form = QFormLayout(delete_content)
        self._delete_summary_label = QLabel("", self)
        self._delete_summary_label.setWordWrap(True)
        self._delete_confirmation = QLineEdit(self)
        self._delete_confirmation.setPlaceholderText("Type Job name to confirm")
        self._delete_project = QPushButton("Delete Job", self)
        delete_form.addRow("Delete summary", self._delete_summary_label)
        delete_form.addRow("Confirm name", self._delete_confirmation)
        delete_form.addRow(self._delete_project)
        layout.addWidget(delete_box)

        active_host = QWidget(self)
        active_host.hide()
        active_form = QFormLayout(active_host)
        self._active_profile_combo = QComboBox(self)
        self._set_active = QPushButton("Set Model", self)
        self._clear_active = QPushButton("Clear Model", self)
        active_form.addRow("Selected model", self._active_profile_combo)
        active_form.addRow(self._set_active)
        active_form.addRow(self._clear_active)
        self._active_profile_label = QLabel("", self)
        self._active_profile_label.hide()
        active_help = QLabel(
            "Choose a model here or in the translation controls below.",
            self,
        )
        active_help.setWordWrap(True)
        active_help.hide()
        self._profile_setup_hint = QLabel("", self)
        self._profile_setup_hint.setWordWrap(True)
        self._profile_setup_hint.setProperty("transrealm_i18n_dynamic", True)
        self._profile_setup_hint.hide()
        layout.addWidget(self._profile_setup_hint)
        self._open_settings = QPushButton("Open Providers", self)
        self._open_settings.hide()
        layout.addWidget(self._open_settings)

        glossary_panel = QWidget(self)
        self._add_panel(glossary_panel, "Glossary")
        layout = QVBoxLayout(glossary_panel)
        layout.addWidget(QLabel("Glossary", self))
        glossary_form = QFormLayout()
        self._gloss_source = QLineEdit(self)
        self._gloss_target = QLineEdit(self)
        self._gloss_scope = QLineEdit(self)
        self._gloss_scope.setText("project")
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

        notes_panel = QWidget(self)
        self._add_panel(notes_panel, "Notes")
        notes_layout = QVBoxLayout(notes_panel)
        notes_layout.addWidget(QLabel("Notes used as context for later translations.", self))
        self._notes = QPlainTextEdit(self)
        self._notes.setObjectName("job-notes")
        self._notes.setMaximumHeight(150)
        self._notes_dirty = False
        self._notes.textChanged.connect(lambda: setattr(self, "_notes_dirty", True))
        notes_layout.addWidget(self._notes)
        self._save_notes = QPushButton("Save Notes", self)
        self._save_notes.clicked.connect(self._on_save_notes)
        notes_layout.addWidget(self._save_notes)
        self._notes_status = QLabel("", self)
        self._notes_status.setWordWrap(True)
        notes_layout.addWidget(self._notes_status)

        self._create_project.clicked.connect(self._on_create_project)
        self._import_file.clicked.connect(self._on_import_file)
        self._project_combo.activated.connect(self._on_project_selected)
        self._delete_project.clicked.connect(self._on_delete_project)
        self._set_active.clicked.connect(self._on_set_active)
        self._clear_active.clicked.connect(self._on_clear_active)
        self._open_settings.clicked.connect(self.request_settings_setup.emit)
        self._add_glossary.clicked.connect(self._on_add_glossary)
        self._update_glossary.clicked.connect(self._on_update_glossary)
        self._delete_glossary.clicked.connect(self._on_delete_glossary)
        self._glossary_list.itemSelectionChanged.connect(self._on_glossary_selected)
        self._i18n.language_changed.connect(lambda _language: self._refresh_profile_guidance())
        self._i18n.bind_tree(self)

    def _add_panel(self, panel: QWidget, title: str) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        self._details.addTab(scroll, title)

    def refresh(self) -> None:
        """Reload projects, profiles, the active selection and glossary."""
        self._submit("refresh", self._refresh_task())

    def _refresh_task(self) -> Callable[[], object]:
        project_id = self._project_id

        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                projects = facade.list_jobs()
                project = next((p for p in projects if p.id == project_id), None)
                models = facade.available_models()
                exists = project is not None and project_id is not None
                active = (
                    facade.active_profile(project_id) if project_id is not None and exists else None
                )
                return (
                    projects,
                    models,
                    project,
                    active,
                    facade.glossary(project_id) if project_id is not None and exists else [],
                    facade.deletion_summary(project_id)
                    if project_id is not None and exists
                    else None,
                    facade.notes(project_id) if project_id is not None and exists else "",
                )

        return task

    def _on_create_project(self) -> None:
        name = self._project_name.text().strip()
        source = self._source_language.text().strip() or "ja"
        target = self._target_language.text().strip() or "zh"
        if not name:
            self._handle_error("Job name is required.")
            return
        self._submit("create_project", self._create_project_task(name, source, target))

    def _create_project_task(
        self,
        name: str,
        source: str,
        target: str,
    ) -> Callable[[], object]:
        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.create_job(name=name, source_language=source, target_language=target)

        return task

    def _on_import_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._i18n.tr("Import source files"),
            "",
            "Source files (*.txt *.json *.srt *.ass *.ssa *.vtt);;All files (*)",
        )
        if paths:
            self.import_files([Path(path) for path in paths])

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
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.import_document(project_id, path)

        return task

    def _on_project_selected(self, index: int) -> None:
        project_id = self._project_combo.itemData(index)
        if not isinstance(project_id, int):
            self._handle_error("Select a valid project.")
            return
        self.select_project(project_id)

    def select_project(self, project_id: int) -> None:
        """Select the active project (programmatic entry point, no dialog)."""
        if self._project_id != project_id:
            self._notes_dirty = False
        self._project_id = project_id
        self.project_ready.emit(project_id)
        self.refresh()

    def _on_delete_project(self) -> None:
        self.delete_project()

    def delete_project(self, confirmation_name: str | None = None) -> None:
        """Delete the selected Project after an exact-name confirmation."""
        if confirmation_name is not None:
            self._delete_confirmation.setText(confirmation_name)
        if self._project_id is None or self._deletion_summary_data is None:
            self._handle_error("Create or select a project first.")
            return
        expected_name = self._deletion_summary_data.project_name
        if self._delete_confirmation.text().strip() != expected_name:
            self._handle_error("Type the exact Job name to confirm deletion.")
            return
        project_id = self._project_id
        self._submit("delete_project", self._delete_project_task(project_id))

    def _delete_project_task(self, project_id: int) -> Callable[[], object]:
        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.delete_job(project_id)

        return task

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
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.select_active_profile(project_id, profile_id)

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
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.clear_active_profile(project_id)

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
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.add_glossary_entry(
                    project_id,
                    source,
                    target,
                    scope=scope,
                    priority=priority,
                    is_locked=locked,
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
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.update_glossary_entry(
                    entry_id,
                    source,
                    target,
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
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.delete_glossary_entry(entry_id)

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
            (
                projects,
                profiles,
                project,
                active_profile,
                glossary_entries,
                deletion_summary,
                notes,
            ) = result
            assert isinstance(projects, list)
            assert isinstance(profiles, list)
            assert isinstance(glossary_entries, list)
            if self._allow_initial_project_restore and self._project_id is None and projects:
                self._allow_initial_project_restore = False
                first_project = projects[0]
                if isinstance(first_project, Project) and first_project.id is not None:
                    self._project_id = first_project.id
                    self.project_ready.emit(first_project.id)
                    self.refresh()
                    return
            self._allow_initial_project_restore = False
            if not self._notes_dirty:
                self._notes.setPlainText(str(notes))
                self._notes_dirty = False
            self._populate(
                projects,
                profiles,
                project,
                active_profile,
                glossary_entries,
                deletion_summary,
            )
        elif action == "save_notes":
            self._notes_dirty = False
            self._notes_status.setText(self._i18n.tr("Notes saved."))
            self._notify_settings_changed()
        elif action == "import_files":
            assert isinstance(result, tuple)
            job_id, imported, errors = result
            if self._project_id is None:
                self._project_id = job_id
                self.project_ready.emit(self._project_id)
                self.refresh()
            for document, segments in imported:
                self.document_ready.emit(document.id, document.name, len(segments))
            self._status.setText(
                self._i18n.tr("Files imported.")
                if not errors
                else safe_error_message("; ".join(errors))
            )
            self._notify_settings_changed()
        elif action == "create_project":
            assert isinstance(result, Project)
            assert result.id is not None
            self._project_id = result.id
            self._status.setText(f"Job {result.name!r} created.")
            self.project_ready.emit(result.id)
            self.refresh()
        elif action == "select_active_profile":
            assert isinstance(result, Project)
            self._status.setText(f"Selected model set for project {result.name!r}.")
            self._notify_settings_changed()
            self.refresh()
        elif action == "clear_active_profile":
            assert isinstance(result, Project)
            self._status.setText(f"Selected model cleared for project {result.name!r}.")
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
        elif action == "delete_project":
            if result is None:
                self._handle_error("Job was not found.")
                return
            assert isinstance(result, Path)
            deleted_id = self._project_id
            self._project_id = None
            self._deletion_summary_data = None
            self._delete_confirmation.clear()
            self._status.setText(self._i18n.tr("Job deleted. Recovery backup retained."))
            if deleted_id is not None:
                self.project_deleted.emit(deleted_id)
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
        deletion_summary: object,
    ) -> None:
        assert isinstance(project, Project | None)
        assert isinstance(active_profile, ModelProfile | None)
        assert isinstance(deletion_summary, ProjectDeletionSummary | None)
        self._deletion_summary_data = deletion_summary
        self._project_combo.clear()
        for candidate in projects:
            assert isinstance(candidate, Project)
            assert candidate.id is not None
            self._project_combo.addItem(candidate.name, candidate.id)
        if self._project_id is not None:
            index = self._project_combo.findData(self._project_id)
            if index >= 0:
                self._project_combo.setCurrentIndex(index)

        if deletion_summary is not None:
            self._delete_summary_label.setText(
                f"{deletion_summary.project_name}: "
                f"{deletion_summary.source_documents} source document(s), "
                f"{deletion_summary.segments} segment(s), "
                f"{deletion_summary.translation_runs} translation session(s), "
                f"{deletion_summary.glossary_entries} glossary entr(y/ies). "
                f"Busy: {deletion_summary.running_runs} running session(s), "
                f"{deletion_summary.active_processing_leases} translating segment(s).",
            )
        else:
            self._delete_summary_label.setText("")
            self._delete_confirmation.clear()

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
            self._active_profile_label.setText("Selected model: none")
        else:
            self._active_profile_label.setText("")
        self._has_project = project is not None
        self._has_profiles = bool(profiles)
        self._has_active_profile = active_profile is not None
        self._refresh_profile_guidance()

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
        self._status.setText(f"Error: {safe_error_message(error)}")

    def _refresh_profile_guidance(self) -> None:
        """Keep the active-profile setup action aligned with current state."""
        if not self._has_project or self._has_active_profile:
            self._profile_setup_hint.hide()
            self._open_settings.hide()
            return
        if self._has_profiles:
            source = "Choose a Model above, then select Set Model."
            self._open_settings.hide()
        else:
            source = (
                "Create a Provider and Model in Providers, then select the model in Translation."
            )
            self._open_settings.show()
        self._profile_setup_hint.setText(self._i18n.tr(source))
        self._profile_setup_hint.show()

    def import_files(self, paths: list[Path]) -> None:
        if self._project_id is None:
            self._project_name.setText(paths[0].stem if paths else "Translation")
            name = self._project_name.text().strip() or "Translation"
        else:
            name = ""
        project_id = self._project_id
        source = self._source_language.text().strip() or "ja"
        target = self._target_language.text().strip() or "zh"

        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                job_id = project_id
                if job_id is None:
                    job = facade.create_job(
                        name=name, source_language=source, target_language=target
                    )
                    job_id = job.id
                if job_id is None:
                    raise ValueError("Job could not be created.")
                imported, errors = [], []
                for path in paths:
                    try:
                        imported.append(facade.import_document(job_id, path))
                    except Exception as exc:
                        errors.append(safe_error_message(exc))
                return job_id, imported, errors

        self._submit("import_files", task)

    def _on_save_notes(self) -> None:
        if self._project_id is None:
            self._handle_error("Create or select a Job first.")
            return
        project_id, content = self._project_id, self._notes.toPlainText()

        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.set_notes(project_id, content)

        self._submit("save_notes", task)
