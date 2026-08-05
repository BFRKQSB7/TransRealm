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
from transrealm.application.adapter_factory import compose_adapter
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_service import TranslationService
from transrealm.domain.segment import Segment
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository


def compose_adapter_factory(db_path: Path, app_version: str) -> Callable[[int], ModelAdapter]:
    """Return a factory building a real adapter from a persisted profile.

    The factory runs in the translation worker thread and opens service
    connections there.
    """

    def build(profile_id: int) -> ModelAdapter:
        with ProviderConnectionService(db_path, app_version=app_version) as connections:
            with ModelProfileService(db_path, app_version=app_version) as profiles:
                profile = profiles.get_profile(profile_id)
                if profile is None:
                    raise LookupError(f"ModelProfile with id {profile_id} does not exist.")
                connection = connections.get_connection(profile.provider_connection_id)
                if connection is None:
                    raise LookupError(
                        f"ProviderConnection for profile {profile_id} does not exist.",
                    )
        return compose_adapter(connection, profile)

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

    Owns a :class:`TranslationService` (created in this thread) for the
    duration of a translate call. Cancellation is observed at segment
    boundaries via the plain ``request_stop`` flag; the in-flight model call is
    bounded by the adapter timeout, so shutdown converges without killing a
    thread.
    """

    progress = Signal(int, int, str)  # done, total, current stable key
    segment_completed = Signal(str, int)  # stable key, revision id
    segment_failed = Signal(str, str)  # stable key, error message
    finished = Signal()
    failed = Signal(str)
    start_translate = Signal(int, int, int)  # project_id, document_id, profile_id

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

    def request_stop(self) -> None:
        """Request cancellation at the next segment boundary.

        Called directly from the main thread (not via a queued slot) so it
        takes effect while the translate loop is blocking this thread.
        """
        self._stop_requested = True

    @Slot(int, int, int)
    def translate(self, project_id: int, source_document_id: int, profile_id: int) -> None:
        """Translate every pending segment of a document on this thread."""
        if self._is_running:
            self.failed.emit("A translation is already running.")
            self.finished.emit()
            return

        self._is_running = True
        self._stop_requested = False
        service: TranslationService | None = None
        run_id: int | None = None
        terminal_status = "failed"
        segment_failed = False
        try:
            adapter = self._adapter_factory(profile_id)
            service = TranslationService(
                self._db_path,
                app_version=self._app_version,
                adapter=adapter,
            )
            recovered = service.recover_expired_leases()
            if recovered:
                self.segment_failed.emit("recovery", f"Recovered {recovered} expired lease(s).")
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            run_id = run.id
            segments = self._load_segments(self._db_path, source_document_id)
            pending = [segment for segment in segments if segment.status == "pending"]
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
                        service.finish_run(run_id=run_id, status=terminal_status)
                    except Exception as exc:
                        self.failed.emit(str(exc))
                service.close()
            self._is_running = False
            self.finished.emit()

    @staticmethod
    def _load_segments(db_path: Path, source_document_id: int) -> list[Segment]:
        repo = SegmentRepository.open(db_path)
        try:
            return repo.list_segments_by_document(source_document_id)
        finally:
            repo.close()
