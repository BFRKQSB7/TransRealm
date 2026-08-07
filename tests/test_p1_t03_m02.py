"""P1-T03-M02: capability-aware workbench.

M02 surfaces the workbench: real Segment/Attempt progress and the active
Profile, with a parameter surface that only presents/sends the parameters the
Profile's capability declares as supported. Parameter changes form the next
Attempt's snapshot (recorded in ``profile_snapshot.request_params``) and never
rewrite completed attempts or revisions; the adapter remains the final filter
so unsupported parameters are never sent.

Service-level tests cover the parameter snapshot, the double-insurance adapter
filter, and the real progress read; pytest-qt tests cover the workbench surface
(progress list, profile/capability info, capability-driven parameter editor)
and that auto mode is unchanged.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.adapters.errors import AdapterServerError
from transrealm.adapters.openai_adapter import OpenAICompatibleAdapter
from transrealm.adapters.protocol import TransportResponse
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.translation_service import (
    TranslationService,
    TranslationServiceError,
)
from transrealm.application.workbench import initial_param_values, presented_parameters
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.project import MODE_WORKBENCH
from transrealm.domain.segment import Segment
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.ui.main_window import MainWindow
from transrealm.ui.workbench import WorkbenchParamEditor

APP_VERSION = "0.1.0"
DEFAULT_BUDGET: dict[str, object] = {
    "total": 8192,
    "reserved_output": 1024,
    "reserved_prompt": 1024,
}


# --------------------------------------------------------------------------- #
# Shared helpers (service level)
# --------------------------------------------------------------------------- #


class RecordingAdapter:
    """In-memory ModelAdapter recording every request it receives."""

    def __init__(self, responses: list[AdapterResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.last_request: AdapterRequest | None = None

    def get_capabilities(self) -> ModelCapability:
        return ModelCapability(
            context_window=128000,
            max_output_tokens=4096,
            supports_streaming=False,
            supports_structured_output=False,
            supported_parameters={"temperature", "max_tokens"},
        )

    def filter_params(self, params: dict[str, object]) -> dict[str, object]:
        return params

    async def chat_completion(self, request: AdapterRequest) -> AdapterResponse:
        self.calls += 1
        self.last_request = request
        index = min(self.calls - 1, len(self.responses) - 1)
        item = self.responses[index]
        if isinstance(item, Exception):
            raise item
        return item


class FakeTransport:
    """In-memory transport recording the request body it was asked to send."""

    def __init__(self, response: TransportResponse) -> None:
        self.response = response
        self.last_request: dict[str, object] | None = None

    async def post(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> TransportResponse:
        self.last_request = body
        return self.response


def _create_project(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="M02",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_txt(path: Path, project_id: int, content: str) -> list[Segment]:
    txt_path = path.parent / "source.txt"
    txt_path.write_text(content, encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as service:
        _document, segments = service.import_txt(project_id, txt_path, name="source.txt")
    return segments


def _create_profile(
    path: Path,
    *,
    capability: ModelCapability | None = None,
    default_params: dict[str, object] | None = None,
) -> ModelProfile:
    cap = capability or ModelCapability(
        context_window=128000,
        max_output_tokens=4096,
        supports_streaming=False,
        supports_structured_output=False,
        supported_parameters={"temperature", "max_tokens"},
    )
    params: dict[str, object] = (
        default_params if default_params is not None else {"temperature": 0.3}
    )
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.create_connection(
            name="local",
            provider_type="openai-compatible",
            endpoint="http://localhost:8080/v1",
            credential_reference="env:OPENAI_API_KEY",
        )
        assert connection.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profile_service:
            profile = profile_service.create_profile(
                name="general",
                provider_connection_id=connection.id,
                model_id="gpt-4o-mini",
                template_version="1.0.0",
                output_protocol="json",
                context_budget=DEFAULT_BUDGET,
                default_params=params,
                capability=cap,
            )
    assert profile.id is not None
    return profile


def _valid_response(stable_key: str, translation: str) -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-m02",
        raw_response=None,
    )


def _chat_completion_body(stable_key: str) -> bytes:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": "こんにちは"}]},
        ensure_ascii=False,
    )
    return json.dumps(
        {
            "id": "req-real",
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"},
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        },
    ).encode("utf-8")


def _ids(segments: list[Segment]) -> list[int]:
    ids: list[int] = []
    for segment in segments:
        assert segment.id is not None
        ids.append(segment.id)
    return ids


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Capability-aware parameter snapshot (application service)
# --------------------------------------------------------------------------- #


class TestCapabilityAwareParamSnapshot:
    """Workbench parameters are sent for the next attempt and snapshotted."""

    def test_translate_segment_sends_workbench_params_and_records_snapshot(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        adapter = RecordingAdapter([_valid_response(segments[0].stable_key, "こんにちは")])
        params: dict[str, object] = {"temperature": 0.9, "max_tokens": 2048}

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                    extra_params=params,
                ),
            )

        assert adapter.last_request is not None
        assert adapter.last_request.extra_params == params
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run.id)
            assert len(attempts) == 1
            assert attempts[0].profile_snapshot["request_params"] == params

    def test_param_change_snapshots_next_attempt_not_history(
        self,
        tmp_path: Path,
    ) -> None:
        """A later parameter change never rewrites an earlier attempt/revision."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "One.\nTwo.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        adapter = RecordingAdapter(
            [
                _valid_response(segments[0].stable_key, "一"),
                _valid_response(segments[1].stable_key, "二"),
            ],
        )
        params_a: dict[str, object] = {"temperature": 0.3, "max_tokens": 512}
        params_b: dict[str, object] = {"temperature": 0.8, "max_tokens": 1024}

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            revision_a = _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                    extra_params=params_a,
                ),
            )
            revision_b = _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[1],
                    profile_id=profile.id,
                    extra_params=params_b,
                ),
            )

        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run.id)
            by_segment = {attempt.segment_id: attempt for attempt in attempts}
            assert by_segment[ids[0]].profile_snapshot["request_params"] == params_a
            assert by_segment[ids[1]].profile_snapshot["request_params"] == params_b
            loaded_a = audit.get_revision(revision_a.id)
            loaded_b = audit.get_revision(revision_b.id)
            assert loaded_a is not None
            assert loaded_b is not None
            assert loaded_a.text == "一"
            assert loaded_b.text == "二"

    def test_translate_without_params_uses_profile_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        ids = _ids(segments)
        profile = _create_profile(path, default_params={"temperature": 0.3})
        assert profile.id is not None
        adapter = RecordingAdapter([_valid_response(segments[0].stable_key, "こんにちは")])

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )

        assert adapter.last_request is not None
        assert adapter.last_request.extra_params == {"temperature": 0.3}
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run.id)
            assert attempts[0].profile_snapshot["request_params"] == {"temperature": 0.3}

    def test_adapter_filters_unsupported_params_before_send(self, tmp_path: Path) -> None:
        """Double insurance: the adapter never sends a parameter it cannot support."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        ids = _ids(segments)
        capability = ModelCapability(
            context_window=128000,
            max_output_tokens=4096,
            supports_streaming=False,
            supports_structured_output=False,
            supported_parameters={"temperature"},
        )
        profile = _create_profile(path, capability=capability)
        assert profile.id is not None

        transport = FakeTransport(
            TransportResponse(
                status_code=200,
                headers={},
                body=_chat_completion_body(segments[0].stable_key),
                elapsed_seconds=0.1,
            ),
        )
        adapter = OpenAICompatibleAdapter(
            endpoint="https://api.example.com",
            model_id=profile.model_id,
            capability=capability,
            transport=transport,
        )

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                    extra_params={"temperature": 0.5, "top_k": 999, "top_p": 0.8},
                ),
            )

        assert transport.last_request is not None
        assert transport.last_request["temperature"] == 0.5
        assert "top_k" not in transport.last_request
        assert "top_p" not in transport.last_request


# --------------------------------------------------------------------------- #
# Real Segment/Attempt progress read
# --------------------------------------------------------------------------- #


class TestSegmentProgress:
    """list_segment_progress reflects the persisted segment and attempt state."""

    def test_progress_without_attempts(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "One.\nTwo.\n")
        document_id = segments[0].source_document_id

        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            progress = audit.list_segment_progress(source_document_id=document_id)

        assert [item.stable_key for item in progress] == [
            segment.stable_key for segment in segments
        ]
        assert [item.status for item in progress] == ["pending", "pending"]
        assert all(item.attempt_status is None for item in progress)
        assert all(item.attempt_error is None for item in progress)
        assert all(item.current_revision_id is None for item in progress)

    def test_progress_reflects_completed_and_failed_attempts(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "One.\nTwo.\n")
        ids = _ids(segments)
        document_id = segments[0].source_document_id
        profile = _create_profile(path)
        assert profile.id is not None
        adapter = RecordingAdapter(
            [
                _valid_response(segments[0].stable_key, "一"),
                AdapterServerError("provider exploded", provider_code=500),
            ],
        )

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )
            with pytest.raises(TranslationServiceError, match="Model call failed"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[1],
                        profile_id=profile.id,
                    ),
                )

        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            progress = audit.list_segment_progress(source_document_id=document_id)
        by_key = {item.stable_key: item for item in progress}
        ok = by_key[segments[0].stable_key]
        bad = by_key[segments[1].stable_key]
        assert ok.status == "completed"
        assert ok.attempt_status == "succeeded"
        assert ok.current_revision_id is not None
        assert bad.status == "failed"
        assert bad.attempt_status == "failed"
        assert bad.attempt_error != ""
        assert bad.current_revision_id is None

    def test_progress_prefers_latest_attempt_after_repair(self, tmp_path: Path) -> None:
        """A segment with several attempts shows the latest, not the first."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "One.\n")
        ids = _ids(segments)
        document_id = segments[0].source_document_id
        profile = _create_profile(path)
        assert profile.id is not None
        # A repairable-empty output then a valid one: the single translate call
        # claims the segment twice (first attempt fails, the repair succeeds).
        empty_content = json.dumps(
            {"items": [{"segment_id": segments[0].stable_key, "translation": ""}]},
            ensure_ascii=False,
        )
        adapter = RecordingAdapter(
            [
                AdapterResponse(
                    content=empty_content,
                    finish_reason="stop",
                    usage=None,
                    request_id="req-repair",
                    raw_response=None,
                ),
                _valid_response(segments[0].stable_key, "一"),
            ],
        )

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )

        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run.id)
            assert len(attempts) == 2  # the repair created a second attempt
            progress = audit.list_segment_progress(source_document_id=document_id)
        assert progress[0].status == "completed"
        assert progress[0].attempt_status == "succeeded"


# --------------------------------------------------------------------------- #
# Pure capability-aware parameter policy
# --------------------------------------------------------------------------- #


class TestParamPolicy:
    def test_presented_parameters_sorted_supported_only(self) -> None:
        cap = ModelCapability(128000, 4096, False, False, {"max_tokens", "temperature"})
        assert presented_parameters(cap) == ("max_tokens", "temperature")

    def test_initial_values_use_default_params_and_spec_defaults(self) -> None:
        cap = ModelCapability(128000, 4096, False, False, {"temperature", "max_tokens"})
        values = initial_param_values(cap, {"temperature": 0.3})
        assert values == {"max_tokens": 2048, "temperature": 0.3}

    def test_max_tokens_clamped_to_capability_limit(self) -> None:
        cap = ModelCapability(128000, 256, False, False, {"max_tokens"})
        values = initial_param_values(cap, {"max_tokens": 5000})
        assert values == {"max_tokens": 256}

    def test_unknown_supported_parameter_keeps_raw_value(self) -> None:
        cap = ModelCapability(128000, 4096, False, False, {"custom_param"})
        assert initial_param_values(cap, {"custom_param": "abc"}) == {"custom_param": "abc"}
        assert initial_param_values(cap, {}) == {"custom_param": ""}


# --------------------------------------------------------------------------- #
# Workbench parameter editor widget
# --------------------------------------------------------------------------- #


class TestWorkbenchParamEditor:
    def test_editor_omits_unsupported_default_params(self, qtbot: Any) -> None:
        cap = ModelCapability(128000, 4096, False, False, {"temperature"})
        editor = WorkbenchParamEditor(cap, {"temperature": 0.3, "top_p": 0.9})
        qtbot.addWidget(editor)
        assert editor.values() == {"temperature": 0.3}

    def test_editor_caps_max_tokens_to_capability_limit(self, qtbot: Any) -> None:
        cap = ModelCapability(128000, 256, False, False, {"max_tokens"})
        editor = WorkbenchParamEditor(cap, {"max_tokens": 9999})
        qtbot.addWidget(editor)
        assert editor.values() == {"max_tokens": 256}
        # The control range is bounded by the capability, so a user edit cannot
        # raise max_tokens above the model's output limit either.
        max_tokens = _param_widget(editor, "max_tokens")
        max_tokens.setValue(999999)
        assert editor.values() == {"max_tokens": 256}

    def test_editor_accepts_initial_values(self, qtbot: Any) -> None:
        cap = ModelCapability(128000, 4096, False, False, {"temperature", "max_tokens"})
        editor = WorkbenchParamEditor(
            cap,
            {"temperature": 0.3},
            initial={"temperature": 0.9},
        )
        qtbot.addWidget(editor)
        assert editor.values()["temperature"] == 0.9

    def test_editor_presents_unknown_param_as_text(self, qtbot: Any) -> None:
        cap = ModelCapability(128000, 4096, False, False, {"custom"})
        editor = WorkbenchParamEditor(cap, {"custom": "abc"})
        qtbot.addWidget(editor)
        assert editor.values() == {"custom": "abc"}

    def test_editor_values_round_trip_after_edit(self, qtbot: Any) -> None:
        cap = ModelCapability(128000, 4096, False, False, {"temperature", "max_tokens"})
        editor = WorkbenchParamEditor(cap, {"temperature": 0.3})
        qtbot.addWidget(editor)
        temp = _param_widget(editor, "temperature")
        temp.setValue(0.9)
        assert editor.values()["temperature"] == 0.9
        assert editor.values()["max_tokens"] == 2048


# --------------------------------------------------------------------------- #
# pytest-qt: workbench surface
# --------------------------------------------------------------------------- #


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build MainWindows against a shared database path and per-window adapters."""
    created: list[MainWindow] = []

    def make(db_path: Path | None = None) -> tuple[MainWindow, dict[str, Any]]:
        holder: dict[str, Any] = {}
        window = MainWindow(
            db_path or (tmp_path / "project.sqlite"),
            app_version=APP_VERSION,
            adapter_factory=lambda profile_id: holder["adapter"],
        )
        qtbot.addWidget(window)
        created.append(window)
        return window, holder

    yield make
    for window in created:
        window.shutdown()


def _segments(db_path: Path, document_id: int) -> list[Segment]:
    repo = SegmentRepository.open(db_path)
    try:
        return repo.list_segments_by_document(document_id)
    finally:
        repo.close()


def _wait_finished(qtbot: Any, worker: Any) -> None:
    done = [False]

    def mark() -> None:
        done[0] = True

    worker.finished.connect(mark)
    qtbot.waitUntil(lambda: done[0], timeout=20000)


def _setup_profile(qtbot: Any, window: MainWindow) -> None:
    settings = window._settings
    settings._conn_name.setText("local")
    settings._conn_endpoint.setText("http://localhost:8080/v1")
    settings._add_connection.click()
    qtbot.waitUntil(lambda: settings._connections_list.count() == 1, timeout=5000)

    settings._profile_name.setText("general")
    settings._profile_model.setText("gpt-4o-mini")
    qtbot.waitUntil(lambda: settings._profile_connection.count() == 1, timeout=5000)
    settings._add_profile.click()
    qtbot.waitUntil(lambda: settings._profiles_list.count() == 1, timeout=5000)


def _activate_profile(window: MainWindow, qtbot: Any) -> None:
    project = window._project
    qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
    project._active_profile_combo.setCurrentIndex(
        project._active_profile_combo.findData(project._active_profile_combo.itemData(0)),
    )
    project._set_active.click()
    qtbot.waitUntil(
        lambda: "Active:" in project._active_profile_label.text(),
        timeout=5000,
    )


def _setup_workbench_project(
    window: MainWindow,
    qtbot: Any,
    tmp_path: Path,
    content: str = "Alpha.\nBeta.\n",
) -> tuple[int, int]:
    """Create a workbench-mode project with an active Profile and a document."""
    _setup_profile(qtbot, window)
    project = window._project
    translation = window._translation

    project._project_name.setText("Demo")
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
    assert project._project_id is not None
    project_id = project._project_id

    with ProjectService(translation._db_path, app_version=APP_VERSION) as svc:
        svc.set_mode(project_id, MODE_WORKBENCH)

    _activate_profile(window, qtbot)

    source = tmp_path / "source.txt"
    source.write_text(content, encoding="utf-8")
    project.import_file(source)
    qtbot.waitUntil(lambda: translation._document_id is not None, timeout=5000)
    assert translation._document_id is not None
    return project_id, translation._document_id


def _param_widget(editor: WorkbenchParamEditor, name: str) -> Any:
    from PySide6.QtWidgets import QFormLayout, QLabel

    layout = editor.layout()
    assert isinstance(layout, QFormLayout)
    for index in range(layout.rowCount()):
        label_item = layout.itemAt(index, QFormLayout.ItemRole.LabelRole)
        if label_item is None:
            continue
        label_widget = label_item.widget()
        if isinstance(label_widget, QLabel) and label_widget.text() == name:
            field = layout.itemAt(index, QFormLayout.ItemRole.FieldRole)
            return field.widget() if field is not None else None
    raise AssertionError(f"no control for parameter {name!r}")


class TestWorkbenchSurface:
    def test_workbench_shows_real_progress_profile_and_supported_params(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation

        qtbot.waitUntil(
            lambda: not translation._workbench_container.isHidden(),
            timeout=5000,
        )
        qtbot.waitUntil(lambda: translation._param_editor is not None, timeout=5000)

        assert "general" in translation._workbench_info.text()
        assert "supported: max_tokens, temperature" in translation._workbench_info.text()
        assert set(translation._param_editor.values()) == {"max_tokens", "temperature"}
        # Real progress: the imported document is present with two pending segments.
        qtbot.waitUntil(lambda: translation._segment_progress.count() == 2, timeout=5000)
        assert "pending" in translation._segment_progress.item(0).text()
        assert "pending" in translation._segment_progress.item(1).text()

    def test_workbench_translate_uses_editor_values_and_snapshots(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        project_id, document_id = _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._param_editor is not None, timeout=5000)

        _param_widget(translation._param_editor, "temperature").setValue(0.9)

        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = RecordingAdapter(
            [_valid_response(segment.stable_key, f"T{i}") for i, segment in enumerate(segments)],
        )

        translation.translate()
        _wait_finished(qtbot, window._translation_worker)

        adapter = holder["adapter"]
        assert adapter.calls == len(segments)
        assert adapter.last_request is not None
        assert adapter.last_request.extra_params["temperature"] == 0.9
        assert adapter.last_request.extra_params["max_tokens"] == 2048

        with TranslationRunService(tmp_path / "project.sqlite", app_version=APP_VERSION) as audit:
            runs = audit.list_runs_for_project(project_id)
            assert len(runs) == 1
            assert runs[0].id is not None
            attempts = audit.list_attempts_for_run(runs[0].id)
            assert len(attempts) == len(segments)
            for attempt in attempts:
                request_params = attempt.profile_snapshot["request_params"]
                assert isinstance(request_params, dict)
                assert request_params["temperature"] == 0.9

        # The on-finished refresh re-reads the persisted progress so the list
        # shows the completed outcome, while the parameter draft is preserved.
        qtbot.waitUntil(
            lambda: translation._segment_progress.count() == len(segments)
            and "completed" in translation._segment_progress.item(0).text(),
            timeout=5000,
        )
        assert translation._param_editor is not None
        assert translation._param_editor.values()["temperature"] == 0.9

    def test_auto_mode_hides_workbench(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        _setup_profile(qtbot, window)
        project = window._project
        translation = window._translation

        project._project_name.setText("Demo")
        project._create_project.click()
        qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
        _activate_profile(window, qtbot)

        source = tmp_path / "source.txt"
        source.write_text("Alpha.\n", encoding="utf-8")
        project.import_file(source)
        qtbot.waitUntil(lambda: translation._document_id is not None, timeout=5000)

        qtbot.waitUntil(lambda: "Mode: auto" in translation._mode_label.text(), timeout=5000)
        assert translation._workbench_container.isHidden()
        assert translation._param_editor is None

    def test_workbench_without_active_profile_shows_guidance(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        _setup_profile(qtbot, window)
        project = window._project
        translation = window._translation

        project._project_name.setText("Demo")
        project._create_project.click()
        qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
        assert project._project_id is not None

        with ProjectService(translation._db_path, app_version=APP_VERSION) as svc:
            svc.set_mode(project._project_id, MODE_WORKBENCH)

        # No active profile is set. Refreshing the Translation page surfaces the
        # recoverable guidance instead of a parameter editor.
        translation.refresh()
        qtbot.waitUntil(
            lambda: not translation._config_missing_label.isHidden(),
            timeout=5000,
        )
        assert "active profile" in translation._config_missing_label.text().lower()
        assert translation._param_editor is None
        assert translation._active_profile_id is None
