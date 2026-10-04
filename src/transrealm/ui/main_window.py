"""Main window wiring the desktop shell to the worker threads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread
from PySide6.QtGui import QCloseEvent, QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from transrealm import __version__
from transrealm.adapters.protocol import ModelAdapter
from transrealm.ui.i18n import LanguageManager
from transrealm.ui.prompts_page import PromptsPage
from transrealm.ui.settings_page import ProvidersPage
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
    """Desktop shell: Translation / Providers / Prompts.

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
        self._tabs: QTabWidget
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

        self._providers = ProvidersPage(
            self._service_worker,
            db_path=db_path,
            app_version=app_version,
            i18n=self._i18n,
        )
        self._settings = self._providers  # Supported internal compatibility hook.
        self._prompts = PromptsPage(
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
        self._project = self._translation._job_controls

        shell = MainShell(self)
        shell.setObjectName("main-shell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        sidebar = QFrame(shell)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(176)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(14, 24, 14, 18)
        navigation.setSpacing(8)
        brand = QLabel("TransRealm", sidebar)
        brand.setObjectName("brand")
        navigation.addWidget(brand)
        navigation.addSpacing(28)
        self._nav_buttons: list[QPushButton] = []
        for index, label in enumerate(("Translation", "Providers", "Prompts")):
            button = QPushButton(label, sidebar)
            button.setObjectName(f"nav-{index}")
            button.setProperty("role", "navigation")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self._tabs.setCurrentIndex(i))
            navigation.addWidget(button)
            self._nav_buttons.append(button)
        navigation.addStretch()
        local_label = QLabel("Local workspace", sidebar)
        local_label.setProperty("role", "muted")
        navigation.addWidget(local_label)
        navigation.addWidget(self._providers._language_combo)
        version = QLabel(f"v{app_version}", sidebar)
        version.setProperty("transrealm_i18n_dynamic", True)
        version.setProperty("role", "muted")
        navigation.addWidget(version)
        shell_layout.addWidget(sidebar)

        content = QWidget(shell)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 18, 24, 18)
        content_layout.setSpacing(16)

        header = QFrame(shell)
        header.setObjectName("app-header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)
        title = QLabel("Translation", header)
        title.setObjectName("app-title")
        title.setProperty("transrealm_i18n_dynamic", True)
        self._page_title = title
        subtitle = QLabel("Import, translate, refine and export in one workspace.", header)
        subtitle.setObjectName("app-subtitle")
        subtitle.setProperty("transrealm_i18n_dynamic", True)
        subtitle.setWordWrap(True)
        self._page_subtitle = subtitle
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        content_layout.addWidget(header)

        tabs = QTabWidget(shell)
        tabs.setObjectName("main-tabs")
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        tabs.setUsesScrollButtons(False)
        tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        tabs.tabBar().hide()
        self._translation.setObjectName("translation-page")
        tabs.addTab(self._translation, "Translation")
        tabs.addTab(_scroll_page(self._providers, "providers-scroll", shell), "Providers")
        tabs.addTab(_scroll_page(self._prompts, "prompts-scroll", shell), "Prompts")
        content_layout.addWidget(tabs, 1)
        shell_layout.addWidget(content, 1)
        shell.bind_tabs(tabs)
        self._tabs = tabs
        self.setCentralWidget(shell)
        self._i18n.language_changed.connect(self._on_language_changed)
        self._i18n.bind_tree(self)

        self._translation.request_project_setup.connect(
            self._focus_model,
        )
        self._project.request_settings_setup.connect(
            lambda: self._tabs.setCurrentIndex(1),
        )
        self._translation.request_settings_setup.connect(
            lambda: self._tabs.setCurrentIndex(1),
        )
        self._translation.request_prompts_setup.connect(self._open_prompts)
        self._tabs.currentChanged.connect(self._refresh_current_page)
        self._providers.request_translation.connect(lambda: self._tabs.setCurrentIndex(0))
        self._prompts.request_translation.connect(lambda: self._tabs.setCurrentIndex(0))
        self._settings.configuration_changed.connect(self._refresh_workspace)
        self._prompts.configuration_changed.connect(self._refresh_workspace)

        self._settings.refresh()
        self._prompts.refresh()
        self._project.refresh()
        self._sync_navigation(0)

    def _focus_model(self) -> None:
        self._tabs.setCurrentIndex(0)
        self._translation._model_combo.setFocus()
        self._translation._model_combo.showPopup()

    def _sync_navigation(self, index: int) -> None:
        titles = ("Translation", "Providers", "Prompts")
        descriptions = (
            "Import, translate, refine and export in one workspace.",
            "Connect a provider, then add a model for translation.",
            "Create reusable instructions for your translations.",
        )
        for i, button in enumerate(self._nav_buttons):
            button.setChecked(i == index)
        self._page_title.setText(self._i18n.tr(titles[index]))
        self._page_subtitle.setText(self._i18n.tr(descriptions[index]))

    def _refresh_workspace(self) -> None:
        self._project.refresh()
        self._translation.refresh()

    def _open_prompts(self) -> None:
        self._prompts.choose_model(self._translation._active_profile_id)
        self._tabs.setCurrentIndex(2)

    def _refresh_current_page(self, index: int) -> None:
        self._sync_navigation(index)
        if index == 0:
            self._refresh_workspace()
        elif index == 1:
            self._settings.refresh()
        else:
            self._prompts.refresh()

    def _on_language_changed(self, language: str) -> None:
        """Rebind newly-created workbench widgets after a language switch."""
        del language
        self.setWindowTitle(self._i18n.tr("TransRealm"))
        self._i18n.bind_tree(self)
        self._sync_navigation(self._tabs.currentIndex())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._translation._capture_revision_draft()
        unsaved = (
            bool(self._translation._revision_drafts)
            or self._project._notes_dirty
            or self._prompts._dirty
        )
        if self.isVisible() and self._service_thread.isRunning() and unsaved:
            choice = QMessageBox.question(
                self, self._i18n.tr("Unsaved edits"),
                self._i18n.tr("There are unsaved edits. Stay to save them, or discard and close."),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
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
        service_stopped = not self._service_thread.isRunning() or self._service_thread.wait(2000)
        if service_stopped:
            self._i18n.uninstall()
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
