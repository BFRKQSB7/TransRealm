"""Workbench parameter editor widget.

P1-T03-M02: the workbench presents a control only for the parameters the
Profile's capability declares as supported (never an assumed universal
parameter set). The adapter still performs the final filter before sending,
so the UI surface and the adapter are a deliberate double check. The pure
value policy lives in ``application/workbench.py``; this module only renders
widgets from the declared specs and reads their current values.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from transrealm.application.workbench import (
    ParamSpec,
    initial_param_values,
    param_spec,
    presented_parameters,
)
from transrealm.domain.model_profile import ModelCapability

_LARGE = 1_000_000


class WorkbenchParamEditor(QWidget):
    """A capability-driven parameter form.

    One control per ``capability.supported_parameters`` entry, seeded from
    ``default_params`` (or the spec default for missing/unknown parameters).
    ``values()`` returns the current value of every presented parameter, so the
    caller only ever sends parameters the capability declared.
    """

    def __init__(
        self,
        capability: ModelCapability,
        default_params: dict[str, object],
        parent: QWidget | None = None,
        *,
        initial: dict[str, object] | None = None,
    ) -> None:
        super().__init__(parent)
        self._capability = capability
        self._readers: dict[str, Callable[[], object]] = {}
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        values = initial_param_values(capability, default_params)
        if initial is not None:
            values = {**values, **initial}
        for name in presented_parameters(capability):
            widget, reader = self._build_control(
                name,
                param_spec(name),
                values[name],
            )
            self._readers[name] = reader
            layout.addRow(name, widget)
        self.setLayout(layout)

    def values(self) -> dict[str, object]:
        """Return the current value of every presented parameter."""
        return {name: reader() for name, reader in self._readers.items()}

    def _build_control(
        self,
        name: str,
        spec: ParamSpec | None,
        value: object,
    ) -> tuple[QWidget, Callable[[], object]]:
        if spec is not None and spec.kind == "float":
            double_spin = QDoubleSpinBox(self)
            double_spin.setDecimals(2)
            low = spec.minimum if spec.minimum is not None else -_LARGE
            high = spec.maximum if spec.maximum is not None else _LARGE
            numeric = value if isinstance(value, (int, float)) else 0.0
            high = max(high, float(numeric))
            double_spin.setRange(low, high)
            if spec.step is not None:
                double_spin.setSingleStep(spec.step)
            double_spin.setValue(float(numeric))
            return double_spin, double_spin.value
        if spec is not None and spec.kind == "int":
            int_spin = QSpinBox(self)
            low = int(spec.minimum) if spec.minimum is not None else 0
            high = int(spec.maximum) if spec.maximum is not None else _LARGE
            if name == "max_tokens" and self._capability.max_output_tokens > 0:
                high = min(high, self._capability.max_output_tokens)
            numeric = value if isinstance(value, (int, float)) else 0
            high = max(high, int(numeric))
            int_spin.setRange(low, high)
            if spec.step is not None:
                int_spin.setSingleStep(int(spec.step))
            int_spin.setValue(int(numeric))
            return int_spin, int_spin.value
        if spec is not None and spec.kind == "bool":
            box = QCheckBox(self)
            box.setChecked(bool(value))
            return box, box.isChecked
        # Unknown supported parameter: plain text control, never assumed to be
        # numeric. The adapter still filters it against the capability.
        edit = QLineEdit(self)
        edit.setText(str(value))
        return edit, edit.text


class WorkbenchPromptEditor(QWidget):
    """Read-only preset template preview with an editable override copy.

    P1-T03-M03: the preset template is shown read-only and can never be edited
    in place. The user edits a copy and saves it as an override (the page owns
    the worker and persists it via the service); a saved override can be
    cleared to return to the preset. The widget only emits requests — it never
    touches the database.
    """

    save_requested = Signal(str)
    clear_requested = Signal()

    def __init__(
        self,
        preset_text: str,
        *,
        override_text: str | None = None,
        override_parent_version: str | None = None,
        initial: str | None = None,
        stale: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._stale = stale
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status = QLabel("", self)
        self._status.setProperty("transrealm_i18n_dynamic", True)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        preview_label = QLabel("Preset (read-only):", self)
        layout.addWidget(preview_label)
        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(True)
        self._preview.setPlainText(preset_text)
        self._preview.setMaximumHeight(110)
        layout.addWidget(self._preview)

        layout.addWidget(QLabel("Override:", self))
        self._editor = QPlainTextEdit(self)
        base_text = override_text if override_text is not None else preset_text
        if initial is not None:
            base_text = initial
        self._editor.setPlainText(base_text)
        layout.addWidget(self._editor)

        buttons = QHBoxLayout()
        self._save = QPushButton("Save as override", self)
        self._clear = QPushButton("Clear override", self)
        self._clear.setEnabled(override_text is not None)
        buttons.addWidget(self._save)
        buttons.addWidget(self._clear)
        layout.addLayout(buttons)

        self._save.clicked.connect(lambda: self.save_requested.emit(self._editor.toPlainText()))
        self._clear.clicked.connect(self.clear_requested.emit)
        self._update_status(override_text is not None, override_parent_version)

    def text(self) -> str:
        """Return the current editor text (the unsaved override draft)."""
        return self._editor.toPlainText()

    def set_override(self, override_text: str, parent_version: str | None = None) -> None:
        """Reflect a persisted override in the editor and status."""
        self._editor.setPlainText(override_text)
        self._clear.setEnabled(True)
        self._update_status(True, parent_version)

    def _update_status(self, override_active: bool, parent_version: str | None) -> None:
        if self._stale:
            version = parent_version or "?"
            self._status.setText(
                f"This override is based on preset version {version}, which no "
                "longer matches the current preset. Re-save from the current "
                "preset or clear it before translating.",
            )
        elif override_active:
            version = parent_version or "?"
            self._status.setText(f"Using an override of preset version {version}.")
        else:
            self._status.setText("Using the read-only preset template.")


class WorkbenchRevisionEditor(QWidget):
    """Manual translation editor for a workbench segment.

    P1-T03-M04: editing a segment appends an ``origin=user`` TranslationRevision
    and makes it the current revision; locking the current revision protects it
    from being replaced by automatic results. The widget only emits requests —
    the page owns the worker and persists through the service, so this widget
    never touches the database.
    """

    save_requested = Signal(str)
    lock_requested = Signal()
    unlock_requested = Signal()

    def __init__(
        self,
        *,
        source_text: str,
        revision_text: str | None = None,
        locked: bool = False,
        initial: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._source_label = QLabel(self)
        self._source_label.setProperty("transrealm_i18n_dynamic", True)
        self._source_label.setWordWrap(True)
        layout.addWidget(self._source_label)

        self._status = QLabel(self)
        self._status.setProperty("transrealm_i18n_dynamic", True)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        layout.addWidget(QLabel("Translation:", self))
        self._editor = QPlainTextEdit(self)
        layout.addWidget(self._editor)

        buttons = QHBoxLayout()
        self._save = QPushButton("Save translation", self)
        self._lock = QPushButton("Lock", self)
        self._unlock = QPushButton("Unlock", self)
        buttons.addWidget(self._save)
        buttons.addWidget(self._lock)
        buttons.addWidget(self._unlock)
        layout.addLayout(buttons)

        self._save.clicked.connect(lambda: self.save_requested.emit(self._editor.toPlainText()))
        self._lock.clicked.connect(self.lock_requested.emit)
        self._unlock.clicked.connect(self.unlock_requested.emit)

        self.set_revision(
            source_text=source_text,
            revision_text=revision_text,
            locked=locked,
            initial=initial,
        )

    def translation(self) -> str:
        """Return the current editor text (the unsaved manual translation)."""
        return self._editor.toPlainText()

    def set_revision(
        self,
        *,
        source_text: str,
        revision_text: str | None,
        locked: bool,
        initial: str | None = None,
    ) -> None:
        """Reflect a segment's source, current revision and lock state.

        ``initial`` preserves an unsaved edit (the page keeps the draft across a
        refresh); it wins over the persisted revision text.
        """
        self._source_label.setText(f"Source: {source_text}")
        if initial is not None:
            self._editor.setPlainText(initial)
        else:
            self._editor.setPlainText(revision_text if revision_text is not None else "")
        has_current = revision_text is not None
        self._lock.setEnabled(has_current and not locked)
        self._unlock.setEnabled(has_current and locked)
        if locked:
            self._status.setText(
                "Current translation is locked; automatic results cannot replace it.",
            )
        elif has_current:
            self._status.setText(
                "Current translation is unlocked; automatic results may replace it.",
            )
        else:
            self._status.setText("No current translation yet. Save one to lock it.")
