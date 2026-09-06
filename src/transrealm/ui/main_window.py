"""Main window wiring the desktop shell to the worker threads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread
from PySide6.QtGui import QCloseEvent, QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from transrealm import __version__
from transrealm.adapters.protocol import ModelAdapter
from transrealm.ui.i18n import LanguageManager
from transrealm.ui.project_page import ProjectPage
from transrealm.ui.settings_page import SettingsPage
from transrealm.ui.theme import LIGHT_TOKENS, build_stylesheet
from transrealm.ui.translation_page import TranslationPage
from transrealm.ui.worker import (
    ServiceWorker,
    TranslationWorker,
    compose_adapter_factory,
)

APP_VERSION = __version__


class MainShell(QWidget):
    """Central shell that preserves the legacy tab-index inspection hook."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tabs: QTabWidget | None = None

    def bind_tabs(self, tabs: QTabWidget) -> None:
        self._tabs = tabs

    def currentIndex(self) -> int:  # noqa: N802
        """Keep existing UI tests and integrations able to inspect navigation."""
        return self._tabs.currentIndex() if self._tabs is not None else -1

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        """Preserve the legacy tab navigation entry point."""
        if self._tabs is not None:
            self._tabs.setCurrentIndex(index)

    def count(self) -> int:
        """Preserve the legacy tab count entry point."""
        return self._tabs.count() if self._tabs is not None else 0

    def widget(self, index: int) -> QWidget | None:
        """Preserve the legacy tab widget lookup entry point."""
        return self._tabs.widget(index) if self._tabs is not None else None

    def tabText(self, index: int) -> str:  # noqa: N802
        """Preserve the legacy tab label lookup entry point."""
        return self._tabs.tabText(index) if self._tabs is not None else ""

    def currentWidget(self) -> QWidget | None:  # noqa: N802
        """Preserve the legacy current-page lookup entry point."""
        return self._tabs.currentWidget() if self._tabs is not None else None


def _scroll_page(page: QWidget, object_name: str, parent: QWidget) -> QScrollArea:
    """Keep the existing page controls usable in short or scaled windows."""
    scroll = QScrollArea(parent)
    scroll.setObjectName(object_name)
    page.setObjectName(object_name.replace("-scroll", "-page"))
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    surface = QColor(LIGHT_TOKENS["surface"])
    for widget in (scroll, scroll.viewport(), page):
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Window, surface)
        palette.setColor(QPalette.ColorRole.Base, surface)
        widget.setPalette(palette)
        widget.setAutoFillBackground(True)
    return scroll


class MainWindow(QMainWindow):
    """Minimal desktop shell: Settings / Project / Translation tabs.

    Owns a :class:`ServiceWorker` thread for short service calls and a
    :class:`TranslationWorker` thread for the long translation loop. On close
    the translation worker is asked to stop at the next segment boundary and
    the threads are given a bounded wait to converge; any in-flight segment
    stays recoverable through the P0-T07 lease, so the thread is never killed.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        app_version: str,
        adapter_factory: Callable[[int], ModelAdapter] | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self._i18n = LanguageManager(settings=settings, parent=self)
        self.setObjectName("main-window")
        self.setWindowTitle(self._i18n.tr("TransRealm"))
        self.setMinimumSize(960, 600)
        self.resize(1180, 720)
        self.setStyleSheet(build_stylesheet())

        factory = adapter_factory or compose_adapter_factory(db_path, app_version)

        self._service_worker = ServiceWorker()
        self._service_thread = QThread(self)
        self._service_worker.moveToThread(self._service_thread)
        self._service_thread.start()

        self._translation_worker = TranslationWorker(
            db_path,
            app_version=app_version,
            adapter_factory=factory,
        )
        self._translation_thread = QThread(self)
        self._translation_worker.moveToThread(self._translation_thread)
        self._translation_thread.start()

        self._settings = SettingsPage(
            self._service_worker,
            db_path=db_path,
            app_version=app_version,
            i18n=self._i18n,
        )
        self._project = ProjectPage(
            self._service_worker,
            db_path=db_path,
            app_version=app_version,
            i18n=self._i18n,
        )
        self._translation = TranslationPage(
            self._service_worker,
            translation_worker=self._translation_worker,
            db_path=db_path,
            app_version=app_version,
            i18n=self._i18n,
        )

        shell = MainShell(self)
        shell.setObjectName("main-shell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(24, 20, 24, 24)
        shell_layout.setSpacing(16)

        header = QFrame(shell)
        header.setObjectName("app-header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)
        header_layout.setSpacing(2)
        title = QLabel("TransRealm", header)
        title.setObjectName("app-title")
        subtitle = QLabel("A calm workspace for local-first translation", header)
        subtitle.setObjectName("app-subtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        shell_layout.addWidget(header)

        tabs = QTabWidget(shell)
        tabs.setObjectName("main-tabs")
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        tabs.setUsesScrollButtons(False)
        tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        tabs.addTab(_scroll_page(self._settings, "settings-scroll", shell), "Settings")
        tabs.addTab(_scroll_page(self._project, "project-scroll", shell), "Project")
        tabs.addTab(
            _scroll_page(self._translation, "translation-scroll", shell),
            "Translation",
        )
        shell_layout.addWidget(tabs, 1)
        shell.bind_tabs(tabs)
        self._tabs = tabs
        self.setCentralWidget(shell)
        self._i18n.language_changed.connect(self._on_language_changed)
        self._i18n.bind_tree(self)

        self._project.project_ready.connect(self._translation.set_project)
        self._project.project_deleted.connect(
            lambda _project_id: self._translation.clear_project(),
        )
        self._project.project_settings_changed.connect(self._translation.set_project)
        self._project.document_ready.connect(self._translation.set_document)
        self._translation.request_project_setup.connect(
            lambda: self._tabs.setCurrentIndex(1),
        )
        self._project.request_settings_setup.connect(
            lambda: self._tabs.setCurrentIndex(0),
        )
        self._translation.request_settings_setup.connect(
            lambda: self._tabs.setCurrentIndex(0),
        )

        self._settings.refresh()
        self._project.refresh()

    def _on_language_changed(self, language: str) -> None:
        """Rebind newly-created workbench widgets after a language switch."""
        del language
        self.setWindowTitle(self._i18n.tr("TransRealm"))
        self._i18n.bind_tree(self)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._shutdown_workers():
            super().closeEvent(event)
        else:
            event.ignore()

    def shutdown(self) -> bool:
        """Request worker shutdown and report whether both threads stopped."""
        return self._shutdown_workers()

    def _shutdown_workers(self) -> bool:
        self._translation_worker.request_stop()
        self._translation_thread.quit()
        translation_stopped = (
            not self._translation_thread.isRunning() or self._translation_thread.wait(5000)
        )
        if not translation_stopped:
            return False

        self._service_thread.quit()
        service_stopped = (
            not self._service_thread.isRunning() or self._service_thread.wait(2000)
        )
        return service_stopped


def main() -> None:
    """Launch the desktop shell against a default data directory."""
    import sys

    from PySide6.QtWidgets import QApplication

    data_dir = Path.home() / ".transrealm"
    data_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    window = MainWindow(data_dir / "project.sqlite", app_version=APP_VERSION)
    window.show()
    sys.exit(app.exec())
