"""Tests for P0-T08-M01: the no-UI translation closed loop.

A single application use case (TranslationService) must wire the Phase 0
pipeline -- compose -> render -> call -> validate -> T07 finalize -- into a
vertical slice that produces a reopenable TranslationRevision. Empty segments,
missing profiles, unusable budgets and non-running runs must never reach the
adapter.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import (
    AdapterRequest,
    AdapterResponse,
    AdapterUsage,
)
from transrealm.adapters.errors import AdapterServerError
from transrealm.adapters.openai_adapter import OpenAICompatibleAdapter
from transrealm.adapters.protocol import TransportResponse
from transrealm.application.context_composer import ContextBudgetError
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.translation_service import (
    TranslationService,
    TranslationServiceError,
)
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.segment import Segment
from transrealm.domain.translation_run import TranslationRun
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_run_repository import (
    TranslationRunRepository,
)

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}


class FakeAdapter:
    """In-memory ModelAdapter that counts calls and returns a canned response."""

    def __init__(self, response: AdapterResponse | Exception) -> None:
        self.response = response
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
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeTransport:
    """In-memory transport returning a canned chat-completions response."""

    def __init__(self, response: TransportResponse) -> None:
        self.response = response
        self.calls = 0
        self.last_request: dict[str, object] | None = None

    async def post(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> TransportResponse:
        self.calls += 1
        self.last_request = body
        return self.response


def _create_project(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="M01",
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
    context_budget: dict[str, object] | None = None,
) -> ModelProfile:
    budget = context_budget if context_budget is not None else DEFAULT_BUDGET
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.create_connection(
            name="local",
            provider_type="openai-compatible",
            endpoint="http://localhost:8080/v1",
            timeout_seconds=30,
            max_retries=0,
            retry_delay_seconds=0.0,
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
                context_budget=budget,
                default_params={"temperature": 0.3},
                capability=ModelCapability(
                    context_window=128000,
                    max_output_tokens=4096,
                    supports_streaming=False,
                    supports_structured_output=False,
                    supported_parameters={"temperature", "max_tokens"},
                ),
            )
    assert profile.id is not None
    return profile


def _valid_response(stable_key: str, translation: str = "こんにちは") -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-1",
        raw_response=None,
    )


def _chat_completion_body(stable_key: str, translation: str = "こんにちは") -> bytes:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
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


def _get_segment(path: Path, segment_id: int) -> Segment:
    repo = SegmentRepository.open(path)
    try:
        segment = repo.get_by_id(segment_id)
    finally:
        repo.close()
    assert segment is not None
    return segment


def _ids(segments: list[Segment]) -> list[int]:
    """Return segment ids, narrowing the nullable id field."""
    ids: list[int] = []
    for segment in segments:
        assert segment.id is not None
        ids.append(segment.id)
    return ids


def _run(coro: Any) -> Any:
    """Run a coroutine in a temporary event loop for tests."""
    return asyncio.run(coro)


class TestSuccessClosedLoop:
    """The happy path produces a reopenable revision."""

    def test_translate_success_creates_reopenable_revision(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\nSecond line here.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key, "こんにちは"))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            revision = _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )

            assert revision.id is not None
            assert revision.segment_id == ids[0]
            assert revision.text == "こんにちは"
            assert revision.origin == "ai"
            assert fake.calls == 1

            # T07 audit records the attempt and the segment outcome.
            with TranslationRunService(path, app_version=APP_VERSION) as audit:
                attempts = audit.list_attempts_for_run(run.id)
                assert len(attempts) == 1
                assert attempts[0].status == "succeeded"
                assert attempts[0].request_id == "req-1"
                assert attempts[0].input_tokens == 10
                assert attempts[0].output_tokens == 5
                assert attempts[0].prompt_hash != ""
                assert attempts[0].context_summary != {}
                assert attempts[0].validator_summary != {}
                reopened = audit.get_revision(revision.id)
                assert reopened is not None
                assert reopened.text == "こんにちは"

            completed = _get_segment(path, ids[0])
            assert completed.status == "completed"
            assert completed.current_revision_id == revision.id

    def test_translate_success_with_real_adapter_and_fake_transport(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\nSecond line here.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
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
            capability=ModelCapability(
                context_window=128000,
                max_output_tokens=4096,
                supports_streaming=False,
                supports_structured_output=False,
                supported_parameters={"temperature", "max_tokens"},
            ),
            transport=transport,
        )

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            revision = _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )
            assert revision.text == "こんにちは"
            assert transport.calls == 1
            assert transport.last_request is not None
            messages = transport.last_request["messages"]
            assert isinstance(messages, list)
            assert "---OUTPUT CONTRACT---" in str(messages[0])
            assert "Second line here." in str(messages[0])

    def test_translate_includes_neighbor_context_and_output_contract(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(
            path,
            project_id,
            "First line.\nSecond line here.\nThird line.\n",
        )
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[1].stable_key, "二行目"))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            revision = _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[1],
                    profile_id=profile.id,
                ),
            )
            assert revision.text == "二行目"

            assert fake.last_request is not None
            prompt = fake.last_request.messages[0].content
            assert "Second line here." in prompt
            assert "First line." in prompt
            assert "Third line." in prompt
            assert "---OUTPUT CONTRACT---" in prompt
            assert '"segment_id"' in prompt

            with TranslationRunService(path, app_version=APP_VERSION) as audit:
                attempts = audit.list_attempts_for_run(run.id)
                assert len(attempts) == 1
                selected = attempts[0].context_summary.get("selected_sources")
                assert isinstance(selected, list)
                assert "CURRENT_SEGMENT" in selected
                assert "NEIGHBOR_SEGMENT" in selected


class TestNoRequestGuards:
    """Invalid inputs never reach the adapter and never claim a segment."""

    def _assert_no_attempts(self, path: Path, run_id: int) -> None:
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            assert audit.list_attempts_for_run(run_id) == []

    def test_cross_project_segment_does_not_request_or_claim(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_a = _create_project(path)
        project_b = _create_project(path)
        segment_b = _import_txt(path, project_b, "Project B source.\n")[0]
        profile = _create_profile(path)
        assert segment_b.id is not None
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segment_b.stable_key))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run_a = service.create_run(project_id=project_a)
            assert run_a.id is not None
            with pytest.raises(TranslationServiceError, match="does not belong"):
                _run(
                    service.translate_segment(
                        run_id=run_a.id,
                        segment_id=segment_b.id,
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 0
            self._assert_no_attempts(path, run_a.id)

        persisted = SegmentRepository.open(path)
        try:
            unchanged = persisted.get_by_id(segment_b.id)
        finally:
            persisted.close()
        assert unchanged is not None
        assert unchanged.status == "pending"
        assert unchanged.current_revision_id is None
        assert unchanged.lease_owner is None

    def test_empty_segment_does_not_request(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        profile = _create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key))

        repo = SegmentRepository.open(path)
        try:
            saved = repo.save_segments(
                [
                    Segment.create(
                        source_document_id=segments[0].source_document_id,
                        stable_key="empty:1",
                        source_text="",
                        sequence=99,
                    ),
                ],
            )
        finally:
            repo.close()
        empty_id = saved[0].id
        assert empty_id is not None

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(TranslationServiceError, match="empty source text"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=empty_id,
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 0
            self._assert_no_attempts(path, run.id)

    def test_missing_profile_does_not_request(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        ids = _ids(segments)
        fake = FakeAdapter(_valid_response(segments[0].stable_key))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(TranslationServiceError, match="ModelProfile with id"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=999999,
                    ),
                )
            assert fake.calls == 0
            self._assert_no_attempts(path, run.id)

    def test_insufficient_budget_does_not_request(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "This is a fairly long source line.\n")
        ids = _ids(segments)
        # available = 4 - 2 - 2 = 0, so any non-empty current segment overflows.
        profile = _create_profile(
            path,
            context_budget={"total": 4, "reserved_output": 2, "reserved_prompt": 2},
        )
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(ContextBudgetError):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 0
            self._assert_no_attempts(path, run.id)

    def test_invalid_budget_config_does_not_request(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        ids = _ids(segments)
        profile = _create_profile(
            path,
            context_budget={"total": 10, "reserved_output": 100, "reserved_prompt": 0},
        )
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(TranslationServiceError, match="context_budget"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 0
            self._assert_no_attempts(path, run.id)

    def test_missing_run_does_not_request(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            with pytest.raises(TranslationServiceError, match="TranslationRun with id"):
                _run(
                    service.translate_segment(
                        run_id=999999,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 0

    def test_non_running_run_does_not_request(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            repo = TranslationRunRepository.open(path)
            try:
                repo.save(
                    TranslationRun(
                        id=run.id,
                        project_id=run.project_id,
                        workflow_id=run.workflow_id,
                        workflow_version=run.workflow_version,
                        workflow_definition_hash=run.workflow_definition_hash,
                        workflow_definition_snapshot=run.workflow_definition_snapshot,
                        status="completed",
                        started_at=run.started_at,
                        finished_at=None,
                    ),
                )
            finally:
                repo.close()

            with pytest.raises(TranslationServiceError, match="status"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 0
            self._assert_no_attempts(path, run.id)


class TestFailureBookkeeping:
    """Known failures after the claim leave an explainable failed attempt."""

    def test_adapter_error_finalizes_failed_attempt(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(AdapterServerError("provider exploded", provider_code=500))

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(TranslationServiceError, match="Model call failed"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 1

            with TranslationRunService(path, app_version=APP_VERSION) as audit:
                attempts = audit.list_attempts_for_run(run.id)
                assert len(attempts) == 1
                assert attempts[0].status == "failed"
                assert attempts[0].retryable is True
                assert attempts[0].error_type == "server_error"
                assert attempts[0].error_message != ""

            segment = _get_segment(path, ids[0])
            assert segment.status == "failed"

    def test_invalid_output_finalizes_failed_attempt(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        fake = FakeAdapter(
            AdapterResponse(
                content="this is not json",
                finish_reason="stop",
                usage=None,
                request_id="req-bad",
                raw_response=None,
            ),
        )

        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(TranslationServiceError, match="validation"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 1

            with TranslationRunService(path, app_version=APP_VERSION) as audit:
                attempts = audit.list_attempts_for_run(run.id)
                assert len(attempts) == 1
                assert attempts[0].status == "failed"
                assert attempts[0].retryable is False
                assert attempts[0].error_type == "validation_error"
                assert attempts[0].error_message != ""

            segment = _get_segment(path, ids[0])
            assert segment.status == "failed"
            assert segment.current_revision_id is None
