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

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from transrealm.application.context import ContextSource
from transrealm.application.preset_templates import current_preset
from transrealm.application.prompt_library_service import NamedPrompt
from transrealm.application.translation_facade import TranslationFacade
from transrealm.application.workbench import SegmentProgress, presented_parameters
from transrealm.domain.model_profile import ModelCapability, ModelCapabilityError, ModelProfile
from transrealm.domain.prompt_override import PromptOverride
from transrealm.domain.segment import SourceDocument
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.ui.i18n import LanguageManager
from transrealm.ui.page_base import WorkerPage, safe_error_message
from transrealm.ui.project_page import ProjectPage
from transrealm.ui.workbench import (
    WorkbenchParamEditor,
    WorkbenchPromptEditor,
    WorkbenchRevisionEditor,
)
from transrealm.ui.worker import ServiceWorker, TranslationWorker


class TranslationPage(WorkerPage):
    """Unified Job/files, context, translation and revision workspace."""

    request_project_setup = Signal()
    request_settings_setup = Signal()
    request_prompts_setup = Signal()

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
        self._running = False
        self._deferred_document: tuple[int, str, int] | None = None
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
        self.setAcceptDrops(True)
        self._job_controls = ProjectPage(
            worker, db_path=db_path, app_version=app_version, i18n=self._i18n
        )
        self._job_controls.project_ready.connect(self.set_project)
        self._job_controls.project_deleted.connect(lambda _: self.clear_project())
        self._job_controls.document_ready.connect(self.set_document)
        self._job_controls.project_settings_changed.connect(self.set_project)
        self._job_controls.request_settings_setup.connect(self.request_settings_setup.emit)
        layout.addWidget(self._job_controls)
        self._models: list[ModelProfile] = []
        self._prompt_texts: dict[int, str] = {}
        self._templates: list[NamedPrompt] = []
        overview_section = QGroupBox("Translation", self)
        overview_section.setObjectName("translation-controls")
        overview_layout = QVBoxLayout(overview_section)
        self._status = QLabel("No document imported.", self)
        self._status.setObjectName("status-banner")
        self._status.setWordWrap(True)
        overview_layout.addWidget(self._status)

        self._active_profile_label = QLabel("", self)
        self._active_profile_label.setWordWrap(True)
        overview_layout.addWidget(self._active_profile_label)
        selectors = QHBoxLayout()
        self._provider_combo = QComboBox(self)
        self._provider_combo.setObjectName("provider-selector")
        self._model_combo = QComboBox(self)
        self._model_combo.setObjectName("model-selector")
        self._prompt_combo = QComboBox(self)
        self._prompt_combo.setObjectName("prompt-selector")
        for label, combo in (
            ("Provider", self._provider_combo),
            ("Model", self._model_combo),
            ("Prompt", self._prompt_combo),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(label, self))
            column.addWidget(combo)
            selectors.addLayout(column)
        overview_layout.addLayout(selectors)
        self._manage_prompts = QPushButton("Manage prompts…", self)
        self._manage_prompts.clicked.connect(self.request_prompts_setup.emit)
        overview_layout.addWidget(self._manage_prompts)
        self._provider_combo.activated.connect(self._on_provider_selected)
        self._model_combo.activated.connect(self._on_model_selected)
        self._prompt_combo.activated.connect(self._on_prompt_selected)
        doc_row = QHBoxLayout()
        doc_row.addWidget(QLabel("Document:", self))
        self._document_combo = QComboBox(self)
        doc_row.addWidget(self._document_combo)
        overview_layout.addLayout(doc_row)

        form = QHBoxLayout()
        self._translate = QPushButton("Translate", self)
        self._cancel = QPushButton("Stop", self)
        self._cancel.setEnabled(False)
        self._export = QPushButton("Export file…", self)
        form.addWidget(self._translate)
        form.addWidget(self._cancel)
        form.addWidget(self._export)
        overview_layout.addLayout(form)

        self._config_missing_label = QLabel("", self)
        self._config_missing_label.setWordWrap(True)
        self._config_missing_label.hide()
        overview_layout.addWidget(self._config_missing_label)

        self._set_active_profile = QPushButton("Choose model…", self)
        self._set_active_profile.hide()
        overview_layout.addWidget(self._set_active_profile)
        self._configure_settings = QPushButton("Configure Providers…", self)
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
        workbench_layout.addWidget(QLabel("Translation history:", self._workbench_container))
        self._revision_history_list = QListWidget(self._workbench_container)
        self._revision_history_list.setObjectName("revision-history")
        workbench_layout.addWidget(self._revision_history_list)
        revision_actions = QHBoxLayout()
        self._use_revision = QPushButton("Use selected translation", self._workbench_container)
        self._use_revision.setObjectName("use-selected-revision")
        self._use_revision.setEnabled(False)
        revision_actions.addWidget(self._use_revision)
        self._retry_failed = QPushButton("Retry failed segment", self._workbench_container)
        self._retry_failed.setObjectName("retry-failed-segment")
        self._retry_failed.setEnabled(False)
        revision_actions.addWidget(self._retry_failed)
        self._retranslate = QPushButton("Retranslate selected segment", self)
        self._retranslate.clicked.connect(self._on_retranslate)
        revision_actions.addWidget(self._retranslate)
        workbench_layout.addLayout(revision_actions)
        self._param_host = QWidget(self._workbench_container)
        self._param_layout = QVBoxLayout(self._param_host)
        self._param_layout.setContentsMargins(0, 0, 0, 0)
        advanced = QGroupBox("Advanced settings", self)
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.addWidget(self._param_host)
        advanced.toggled.connect(self._param_host.setVisible)
        self._param_host.hide()
        workbench_layout.addWidget(advanced)
        self._prompt_host = QWidget(self._workbench_container)
        self._prompt_layout = QVBoxLayout(self._prompt_host)
        self._prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_settings = QGroupBox("Edit current prompt", self)
        prompt_settings.setCheckable(True)
        prompt_settings.setChecked(False)
        prompt_layout = QVBoxLayout(prompt_settings)
        prompt_layout.addWidget(self._prompt_host)
        prompt_settings.toggled.connect(self._prompt_host.setVisible)
        self._prompt_host.hide()
        workbench_layout.addWidget(prompt_settings)
        self._segment_progress = QListWidget(self._workbench_container)
        workbench_layout.addWidget(self._segment_progress)
        self._revision_host = QWidget(self._workbench_container)
        self._revision_layout = QVBoxLayout(self._revision_host)
        self._revision_layout.setContentsMargins(0, 0, 0, 0)
        workbench_layout.addWidget(self._revision_host)
        self._workbench_container.hide()
        layout.addWidget(overview_section)
        self._context_preview = QPlainTextEdit(self)
        self._context_preview.setReadOnly(True)
        self._context_preview.setObjectName("context-preview")
        self._context_preview.setMaximumHeight(120)
        workbench_layout.addWidget(QLabel("Context", self))
        workbench_layout.addWidget(self._context_preview)
        layout.addWidget(self._workbench_container)

        # Keep the source/editor next to the segment list; lower-frequency
        # history/context/settings live in internal tabs of the same workspace.
        detail_tabs = QTabWidget(self._workbench_container)
        detail_tabs.setMinimumHeight(280)
        editor_panel = QWidget(detail_tabs)
        editor_layout = QVBoxLayout(editor_panel)
        for widget in (self._segment_detail, self._revision_host):
            workbench_layout.removeWidget(widget)
            editor_layout.addWidget(widget)
        detail_tabs.addTab(editor_panel, "Current translation")
        history_panel = QWidget(detail_tabs)
        history_layout = QVBoxLayout(history_panel)
        workbench_layout.removeWidget(self._revision_history_list)
        history_layout.addWidget(self._revision_history_list)
        workbench_layout.removeItem(revision_actions)
        history_layout.addLayout(revision_actions)
        detail_tabs.addTab(history_panel, "Translation history:")
        context_panel = QWidget(detail_tabs)
        context_layout = QVBoxLayout(context_panel)
        workbench_layout.removeWidget(self._context_preview)
        context_layout.addWidget(self._context_preview)
        detail_tabs.addTab(context_panel, "Context")
        settings_panel = QWidget(detail_tabs)
        settings_layout = QVBoxLayout(settings_panel)
        for widget in (advanced, prompt_settings):
            workbench_layout.removeWidget(widget)
            settings_layout.addWidget(widget)
        # Keep the supported editor hook internal; prompt management has one page.
        prompt_settings.hide()
        detail_tabs.addTab(settings_panel, "Advanced settings")
        workbench_layout.removeWidget(self._segment_progress)
        self._segment_progress.setMaximumWidth(340)
        content_row = QHBoxLayout()
        content_row.addWidget(self._segment_progress, 1)
        content_row.addWidget(detail_tabs, 2)
        workbench_layout.addLayout(content_row)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        overview_layout.addWidget(self._progress)

        self._translate.clicked.connect(self._on_translate)
        self._cancel.clicked.connect(self._on_cancel)
        self._export.clicked.connect(self._on_export)
        self._set_active_profile.clicked.connect(self._on_request_project_setup)
        self._configure_settings.clicked.connect(self._on_request_settings_setup)
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
        if self._project_id != project_id:
            self._document_id = None
            self._allow_initial_document_restore = self._project_id is None
            self._selected_workbench_id = None
            self._clear_revision_editor()
            self._clear_revision_history()
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
        project_id, current = self._project_id, self._document_id
        allow_restore = self._allow_initial_document_restore

        def task() -> object:
            if project_id is None:
                return None
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                project = facade.open_job(project_id)
                if project is None:
                    return None
                profile = facade.active_profile(project_id)
                override = (
                    facade.prompt_override(profile.id)
                    if profile is not None and profile.id is not None
                    else None
                )
                documents = facade.list_documents(project_id)
                effective = current if any(doc.id == current for doc in documents) else None
                if effective is None and allow_restore and documents:
                    effective = documents[0].id
                return (
                    project,
                    profile,
                    facade.progress(effective) if effective is not None else [],
                    override,
                    documents,
                    effective,
                    facade.available_providers(),
                    facade.available_models(),
                    facade.available_prompts(),
                )

        return task

    def set_document(self, source_document_id: int, name: str, count: int) -> None:
        """Record the imported document and surface its segment count."""
        if self._running:
            if source_document_id != self._document_id:
                self._deferred_document = (source_document_id, name, count)
            return
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
        if self._active_profile_id is None:
            self._on_config_missing("Choose a Provider and model before translating.")
            self._translation_worker.start_translate_auto.emit(self._project_id, self._document_id)
            return
        self._set_running(True)
        self._terminal_error = False
        self._stop_clicked = False
        self._status.setText(self._i18n.tr("Translating…"))
        self._hide_config_missing()
        params = self._param_editor.values() if self._param_editor is not None else None
        self._translation_worker.start_translate_workbench.emit(
            self._project_id,
            self._document_id,
            self._active_profile_id,
            params,
        )

    def _set_running(self, running: bool) -> None:
        self._running = running
        self._translate.setEnabled(
            not running and self._document_id is not None and self._active_profile_id is not None
        )
        self._cancel.setEnabled(running)
        self._export.setEnabled(not running and self._document_id is not None)
        self._document_combo.setEnabled(not running and self._document_combo.count() > 0)
        for widget in (
            self._provider_combo,
            self._model_combo,
            self._prompt_combo,
            self._job_controls,
            self._param_host,
            self._prompt_host,
            self._revision_host,
        ):
            widget.setEnabled(not running)
        self._sync_revision_actions()

    def _on_cancel(self) -> None:
        self._stop_clicked = True
        self._status.setText(self._i18n.tr("Stopping after the current segment…"))
        self._translation_worker.request_stop()

    def translate(self) -> None:
        """Programmatic entry point mirroring the Translate button (no dialog)."""
        self._on_translate()

    def _on_config_missing(self, reason: str) -> None:
        self._set_running(False)
        self._status.setText("Translation needs configuration.")
        self._config_missing_label.setText(reason)
        self._config_missing_label.setProperty("transrealm_i18n_source", reason)
        self._config_missing_label.setText(self._i18n.tr(reason))
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
            self._status.setText(f"{stable_key}: {self._i18n.tr('Completed')}")

    def _on_segment_failed(self, stable_key: str, error: str) -> None:
        self._terminal_error = True
        self._status.setText(f"{stable_key}: {safe_error_message(error)}")

    def _on_finished(self) -> None:
        self._set_running(False)
        deferred = getattr(self, "_deferred_document", None)
        if deferred is not None:
            self._deferred_document = None
            self.set_document(*deferred)
        if not self._config_missing_label.isHidden():
            return
        self.refresh()
        if getattr(self, "_terminal_error", False):
            return
        message = (
            "Translation stopped. Resume to continue."
            if getattr(self, "_stop_clicked", False)
            else "Translation finished."
        )
        self._status.setText(self._i18n.tr(message))

    def _on_failed(self, error: str) -> None:
        self._terminal_error = True
        self._set_running(False)
        self._status.setText(f"{self._i18n.tr('Translation failed')}: {safe_error_message(error)}")

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
        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                facade.export_document(document_id, target_path)
            return None

        return task

    def _handle_action(self, action: str, result: object) -> None:
        if action == "refresh":
            if result is None:
                self._document_id = None
                self._document_combo.clear()
                self._hide_workbench()
                return
            assert isinstance(result, tuple)
            (
                project,
                profile,
                progress,
                override,
                documents,
                effective,
                providers,
                models,
                templates,
            ) = result
            self._allow_initial_document_restore = False
            self._active_profile_id = project.active_profile_id
            self._models = models
            self._templates = templates
            self._provider_combo.clear()
            for provider in providers:
                self._provider_combo.addItem(provider.name, provider.id)
            if profile is not None:
                self._provider_combo.setCurrentIndex(
                    self._provider_combo.findData(profile.provider_connection_id)
                )
                self._active_profile_label.setText(f"Model: {profile.name} — {profile.model_id}")
                self._hide_config_missing()
            else:
                self._active_profile_label.setText("")
                self._on_config_missing(
                    "Choose a Provider and model. Configure Providers if none exist."
                )
            self._populate_model_selector()
            self._populate_prompt_selector(override)
            self._populate_documents(documents, effective, len(progress))
            self._populate_workbench(profile, progress, override)
            self._set_running(self._running)
        elif action == "select_model":
            self._job_controls.refresh()
            self.refresh()
        elif action in {"save_override", "clear_override"}:
            self._clear_prompt_editor()
            self._status.setText(
                self._i18n.tr("Prompt saved." if action == "save_override" else "Prompt cleared.")
            )
            self.refresh()
        elif action in {
            "save_revision",
            "lock_revision",
            "unlock_revision",
            "set_current_revision",
            "retry_failed",
        }:
            messages = {
                "save_revision": "Manual translation saved.",
                "lock_revision": "Current translation locked.",
                "unlock_revision": "Current translation unlocked.",
                "set_current_revision": "Current translation selected.",
                "retry_failed": "Failed segment requeued.",
            }
            self._status.setText(self._i18n.tr(messages[action]))
            if action == "set_current_revision":
                self._clear_revision_editor()
            self.refresh()
        elif action == "load_revision_history":
            assert isinstance(result, tuple)
            segment_id, revisions = result
            if segment_id != self._selected_segment_id():
                return
            self._revision_history_segment_id = segment_id
            self._revision_entries = revisions
            self._render_revision_history()
        elif action == "context_preview":
            assert isinstance(result, tuple)
            segment_id, manifest = result
            if segment_id == self._selected_segment_id():
                lines = [
                    f"{self._i18n.tr('Available context budget')}: {manifest.budget.available}"
                ]
                for candidate in manifest.selected:
                    if candidate.source != ContextSource.CURRENT_SEGMENT:
                        lines.append(candidate.content)
                self._context_preview.setPlainText("\n\n".join(lines))
        elif action == "export":
            self._status.setText(self._i18n.tr("Export written."))
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
        if previous_id is None and items and isinstance(active_profile, ModelProfile):
            previous_id = items[0].segment_id
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
                f"Model: {active_profile.name} — {active_profile.model_id} "
                "(no capability snapshot — parameters unavailable).",
            )
            self._clear_param_editor()
            self._clear_prompt_editor()
            return

        supported = ", ".join(presented_parameters(capability)) or "(none)"
        self._workbench_info.setText(
            f"Model: {active_profile.name} — {active_profile.model_id} · "
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
                if item.attempt_error:
                    label += f": {safe_error_message(item.attempt_error)}"
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
            with TranslationFacade(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return segment_id, runs.revisions(segment_id)

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
                label = f"{self._i18n.tr('Translation')} {revision.id}: "
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
        self._retranslate.setEnabled(
            selected is not None
            and not selected.revision_locked
            and not self._running
            and self._active_profile_id is not None
        )
        retry_enabled = selected is not None and selected.status == "failed" and not self._running
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
            with TranslationFacade(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.select_revision(segment_id, revision_id)

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
            with TranslationFacade(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.retry_failed(segment_id)

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
            with TranslationFacade(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.save_manual_revision(segment_id, text)

        return task

    def _on_lock_revision(self) -> None:
        selected = self._selected_segment_item()
        if selected is None:
            self._handle_error("Select a segment to lock.")
            return
        self._submit("lock_revision", self._lock_revision_task(selected.segment_id))

    def _lock_revision_task(self, segment_id: int) -> Callable[[], object]:
        def task() -> object:
            with TranslationFacade(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.lock_current(segment_id)

        return task

    def _on_unlock_revision(self) -> None:
        selected = self._selected_segment_item()
        if selected is None:
            self._handle_error("Select a segment to unlock.")
            return
        self._submit("unlock_revision", self._unlock_revision_task(selected.segment_id))

    def _unlock_revision_task(self, segment_id: int) -> Callable[[], object]:
        def task() -> object:
            with TranslationFacade(
                self._db_path,
                app_version=self._app_version,
            ) as runs:
                return runs.unlock_current(segment_id)

        return task

    def _on_save_override(self, text: str) -> None:
        if self._active_profile_id is None:
            self._handle_error("No active profile to save the override to.")
            return
        profile_id = self._active_profile_id
        self._submit("save_override", self._save_override_task(profile_id, text))

    def _save_override_task(self, profile_id: int, text: str) -> Callable[[], object]:
        def task() -> object:
            with TranslationFacade(
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
            with TranslationFacade(
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
        self._status.setText(f"Error: {safe_error_message(error)}")

    def _populate_model_selector(self) -> None:
        provider_id = self._provider_combo.currentData()
        self._model_combo.clear()
        for model in self._models:
            if model.provider_connection_id == provider_id:
                self._model_combo.addItem(f"{model.model_id} — {model.name}", model.id)
        self._model_combo.setCurrentIndex(self._model_combo.findData(self._active_profile_id))

    def _on_provider_selected(self, _index: int) -> None:
        self._populate_model_selector()
        if self._model_combo.count():
            self._model_combo.setCurrentIndex(0)
            self._on_model_selected(0)

    def _on_model_selected(self, _index: int) -> None:
        project_id, model_id = self._project_id, self._model_combo.currentData()
        if self._running or project_id is None or not isinstance(model_id, int):
            return

        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return facade.select_active_profile(project_id, model_id)

        self._submit("select_model", task)

    def _populate_prompt_selector(self, override: object) -> None:
        self._prompt_combo.clear()
        self._prompt_combo.addItem(self._i18n.tr("Preset prompt"), "preset")
        selected = 0
        for template in self._templates:
            self._prompt_combo.addItem(template.name, template.template_id)
            if isinstance(override, PromptOverride) and (
                template.template_text == override.template_text
                and template.parent_template_version == override.parent_template_version
            ):
                selected = self._prompt_combo.count() - 1
        if isinstance(override, PromptOverride) and selected == 0:
            self._prompt_combo.addItem(self._i18n.tr("Model prompt"), "current")
            selected = self._prompt_combo.count() - 1
        self._prompt_combo.setCurrentIndex(selected)

    def _on_prompt_selected(self, _index: int) -> None:
        profile_id = self._active_profile_id
        if profile_id is None or self._running:
            return
        template_id = self._prompt_combo.currentData()
        if not isinstance(template_id, str) or template_id == "current":
            return

        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                facade.select_prompt(profile_id, None if template_id == "preset" else template_id)
            return None

        self._submit("clear_override" if template_id == "preset" else "save_override", task)

    def _load_context_preview(self, segment_id: int) -> None:
        profile_id = self._active_profile_id
        if profile_id is None:
            return

        def task() -> object:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                return segment_id, facade.context_preview(segment_id, profile_id)

        self._submit("context_preview", task)

    def import_file(self, path: Path) -> None:
        self._job_controls.import_file(path)

    def _on_retranslate(self) -> None:
        selected = self._selected_segment_item()
        if (
            self._running
            or selected is None
            or selected.revision_locked
            or self._active_profile_id is None
            or self._project_id is None
            or self._document_id is None
        ):
            return
        self._terminal_error = False
        self._stop_clicked = False
        self._set_running(True)
        self._translation_worker.start_translate_single.emit(
            self._project_id,
            self._document_id,
            self._active_profile_id,
            selected.segment_id,
            self._param_editor.values() if self._param_editor is not None else None,
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if not self._running and mime is not None and mime.hasUrls():
            if all(url.isLocalFile() for url in mime.urls()):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if not self._running and mime is not None and mime.hasUrls():
            paths = [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]
            if paths:
                self._job_controls.import_files(paths)
                event.acceptProposedAction()
