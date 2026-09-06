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

from PySide6.QtCore import QSignalBlocker, Qt, Signal
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
from transrealm.application.exporter import (
    AssExporter,
    JsonExporter,
    SrtExporter,
    SsaExporter,
    TxtExporter,
    VttExporter,
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
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.ui.i18n import LanguageManager
from transrealm.ui.page_base import WorkerPage, safe_error_message
from transrealm.ui.workbench import (
    WorkbenchParamEditor,
    WorkbenchPromptEditor,
    WorkbenchRevisionEditor,
)
from transrealm.ui.worker import ServiceWorker, TranslationWorker


class TranslationPage(WorkerPage):
    """Auto-mode translation journey: import -> translate -> status -> export.

    M01 ships the auto mode. The active ModelProfile is resolved from the
    project on the translation worker thread (never from a manual picker), and
    when the project has no active profile the page shows a single recoverable
    step — a button that jumps to the Project tab. The workbench surface
    (explicit profile/parameter selection) arrives in P1-T03-M02.
    """

    request_project_setup = Signal()
    request_settings_setup = Signal()

    def __init__(
        self,
        worker: ServiceWorker,
        *,
        translation_worker: TranslationWorker,
        db_path: Path,
        app_version: str,
        i18n: LanguageManager | None = None,
    ) -> None:
        super().__init__(worker)
        self._translation_worker = translation_worker
        self._db_path = db_path
        self._app_version = app_version
        self._i18n = i18n or LanguageManager(parent=self)
        self._project_id: int | None = None
        self._document_id: int | None = None
        self._document_name = ""
        self._document_format = "txt"
        self._mode = MODE_AUTO
        self._running = False
        self._active_profile_id: int | None = None
        self._param_editor: WorkbenchParamEditor | None = None
        self._prompt_editor: WorkbenchPromptEditor | None = None
        self._revision_editor: WorkbenchRevisionEditor | None = None
        self._workbench_progress: list[SegmentProgress] = []
        self._selected_workbench_id: int | None = None
        self._revision_history_segment_id: int | None = None
        self._revision_entries: list[TranslationRevision] = []
        self._allow_initial_document_restore = True

        layout = QVBoxLayout(self)
        overview_section = QGroupBox("Auto overview", self)
        overview_section.setObjectName("auto-overview-section")
        overview_layout = QVBoxLayout(overview_section)
        self._status = QLabel("No document imported.", self)
        self._status.setObjectName("status-banner")
        self._status.setWordWrap(True)
        overview_layout.addWidget(self._status)

        self._mode_label = QLabel("Mode: auto", self)
        overview_layout.addWidget(self._mode_label)
        self._active_profile_label = QLabel("", self)
        overview_layout.addWidget(self._active_profile_label)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Interaction mode:", self))
        self._mode_switch = QComboBox(self)
        self._mode_switch.addItem("Auto", MODE_AUTO)
        self._mode_switch.addItem("Workbench", MODE_WORKBENCH)
        self._mode_switch.setProperty("transrealm_i18n_static_items", True)
        mode_row.addWidget(self._mode_switch)
        overview_layout.addLayout(mode_row)

        doc_row = QHBoxLayout()
        doc_row.addWidget(QLabel("Document:", self))
        self._document_combo = QComboBox(self)
        doc_row.addWidget(self._document_combo)
        overview_layout.addLayout(doc_row)

        form = QFormLayout()
        self._translate = QPushButton("Translate", self)
        self._cancel = QPushButton("Cancel", self)
        self._cancel.setEnabled(False)
        self._export = QPushButton("Export file…", self)
        form.addRow(self._translate)
        form.addRow(self._cancel)
        form.addRow(self._export)
        overview_layout.addLayout(form)

        self._config_missing_label = QLabel("", self)
        self._config_missing_label.setWordWrap(True)
        self._config_missing_label.hide()
        overview_layout.addWidget(self._config_missing_label)

        self._set_active_profile = QPushButton("Set active profile…", self)
        self._set_active_profile.hide()
        overview_layout.addWidget(self._set_active_profile)
        self._configure_settings = QPushButton("Configure Connection and Model Profile…", self)
        self._configure_settings.hide()
        overview_layout.addWidget(self._configure_settings)

        # Workbench surface (P1-T03-M02): real Segment/Attempt progress, the
        # active Profile's capability, and a parameter editor presenting only
        # the capability-supported parameters. Hidden in auto mode.
        self._workbench_container = QWidget(self)
        workbench_layout = QVBoxLayout(self._workbench_container)
        workbench_layout.setContentsMargins(0, 0, 0, 0)
        self._workbench_info = QLabel("", self._workbench_container)
        self._workbench_info.setWordWrap(True)
        workbench_layout.addWidget(self._workbench_info)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter status:", self._workbench_container))
        self._workbench_filter = QComboBox(self._workbench_container)
        self._workbench_filter.setObjectName("workbench-status-filter")
        self._workbench_filter.addItem("All statuses", "all")
        self._workbench_filter.addItem("Pending", "pending")
        self._workbench_filter.addItem("Processing", "processing")
        self._workbench_filter.addItem("Completed", "completed")
        self._workbench_filter.addItem("Failed", "failed")
        self._workbench_filter.setProperty("transrealm_i18n_static_items", True)
        filter_row.addWidget(self._workbench_filter)
        workbench_layout.addLayout(filter_row)
        self._segment_detail = QLabel("No segment selected.", self._workbench_container)
        self._segment_detail.setObjectName("segment-detail")
        self._segment_detail.setProperty("transrealm_i18n_dynamic", True)
        self._segment_detail.setWordWrap(True)
        workbench_layout.addWidget(self._segment_detail)
        workbench_layout.addWidget(QLabel("Revision history:", self._workbench_container))
        self._revision_history_list = QListWidget(self._workbench_container)
        self._revision_history_list.setObjectName("revision-history")
        workbench_layout.addWidget(self._revision_history_list)
        revision_actions = QHBoxLayout()
        self._use_revision = QPushButton("Use selected revision", self._workbench_container)
        self._use_revision.setObjectName("use-selected-revision")
        self._use_revision.setEnabled(False)
        revision_actions.addWidget(self._use_revision)
        self._retry_failed = QPushButton("Retry failed segment", self._workbench_container)
        self._retry_failed.setObjectName("retry-failed-segment")
        self._retry_failed.setEnabled(False)
        revision_actions.addWidget(self._retry_failed)
        workbench_layout.addLayout(revision_actions)
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
        layout.addWidget(overview_section)
        layout.addWidget(self._workbench_container)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        overview_layout.addWidget(self._progress)

        self._translate.clicked.connect(self._on_translate)
        self._cancel.clicked.connect(self._on_cancel)
        self._export.clicked.connect(self._on_export)
        self._set_active_profile.clicked.connect(self._on_request_project_setup)
        self._configure_settings.clicked.connect(self._on_request_settings_setup)
        self._mode_switch.activated.connect(self._on_mode_switch)
        self._document_combo.activated.connect(self._on_document_selected)
        self._workbench_filter.currentIndexChanged.connect(self._on_workbench_filter_changed)
        self._segment_progress.itemSelectionChanged.connect(self._on_segment_selected)
        self._revision_history_list.itemSelectionChanged.connect(
            self._on_revision_history_selected,
        )
        self._use_revision.clicked.connect(self._on_use_revision)
        self._retry_failed.clicked.connect(self._on_retry_failed)

        translation_worker.progress.connect(self._on_progress)
        translation_worker.segment_completed.connect(self._on_segment_completed)
        translation_worker.segment_failed.connect(self._on_segment_failed)
        translation_worker.config_missing.connect(self._on_config_missing)
        translation_worker.finished.connect(self._on_finished)
        translation_worker.failed.connect(self._on_failed)
        self._i18n.language_changed.connect(self._on_language_changed)
        self._i18n.bind_tree(self)

    def set_project(self, project_id: int) -> None:
        """Record the active project id and refresh its mode/profile status."""
        self._project_id = project_id
        self.refresh()

    def clear_project(self) -> None:
        """Clear the project context after the active Project is deleted."""
        self._project_id = None
        self._document_id = None
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
        allow_initial_restore = self._allow_initial_document_restore

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
                # kept only when it belongs to the selected project. On a fresh
                # shell reopen, select the first persisted document so the user
                # sees the same project journey without leaking a stale id from
                # another project.
                if current is not None and any(doc.id == current for doc in documents):
                    effective_id = current
                elif current is None and allow_initial_restore and documents:
                    effective_id = documents[0].id
                if effective_id is not None:
                    progress = runs.list_segment_progress(source_document_id=effective_id)
            return project, active_profile, progress, override, documents, effective_id

        return task

    def set_document(self, source_document_id: int, name: str, count: int) -> None:
        """Record the imported document and surface its segment count."""
        self._document_id = source_document_id
        self._document_name = name
        self._document_format = Path(name).suffix.lstrip(".").lower() or "txt"
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
        self._document_format = "txt"
        if effective_id is not None:
            for doc in docs:
                if doc.id == effective_id:
                    self._document_name = doc.name
                    self._document_format = doc.format
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
        if self._active_profile_id is None:
            self._translation_worker.start_translate_auto.emit(
                self._project_id,
                self._document_id,
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
        self._sync_revision_actions()

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
        self._configure_settings.show()
        self._translate.setEnabled(False)

    def _hide_config_missing(self) -> None:
        self._config_missing_label.hide()
        self._set_active_profile.hide()
        self._configure_settings.hide()
        if not self._running:
            self._translate.setEnabled(True)

    def _on_request_project_setup(self) -> None:
        self.request_project_setup.emit()

    def _on_request_settings_setup(self) -> None:
        self.request_settings_setup.emit()

    def _on_progress(self, done: int, total: int, stable_key: str) -> None:
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(done)
        if total > 0 and self._running:
            self._status.setText(f"Translated {done}/{total} ({stable_key}).")

    def _on_segment_completed(self, stable_key: str, revision_id: int) -> None:
        if self._running:
            self._status.setText(f"Segment {stable_key} translated (revision {revision_id}).")

    def _on_segment_failed(self, stable_key: str, error: str) -> None:
        if self._running:
            self._status.setText(f"Segment {stable_key} failed: {safe_error_message(error)}")

    def _on_finished(self) -> None:
        self._set_running(False)
        if not self._config_missing_label.isHidden():
            return
        # The workbench progress list reflects the persisted state, so re-read
        # it after a run so the segments show their completed/failed outcome.
        if self._mode == MODE_WORKBENCH:
            self.refresh()
        # Replace progress or the placeholder status with a stable terminal
        # message. Late queued progress/completion signals are ignored because
        # _running is already false.
        self._status.setText("Translation finished.")

    def _on_failed(self, error: str) -> None:
        self._set_running(False)
        self._status.setText(f"Translation failed: {safe_error_message(error)}")

    def _on_export(self) -> None:
        if self._document_id is None:
            self._handle_error("Import a document first.")
            return
        suffix = f".{self._document_format}"
        default_name = Path(self._document_name or "translated").with_suffix(suffix).name
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export source file",
            default_name,
            f"{self._document_format.upper()} files (*{suffix});;All files (*)",
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
        document_format = self._document_format

        def task() -> object:
            exporter_types = {
                "txt": TxtExporter,
                "json": JsonExporter,
                "srt": SrtExporter,
                "ass": AssExporter,
                "ssa": SsaExporter,
                "vtt": VttExporter,
            }
            exporter_type = exporter_types.get(document_format)
            if exporter_type is None:
                raise ValueError(f"Unsupported document format: {document_format}")
            exporter = exporter_type(self._db_path, app_version=self._app_version)
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
            self._allow_initial_document_restore = False
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
                self._on_config_missing(
                    "Create a Connection and Model Profile in Settings, then set the "
                    "Profile active in Project.",
                )
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
        elif action == "load_revision_history":
            assert isinstance(result, tuple)
            segment_id, revisions = result
            if segment_id != self._selected_segment_id():
                return
            assert isinstance(revisions, list)
            self._revision_history_segment_id = segment_id
            self._revision_entries = [
                revision for revision in revisions if isinstance(revision, TranslationRevision)
            ]
            self._render_revision_history()
        elif action == "set_current_revision":
            self._status.setText("Current revision selected.")
            self.refresh()
        elif action == "retry_failed":
            self._status.setText("Failed segment requeued.")
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
        self._selected_workbench_id = previous_id
        self._render_workbench_list()
        self._restore_workbench_selection()
        selected = next(
            (item for item in items if item.segment_id == previous_id),
            None,
        )
        visible_ids = {item.segment_id for item in self._visible_workbench_progress()}
        if selected is not None and selected.segment_id in visible_ids:
            keep_draft = selected.segment_id == previous_id
            self._rebuild_revision_editor(
                selected,
                initial=revision_draft if keep_draft else None,
            )
        elif previous_id is None:
            self._clear_revision_editor()
            self._update_segment_detail(None)
        else:
            self._update_segment_detail(selected)
        if selected is not None:
            self._load_revision_history(selected.segment_id)
        else:
            self._clear_revision_history()

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

    def _visible_workbench_progress(self) -> list[SegmentProgress]:
        selected_status = self._workbench_filter.currentData()
        if selected_status in (None, "all"):
            return list(self._workbench_progress)
        return [item for item in self._workbench_progress if item.status == selected_status]

    def _render_workbench_list(self) -> None:
        visible = self._visible_workbench_progress()
        blocker = QSignalBlocker(self._segment_progress)
        try:
            self._segment_progress.clear()
            for item in visible:
                status = item.status
                if self._i18n.current_language != "en":
                    status = self._i18n.tr(item.status.capitalize())
                label = f"{item.stable_key}: {status}"
                if item.current_revision_id is not None:
                    label += f" (rev {item.current_revision_id})"
                if item.attempt_status is not None:
                    label += f" · attempt {item.attempt_status}"
                    if item.attempt_error:
                        label += f": {item.attempt_error}"
                self._segment_progress.addItem(label)
            if self._selected_workbench_id is not None:
                for index, item in enumerate(visible):
                    if item.segment_id == self._selected_workbench_id:
                        self._segment_progress.setCurrentRow(index)
                        break
        finally:
            del blocker

    def _on_workbench_filter_changed(self, _index: int) -> None:
        selected_id = self._selected_workbench_id
        if selected_id is None:
            selected_id = self._selected_segment_id()
        draft = self._revision_editor.translation() if self._revision_editor is not None else None
        self._selected_workbench_id = selected_id
        self._render_workbench_list()
        self._selected_workbench_id = selected_id
        self._restore_workbench_selection()
        selected = self._selected_segment_item()
        visible_ids = {item.segment_id for item in self._visible_workbench_progress()}
        if selected is None:
            self._clear_revision_editor()
            self._update_segment_detail(None)
        elif selected.segment_id in visible_ids:
            self._update_segment_detail(selected)
            self._rebuild_revision_editor(selected, initial=draft)
        else:
            # Keep the editor and its draft visible while a filter temporarily
            # hides the selected segment; clearing the filter restores it.
            self._update_segment_detail(selected)
        if selected is not None:
            self._load_revision_history(selected.segment_id)

    def _update_segment_detail(self, item: SegmentProgress | None) -> None:
        if item is None:
            self._segment_detail.setText(self._i18n.tr("No segment selected."))
            return
        current = item.revision_text if item.revision_text is not None else "(none)"
        self._segment_detail.setText(
            f"{self._i18n.tr('Source')}: {item.source_text}\n"
            f"{self._i18n.tr('Current translation')}: {current}",
        )

    def _restore_workbench_selection(self) -> None:
        if self._selected_workbench_id is None:
            return
        visible = self._visible_workbench_progress()
        for index, item in enumerate(visible):
            if item.segment_id == self._selected_workbench_id:
                blocker = QSignalBlocker(self._segment_progress)
                try:
                    self._segment_progress.setCurrentRow(index)
                finally:
                    del blocker
                return

    def _on_language_changed(self, _language: str) -> None:
        self._render_workbench_list()
        self._restore_workbench_selection()
        selected = self._selected_segment_item() if self._selected_workbench_id else None
        self._update_segment_detail(selected)
        self._render_revision_history()

    def _revision_history_task(
        self,
        segment_id: int,
    ) -> Callable[[], object]:
        def task() -> object:
            with TranslationRunService(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return segment_id, runs.list_revisions_for_segment(segment_id=segment_id)

        return task

    def _load_revision_history(self, segment_id: int) -> None:
        self._revision_history_segment_id = segment_id
        self._revision_entries = []
        self._render_revision_history()
        self._submit("load_revision_history", self._revision_history_task(segment_id))

    def _render_revision_history(self) -> None:
        blocker = QSignalBlocker(self._revision_history_list)
        try:
            self._revision_history_list.clear()
            selected = self._selected_segment_item()
            current_id = selected.current_revision_id if selected is not None else None
            for revision in self._revision_entries:
                label = f"{self._i18n.tr('Revision')} {revision.id}: "
                label += self._i18n.tr(revision.origin.capitalize())
                if revision.id == current_id:
                    label += f" · {self._i18n.tr('current')}"
                if revision.is_locked:
                    label += f" · {self._i18n.tr('locked')}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, revision.id)
                self._revision_history_list.addItem(item)
        finally:
            del blocker
        self._sync_revision_actions()

    def _clear_revision_history(self) -> None:
        self._revision_history_segment_id = None
        self._revision_entries = []
        self._revision_history_list.clear()
        self._sync_revision_actions()

    def _on_revision_history_selected(self) -> None:
        self._sync_revision_actions()

    def _sync_revision_actions(self) -> None:
        selected = self._selected_segment_item()
        retry_enabled = (
            selected is not None and selected.status == "failed" and not self._running
        )
        self._retry_failed.setEnabled(retry_enabled)
        history_item = self._revision_history_list.currentItem()
        revision_id = history_item.data(Qt.ItemDataRole.UserRole) if history_item else None
        self._use_revision.setEnabled(
            selected is not None
            and isinstance(revision_id, int)
            and revision_id != selected.current_revision_id
            and not self._running,
        )

    def _set_current_revision_task(
        self,
        segment_id: int,
        revision_id: int,
    ) -> Callable[[], object]:
        def task() -> object:
            with TranslationRunService(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.set_current_revision(
                    segment_id=segment_id,
                    revision_id=revision_id,
                )

        return task

    def _on_use_revision(self) -> None:
        selected = self._selected_segment_item()
        history_item = self._revision_history_list.currentItem()
        revision_id = history_item.data(Qt.ItemDataRole.UserRole) if history_item else None
        if selected is None or not isinstance(revision_id, int):
            self._handle_error("Select a revision first.")
            return
        self._submit(
            "set_current_revision",
            self._set_current_revision_task(selected.segment_id, revision_id),
        )

    def _retry_failed_task(self, segment_id: int) -> Callable[[], object]:
        def task() -> object:
            with TranslationRunService(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.retry_failed(segment_id=segment_id)

        return task

    def _on_retry_failed(self) -> None:
        selected = self._selected_segment_item()
        if selected is None or selected.status != "failed":
            self._handle_error("Select a failed segment to retry.")
            return
        self._submit("retry_failed", self._retry_failed_task(selected.segment_id))

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
        self._i18n.bind_tree(editor)

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
        self._i18n.bind_tree(editor)

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
        visible = self._visible_workbench_progress()
        if 0 <= row < len(visible):
            return visible[row]
        if self._selected_workbench_id is None:
            return None
        return next(
            (
                item
                for item in self._workbench_progress
                if item.segment_id == self._selected_workbench_id
            ),
            None,
        )

    def _selected_segment_id(self) -> int | None:
        item = self._selected_segment_item()
        return item.segment_id if item is not None else None

    def _on_segment_selected(self) -> None:
        """Show the manual translation editor for the newly selected segment."""
        selected = self._selected_segment_item()
        if selected is None:
            self._update_segment_detail(None)
            return
        self._selected_workbench_id = selected.segment_id
        self._update_segment_detail(selected)
        self._rebuild_revision_editor(selected)
        self._load_revision_history(selected.segment_id)

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
        self._i18n.bind_tree(editor)

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
        self._clear_revision_history()

    def _handle_error(self, error: str) -> None:
        # A failed mode change must not leave the selector showing a mode that
        # was never persisted; re-align it with the current project's mode.
        self._sync_mode_switch()
        self._status.setText(f"Error: {safe_error_message(error)}")
