"""Worker threads for the desktop shell.

All SQLite/Provider/Parser work happens on dedicated worker threads so the Qt
main thread never blocks. Services are created and used inside the thread that
runs them, so a database connection is never shared across threads. The main
thread only sends plain arguments and receives DTOs/immutable data via signals.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from transrealm.adapters.protocol import ModelAdapter
from transrealm.application.translation_facade import TranslationFacade


def compose_adapter_factory(db_path: Path, app_version: str) -> Callable[[int], ModelAdapter]:
    """Return a factory building a real adapter from a persisted profile.

    The factory runs in the translation worker thread and opens service
    connections there.
    """

    def build(profile_id: int) -> ModelAdapter:
        return TranslationFacade.adapter_for_profile(db_path, app_version, profile_id)

    return build


class ServiceWorker(QObject):
    """Runs short Application Service calls on its own thread.

    The UI emits ``run_requested`` with a ``request_id`` and a callable; the
    callable executes in this object's thread (where it may open and close
    service connections) and the result or a safe error message is emitted
    back as a queued signal.
    """

    task_done = Signal(str, object)
    task_error = Signal(str, str)
    run_requested = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        # Auto connection: because this object lives on the worker thread,
        # emitting run_requested from the main thread queues the call there.
        self.run_requested.connect(self.run)

    @Slot(str, object)
    def run(self, request_id: str, fn: Callable[[], object]) -> None:
        """Execute ``fn`` on this worker's thread and emit the outcome."""
        try:
            result = fn()
        except Exception as exc:
            self.task_error.emit(request_id, str(exc))
        else:
            self.task_done.emit(request_id, result)


class TranslationWorker(QObject):
    """Translates a document's pending segments on a dedicated thread.

    Owns a :class:`TranslationFacade` (created in this thread) for the
    duration of a translate call. Cancellation is observed at segment
    boundaries via the plain ``request_stop`` flag; the in-flight model call is
    bounded by the adapter timeout, so shutdown converges without killing a
    thread.
    """

    progress = Signal(int, int, str)  # done, total, current stable key
    segment_completed = Signal(str, int)  # stable key, revision id
    segment_failed = Signal(str, str)  # stable key, error message
    config_missing = Signal(str)  # actionable reason to set up the project first
    finished = Signal()
    failed = Signal(str)
    start_translate = Signal(int, int, int)  # project_id, document_id, profile_id
    start_translate_auto = Signal(int, int)  # project_id, document_id
    # project_id, document_id, profile_id, params
    start_translate_workbench = Signal(int, int, int, object)
    start_translate_single = Signal(int, int, int, int, object)

    def __init__(
        self,
        db_path: Path,
        *,
        app_version: str,
        adapter_factory: Callable[[int], ModelAdapter],
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._app_version = app_version
        self._adapter_factory = adapter_factory
        self._stop_requested = False
        self._is_running = False
        # Queued connection: emitting start_translate from the main thread runs
        # the translate loop on this object's worker thread.
        self.start_translate.connect(self.translate)
        self.start_translate_auto.connect(self.translate_auto)
        self.start_translate_workbench.connect(self.translate_workbench)
        self.start_translate_single.connect(self.translate_single)

    def request_stop(self) -> None:
        """Request cancellation at the next segment boundary.

        Called directly from the main thread (not via a queued slot) so it
        takes effect while the translate loop is blocking this thread.
        """
        self._stop_requested = True

    @Slot(int, int)
    def translate_auto(self, project_id: int, source_document_id: int) -> None:
        """Translate in auto mode using the project's active profile.

        Resolves the active ModelProfile on this worker thread and then runs
        the same translate loop as the explicit-profile path. When the project
        is missing or has no active profile, emits ``config_missing`` (no run
        is created and the adapter is never called) so the UI can guide the
        user with a single recoverable step.
        """
        if self._is_running:
            self.failed.emit("A translation is already running.")
            self.finished.emit()
            return

        try:
            with TranslationFacade(self._db_path, app_version=self._app_version) as facade:
                project = facade.open_job(project_id)
        except Exception as exc:
            self.failed.emit(str(exc))
            self.finished.emit()
            return
        if project is None:
            self.config_missing.emit(
                f"Project {project_id} does not exist. Select a project first.",
            )
            self.finished.emit()
            return
        profile_id = project.active_profile_id
        if profile_id is None:
            self.config_missing.emit(
                "Choose a Provider and model in Translation before translating.",
            )
            self.finished.emit()
            return
        self.translate(project_id, source_document_id, profile_id)

    @Slot(int, int, int, object)
    def translate_workbench(
        self,
        project_id: int,
        source_document_id: int,
        profile_id: int,
        params: object,
    ) -> None:
        """Translate with explicit profile and workbench parameters."""
        extra_params = params if isinstance(params, dict) else None
        self.translate(project_id, source_document_id, profile_id, extra_params=extra_params)

    @Slot(int, int, int)
    def translate(
        self,
        project_id: int,
        source_document_id: int,
        profile_id: int,
        extra_params: dict[str, object] | None = None,
        segment_id: int | None = None,
    ) -> None:
        """Translate every pending segment of a document on this thread."""
        if self._is_running:
            self.failed.emit("A translation is already running.")
            self.finished.emit()
            return

        self._is_running = True
        service: TranslationFacade | None = None
        run_id: int | None = None
        terminal_status = "failed"
        segment_failed = False
        try:
            adapter = self._adapter_factory(profile_id)
            service = TranslationFacade(
                self._db_path,
                app_version=self._app_version,
                adapter=adapter,
            )
            if source_document_id not in {
                document.id for document in service.list_documents(project_id)
            }:
                raise ValueError("Selected document does not belong to this Job.")
            if segment_id is not None:
                if segment_id not in {
                    item.id for item in service.list_segments(source_document_id)
                }:
                    raise ValueError("Selected segment does not belong to this file.")
                service.requeue_segment(segment_id)
            run = service.start_run(project_id)
            assert run.id is not None
            run_id = run.id
            segments = service.list_segments(source_document_id)
            locked = {
                item.segment_id
                for item in service.progress(source_document_id)
                if item.revision_locked
            }
            pending = [
                segment
                for segment in segments
                if segment.status == "pending"
                and segment.id not in locked
                and (segment_id is None or segment.id == segment_id)
            ]
            total = len(pending)
            self.progress.emit(0, total, "")
            for index, segment in enumerate(pending):
                if self._stop_requested:
                    terminal_status = "cancelled"
                    break
                assert segment.id is not None
                try:
                    revision = asyncio.run(
                        service.translate_segment(
                            run_id=run.id,
                            segment_id=segment.id,
                            profile_id=profile_id,
                            extra_params=extra_params,
                        ),
                    )
                    assert revision.id is not None
                    self.segment_completed.emit(segment.stable_key, revision.id)
                except Exception as exc:
                    self.segment_failed.emit(segment.stable_key, str(exc))
                    segment_failed = True
                self.progress.emit(index + 1, total, segment.stable_key)
            else:
                terminal_status = "failed" if segment_failed else "completed"
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if service is not None:
                if run_id is not None:
                    try:
                        if terminal_status == "cancelled":
                            service.stop(run_id)
                        else:
                            service.finish_run(run_id, status=terminal_status)
                    except Exception as exc:
                        self.failed.emit(str(exc))
                service.close()
            self._is_running = False
            self._stop_requested = False
            self.finished.emit()

    @Slot(int, int, int, int, object)
    def translate_single(
        self,
        project_id: int,
        source_document_id: int,
        profile_id: int,
        segment_id: int,
        params: object,
    ) -> None:
        self.translate(
            project_id,
            source_document_id,
            profile_id,
            extra_params=params if isinstance(params, dict) else None,
            segment_id=segment_id,
        )
