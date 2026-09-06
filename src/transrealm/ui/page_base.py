"""Shared Qt page base for the desktop shell."""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from transrealm.ui.worker import ServiceWorker


def safe_error_message(error: object) -> str:
    """Turn an internal exception into an actionable, non-sensitive UI message."""
    raw = str(error).strip()
    lowered = raw.lower()
    if "unique constraint failed: provider_connections.name" in lowered:
        return (
            "A connection with this name already exists. "
            "Choose another name or edit the existing connection."
        )
    if "unique constraint failed: model_profiles.name" in lowered:
        return (
            "A Model Profile with this name already exists. "
            "Choose another name or edit the existing profile."
        )
    if "unique constraint failed" in lowered:
        return "This name is already in use. Choose another name or edit the existing item."

    message = re.sub(
        r"(?is)\bSQL\s*:\s*.*$",
        "",
        raw,
    )
    message = re.sub(
        r"(?i)(?:password|token|api[-_ ]?key|secret|credential)\s*[:=]\s*[^\s;,)]*",
        "sensitive value redacted",
        message,
    )
    message = re.sub(r"(?i)\b[A-Z]:[\\/][^;\r\n)]*", "<local path>", message)
    message = re.sub(
        r"(?<![/:A-Za-z0-9])/(?:[^\s;()]+/)*[^\s;()]+",
        "<local path>",
        message,
    )
    message = re.sub(r"\(\s*path\s*:\s*.*?\)", "", message, flags=re.IGNORECASE)
    message = re.sub(r"\s+", " ", message).strip(" ;:")
    return message or "The operation could not be completed. Check the values and try again."


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
        self._handle_error(safe_error_message(error))

    def _handle_action(self, action: str, result: object) -> None:
        raise NotImplementedError

    def _handle_error(self, error: str) -> None:
        raise NotImplementedError
