"""Main window wiring the desktop shell to the worker threads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget

from transrealm.adapters.protocol import ModelAdapter
from transrealm.ui.project_page import ProjectPage
from transrealm.ui.settings_page import SettingsPage
from transrealm.ui.translation_page import TranslationPage
from transrealm.ui.worker import (
    ServiceWorker,
    TranslationWorker,
    compose_adapter_factory,
)

APP_VERSION = "0.1.0"


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
    ) -> None:
        super().__init__()
        self.setWindowTitle("TransRealm")
        self.resize(720, 560)

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
        )
        self._project = ProjectPage(
            self._service_worker,
            db_path=db_path,
            app_version=app_version,
        )
        self._translation = TranslationPage(
            self._service_worker,
            translation_worker=self._translation_worker,
            db_path=db_path,
            app_version=app_version,
        )

        tabs = QTabWidget(self)
        tabs.addTab(self._settings, "Settings")
        tabs.addTab(self._project, "Project")
        tabs.addTab(self._translation, "Translation")
        self.setCentralWidget(tabs)

        self._project.project_ready.connect(self._translation.set_project)
        self._project.project_settings_changed.connect(self._translation.set_project)
        self._project.document_ready.connect(self._translation.set_document)
        self._translation.request_project_setup.connect(
            lambda: tabs.setCurrentIndex(1),
        )

        self._settings.refresh()
        self._project.refresh()

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
