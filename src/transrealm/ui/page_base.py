"""Shared Qt page base for the desktop shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from transrealm.ui.worker import ServiceWorker


class WorkerPage(QWidget):
    """Base page that runs service calls through a shared ServiceWorker."""

    def __init__(self, worker: ServiceWorker) -> None:
        super().__init__()
        self._worker = worker
        self._request_counter = 0
        self._pending_request: str | None = None
        self._pending_action: str | None = None
        worker.task_done.connect(self._on_task_done)
        worker.task_error.connect(self._on_task_error)

    def _submit(self, action: str, fn: Callable[[], object]) -> None:
        self._request_counter += 1
        request_id = f"{id(self)}:{self._request_counter}"
        self._pending_request = request_id
        self._pending_action = action
        self._worker.run_requested.emit(request_id, fn)

    def _on_task_done(self, request_id: str, result: object) -> None:
        if request_id != self._pending_request:
            return
        action = self._pending_action
        self._pending_request = None
        self._pending_action = None
        if action is not None:
            self._handle_action(action, result)

    def _on_task_error(self, request_id: str, error: str) -> None:
        if request_id != self._pending_request:
            return
        self._pending_request = None
        self._pending_action = None
        self._handle_error(error)

    def _handle_action(self, action: str, result: object) -> None:
        raise NotImplementedError

    def _handle_error(self, error: str) -> None:
        raise NotImplementedError
