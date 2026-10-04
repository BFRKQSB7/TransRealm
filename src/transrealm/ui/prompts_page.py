"""Preset viewing and named prompt copy management on the service worker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transrealm.application.preset_templates import ALLOWED_PLACEHOLDERS, current_preset
from transrealm.application.prompt_library_service import NamedPrompt, PromptLibraryService
from transrealm.domain.prompt_override import PromptOverride
from transrealm.ui.i18n import LanguageManager
from transrealm.ui.page_base import WorkerPage, safe_error_message
from transrealm.ui.workbench import WorkbenchPromptEditor
from transrealm.ui.worker import ServiceWorker


class PromptsPage(WorkerPage):
    configuration_changed = Signal()
    request_translation = Signal()

    def __init__(
        self,
        worker: ServiceWorker,
        *,
        db_path: Path,
        app_version: str,
        i18n: LanguageManager,
    ) -> None:
        super().__init__(worker)
        self._library = PromptLibraryService(db_path, app_version=app_version)
        self._i18n = i18n
        self._templates: dict[str, NamedPrompt] = {}
        self._draft = False
        self._dirty = False
        self._model_editor: WorkbenchPromptEditor | None = None
        self._preferred_model: int | None = None
        layout = QVBoxLayout(self)
        back = QPushButton("Back to Translation", self)
        back.clicked.connect(self.request_translation.emit)
        layout.addWidget(back, 0, Qt.AlignmentFlag.AlignRight)
        help_text = QLabel(
            "Copy a preset, edit the copy, then select it in Translation. "
            "Changes to a saved template take effect when you select it again.",
            self,
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self._status = QLabel("", self)
        self._status.setProperty("transrealm_i18n_dynamic", True)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._list = QListWidget(self)
        self._list.setMaximumHeight(160)
        layout.addWidget(self._list)
        self._name = QLineEdit(self)
        self._name.setPlaceholderText("Prompt name")
        layout.addWidget(self._name)
        self._editor = QPlainTextEdit(self)
        self._editor.setMinimumHeight(180)
        layout.addWidget(self._editor, 1)
        self._variables = QLabel(
            "Variables: " + ", ".join(f"${key}" for key in ALLOWED_PLACEHOLDERS),
            self,
        )
        self._variables.setProperty("transrealm_i18n_dynamic", True)
        self._variables.setWordWrap(True)
        layout.addWidget(self._variables)
        actions = QHBoxLayout()
        self._copy = QPushButton("Copy preset", self)
        self._save = QPushButton("Save prompt", self)
        self._delete = QPushButton("Delete prompt", self)
        for button in (self._copy, self._save, self._delete):
            actions.addWidget(button)
        layout.addLayout(actions)
        self._copy.clicked.connect(self._on_copy)
        self._save.clicked.connect(self._on_save)
        self._delete.clicked.connect(self._on_delete)
        self._list.currentItemChanged.connect(self._on_selected)
        self._name.textEdited.connect(self._mark_dirty)
        self._editor.textChanged.connect(self._mark_dirty)
        model_section = QGroupBox("Current model prompt", self)
        model_section.setCheckable(True)
        model_section.setChecked(False)
        model_layout = QVBoxLayout(model_section)
        self._models = QComboBox(model_section)
        model_layout.addWidget(self._models)
        self._model_host = QGroupBox(model_section)
        self._model_layout = QVBoxLayout(self._model_host)
        model_layout.addWidget(self._model_host)
        self._model_host.hide()
        model_section.toggled.connect(self._model_host.setVisible)
        self._models.activated.connect(self._load_model_prompt)
        layout.addWidget(model_section)
        layout.removeWidget(self._list)
        self._list.setMaximumHeight(16777215)
        layout.removeWidget(self._name)
        layout.removeWidget(self._editor)
        layout.removeWidget(self._variables)
        layout.removeItem(actions)
        layout.removeWidget(model_section)
        left = QWidget(self)
        left.setMinimumWidth(180)
        left.setMaximumWidth(230)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._list, 1)
        actions.removeWidget(self._copy)
        left_layout.addWidget(self._copy)
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._name)
        right_layout.addWidget(self._editor, 1)
        right_layout.addWidget(self._variables)
        right_layout.addLayout(actions)
        right_layout.addWidget(model_section)
        self._save.setProperty("role", "primary")
        self._delete.setProperty("role", "danger")
        columns = QHBoxLayout()
        columns.setSpacing(20)
        columns.addWidget(left, 1)
        columns.addWidget(right, 3)
        layout.addLayout(columns, 1)
        self._i18n.language_changed.connect(lambda _: self._retranslate_list())
        self._i18n.bind_tree(self)

    def refresh(self) -> None:
        if not self._draft and not self._dirty:

            def task() -> object:
                return self._library.list_templates(), self._library.list_models()

            self._submit("refresh", task)

    def choose_model(self, model_id: int | None) -> None:
        """Follow the workspace model when its Manage prompts link is used."""
        self._preferred_model = model_id
        index = self._models.findData(model_id)
        if index >= 0:
            self._models.setCurrentIndex(index)
            self._load_model_prompt()

    def _mark_dirty(self) -> None:
        if not self._editor.isReadOnly():
            self._dirty = True

    def _selected_id(self) -> str | None:
        item = self._list.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, str) else None

    def _on_copy(self) -> None:
        self._draft = True
        self._dirty = True
        self._name.clear()
        self._name.setReadOnly(False)
        self._editor.setReadOnly(False)
        self._editor.setPlainText(current_preset().template_text)
        self._save.setEnabled(True)
        self._delete.setEnabled(False)
        self._status.setText(self._i18n.tr("Name and edit the copy, then save it."))
        self._name.setFocus()

    def _on_save(self) -> None:
        name, text = self._name.text(), self._editor.toPlainText()
        template_id = self._selected_id()
        if self._draft:
            self._submit("save", lambda: self._library.copy_preset(name, template_text=text))
        elif template_id is not None:
            self._submit(
                "save",
                lambda: self._library.update(
                    template_id,
                    name=name,
                    template_text=text,
                ),
            )

    def _on_delete(self) -> None:
        template_id = self._selected_id()
        if template_id is not None and not self._draft:
            self._submit("delete", lambda: self._library.delete(template_id))

    def _on_selected(self, current: QListWidgetItem | None, _previous: object) -> None:
        if current is None:
            return
        self._draft = False
        template_id = current.data(Qt.ItemDataRole.UserRole)
        prompt = self._templates.get(template_id) if isinstance(template_id, str) else None
        self._name.setText(prompt.name if prompt is not None else self._i18n.tr("Preset prompt"))
        self._editor.setPlainText(
            prompt.template_text if prompt is not None else current_preset().template_text
        )
        self._name.setReadOnly(prompt is None)
        self._editor.setReadOnly(prompt is None)
        self._save.setEnabled(prompt is not None)
        self._delete.setEnabled(prompt is not None)
        self._status.setText(
            self._i18n.tr("This prompt is based on an older preset. Copy the current preset.")
            if prompt is not None and prompt.parent_template_version != current_preset().version
            else ""
        )
        self._dirty = False

    def _handle_action(self, action: str, result: object) -> None:
        if action == "refresh":
            assert isinstance(result, tuple)
            templates, models = result
            selected = self._selected_id()
            self._templates = {prompt.template_id: prompt for prompt in templates}
            self._list.blockSignals(True)
            self._list.clear()
            self._list.addItem(QListWidgetItem(self._i18n.tr("Preset prompt")))
            for prompt in templates:
                item = QListWidgetItem(prompt.name)
                item.setData(Qt.ItemDataRole.UserRole, prompt.template_id)
                self._list.addItem(item)
            index = next(
                (
                    i
                    for i in range(self._list.count())
                    if self._list.item(i).data(Qt.ItemDataRole.UserRole) == selected
                ),
                0,
            )
            self._list.setCurrentRow(index)
            self._list.blockSignals(False)
            self._on_selected(self._list.currentItem(), None)
            selected_model = self._preferred_model or self._models.currentData()
            self._preferred_model = None
            self._models.clear()
            for model in models:
                self._models.addItem(model.name, model.id)
            if isinstance(selected_model, int):
                self._models.setCurrentIndex(max(0, self._models.findData(selected_model)))
            self._load_model_prompt()
        elif action in {"save", "delete"}:
            self._draft = False
            self._dirty = False
            self._status.setText(
                self._i18n.tr("Prompt saved." if action == "save" else "Prompt deleted.")
            )
            self.configuration_changed.emit()
            self.refresh()
        elif action == "load_model_prompt":
            assert isinstance(result, tuple)
            model_id, override = result
            if model_id != self._models.currentData():
                return
            while self._model_layout.count():
                child = self._model_layout.takeAt(0)
                widget = child.widget() if child is not None else None
                if widget is not None:
                    widget.deleteLater()
            preset = current_preset()
            self._model_editor = WorkbenchPromptEditor(
                preset.template_text,
                override_text=override.template_text
                if isinstance(override, PromptOverride)
                else None,
                override_parent_version=(
                    override.parent_template_version
                    if isinstance(override, PromptOverride)
                    else None
                ),
                stale=isinstance(override, PromptOverride)
                and override.parent_template_version != preset.version,
                parent=self._model_host,
            )
            self._model_editor.save_requested.connect(self._save_model_prompt)
            self._model_editor.clear_requested.connect(self._clear_model_prompt)
            self._model_layout.addWidget(self._model_editor)
            self._i18n.bind_tree(self._model_editor)
            self._model_host.setEnabled(True)
        elif action in {"save_model_prompt", "clear_model_prompt"}:
            self.configuration_changed.emit()
            self._load_model_prompt()

    def _load_model_prompt(self, _index: int = -1) -> None:
        model_id = self._models.currentData()
        if isinstance(model_id, int):
            self._model_host.setEnabled(False)
            self._submit(
                "load_model_prompt", lambda: (model_id, self._library.model_prompt(model_id))
            )

    def _save_model_prompt(self, text: str) -> None:
        model_id = self._models.currentData()
        if isinstance(model_id, int):
            self._submit(
                "save_model_prompt", lambda: self._library.save_model_prompt(model_id, text)
            )

    def _clear_model_prompt(self) -> None:
        model_id = self._models.currentData()
        if isinstance(model_id, int):
            self._submit("clear_model_prompt", lambda: self._library.clear_model_prompt(model_id))

    def _retranslate_list(self) -> None:
        self._variables.setText(
            self._i18n.tr("Variables") + ": "
            + ", ".join(f"${key}" for key in ALLOWED_PLACEHOLDERS)
        )
        if self._list.count():
            self._list.item(0).setText(self._i18n.tr("Preset prompt"))
        if self._selected_id() is None and not self._draft:
            self._name.setText(self._i18n.tr("Preset prompt"))

    def _handle_error(self, error: str) -> None:
        self._model_host.setEnabled(True)
        message = self._i18n.tr(safe_error_message(error))
        self._status.setText(f"{self._i18n.tr('Error')}: {message}")
