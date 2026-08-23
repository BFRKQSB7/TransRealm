"""Qt translation and language preference support for the desktop shell."""

from __future__ import annotations

from pathlib import Path
from weakref import WeakKeyDictionary, WeakSet

from PySide6.QtCore import QCoreApplication, QObject, QSettings, QTranslator, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QTabWidget,
    QWidget,
)

SUPPORTED_LANGUAGES = ("en", "zh_CN")
DEFAULT_LANGUAGE = "en"


class LanguageManager(QObject):
    """Install a Qt translator and persist the selected UI language.

    The manager stores source text on static widgets and reapplies it after a
    language change. Dynamic list/status content is left to its owning page;
    binding the tree again after a refresh covers newly-created editor widgets.
    """

    language_changed = Signal(str)

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings or QSettings("TransRealm", "TransRealm")
        self._translator = QTranslator(self)
        self._bound_widgets: WeakSet[QWidget] = WeakSet()
        self._tab_sources: WeakKeyDictionary[QTabWidget, list[str]] = WeakKeyDictionary()
        self._combo_sources: WeakKeyDictionary[QComboBox, list[str]] = WeakKeyDictionary()
        self._language = self._normalize(self._settings.value("language", DEFAULT_LANGUAGE))
        self._load_language(self._language)

    @property
    def current_language(self) -> str:
        """Return the normalized active language code."""
        return self._language

    def set_language(self, language: object) -> str:
        """Set and persist a language, safely falling back to English."""
        requested = self._normalize(language)
        if requested == self._language:
            self._settings.setValue("language", requested)
            self._settings.sync()
            return requested

        active = requested if self._load_language(requested) else DEFAULT_LANGUAGE
        self._language = active
        self._settings.setValue("language", active)
        self._settings.sync()
        self.language_changed.emit(active)
        return active

    def tr(
        self,
        source: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        """Translate a source string in the stable application context."""
        return QCoreApplication.translate("TransRealm", source, disambiguation, n)

    def bind_tree(self, root: QWidget) -> None:
        """Bind static text in a widget tree and immediately translate it."""
        self._bind_widget(root)
        for widget in root.findChildren(QWidget):
            self._bind_widget(widget)

    def _bind_widget(self, widget: QWidget) -> None:
        if bool(widget.property("transrealm_i18n_dynamic")):
            return

        if isinstance(widget, QTabWidget):
            if widget not in self._tab_sources:
                self._tab_sources[widget] = [
                    widget.tabText(index) for index in range(widget.count())
                ]
            self._bound_widgets.add(widget)
            self._translate_tabs(widget)
            return

        if isinstance(widget, QComboBox) and bool(
            widget.property("transrealm_i18n_static_items"),
        ):
            if widget not in self._combo_sources:
                self._combo_sources[widget] = [
                    widget.itemText(index) for index in range(widget.count())
                ]
            self._bound_widgets.add(widget)
            self._translate_combo(widget)
            return

        if isinstance(widget, (QAbstractButton, QGroupBox, QLabel)):
            source = widget.property("transrealm_i18n_source")
            if source is None:
                source = self._widget_text(widget)
                if not source:
                    return
                widget.setProperty("transrealm_i18n_source", source)
            if not isinstance(source, str) or not source:
                return
            self._bound_widgets.add(widget)
            self._set_widget_text(widget, self.tr(source))

    def _retranslate_bound(self, language: str) -> None:
        del language
        for widget in list(self._bound_widgets):
            if isinstance(widget, QTabWidget):
                self._translate_tabs(widget)
            elif isinstance(widget, QComboBox):
                self._translate_combo(widget)
            elif isinstance(widget, (QAbstractButton, QGroupBox, QLabel)):
                source = widget.property("transrealm_i18n_source")
                if isinstance(source, str):
                    self._set_widget_text(widget, self.tr(source))

    @staticmethod
    def _widget_text(widget: QAbstractButton | QGroupBox | QLabel) -> str:
        if isinstance(widget, QGroupBox):
            return widget.title()
        return widget.text()

    @staticmethod
    def _set_widget_text(widget: QAbstractButton | QGroupBox | QLabel, text: str) -> None:
        if isinstance(widget, QGroupBox):
            widget.setTitle(text)
        else:
            widget.setText(text)

    def _translate_tabs(self, widget: QTabWidget) -> None:
        for index, source in enumerate(self._tab_sources[widget]):
            if index < widget.count():
                widget.setTabText(index, self.tr(source))

    def _translate_combo(self, widget: QComboBox) -> None:
        for index, source in enumerate(self._combo_sources[widget]):
            if index < widget.count():
                widget.setItemText(index, self.tr(source))

    def _load_language(self, language: str) -> bool:
        app = QCoreApplication.instance()
        if app is not None:
            app.removeTranslator(self._translator)
        if language == DEFAULT_LANGUAGE:
            self._language = DEFAULT_LANGUAGE
            self._retranslate_bound(language)
            return True

        resource = Path(__file__).with_name("i18n") / f"transrealm_{language}.qm"
        loaded = self._translator.load(str(resource))
        if not loaded:
            self._language = DEFAULT_LANGUAGE
            self._retranslate_bound(DEFAULT_LANGUAGE)
            return False
        if app is not None:
            app.installTranslator(self._translator)
        self._language = language
        self._retranslate_bound(language)
        return True

    @staticmethod
    def _normalize(language: object) -> str:
        value = str(language) if language is not None else DEFAULT_LANGUAGE
        return value if value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
