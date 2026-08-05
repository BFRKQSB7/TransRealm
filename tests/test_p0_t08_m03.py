"""Tests for P0-T08-M03: failure paths and the limited repair E2E.

Adapter errors and invalid output must land in explainable failed
Attempts/Segments. A repairable validation failure triggers exactly one model
re-call as a NEW attempt with a new idempotency key; permanent errors are not
business-retried; and a crash between the repair model call and finalize stays
explainable and recoverable per the P0-T07 lease semantics.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.adapters.errors import AdapterAuthenticationError
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import (
    TranslationRunService,
    TranslationRunServiceError,
)
from transrealm.application.translation_service import (
    TranslationService,
    TranslationServiceError,
)
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.segment import Segment
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}


class SimulatedCrashError(RuntimeError):
    """Simulates a process death between two statements."""


class SequenceAdapter:
    """In-memory ModelAdapter returning a fixed sequence of responses.

    The last item is repeated once the sequence is exhausted, so a test can
    prove how many model calls a scenario makes.
    """

    def __init__(self, responses: list[AdapterResponse | Exception]) -> None:
        self.responses = responses
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


class AdvanceableClock:
    """A controllable UTC clock for lease/recovery tests."""

    def __init__(self) -> None:
        self._now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _create_project(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="M03",
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


def _create_profile(path: Path) -> int:
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.create_connection(
            name="local",
            provider_type="openai-compatible",
            endpoint="http://localhost:8080/v1",
            timeout_seconds=30,
            max_retries=0,
            retry_delay_seconds=0.0,
            credential_reference=None,
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
    return profile.id


def _response(stable_key: str, translation: str) -> AdapterResponse:
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


def _repairable_empty(stable_key: str) -> AdapterResponse:
    return _response(stable_key, "")


def _repairable_contaminated(stable_key: str) -> AdapterResponse:
    return _response(stable_key, "```\nこんにちは\n```")


def _non_repairable_unknown_id() -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": "hallucinated-id", "translation": "x"}]},
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-1",
        raw_response=None,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _get_segment(path: Path, segment_id: int) -> Segment:
    repo = SegmentRepository.open(path)
    try:
        segment = repo.get_by_id(segment_id)
    finally:
        repo.close()
    assert segment is not None
    return segment


def _translate(
    path: Path,
    *,
    project_id: int,
    segment_id: int,
    profile_id: int,
    adapter: Any,
    clock: AdvanceableClock | None = None,
    max_repair_attempts: int = 1,
) -> Any:
    service = TranslationService(
        path,
        app_version=APP_VERSION,
        adapter=adapter,
        clock=clock,
    )
    try:
        run = service.create_run(project_id=project_id)
        assert run.id is not None
        return _run(
            service.translate_segment(
                run_id=run.id,
                segment_id=segment_id,
                profile_id=profile_id,
                max_repair_attempts=max_repair_attempts,
            ),
        ), run.id
    finally:
        service.close()


class TestRepairSuccess:
    """A repairable failure triggers exactly one repair re-call as a new attempt."""

    def test_repairable_empty_translation_repairs_on_second_call(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        adapter = SequenceAdapter([
            _repairable_empty(segment.stable_key),
            _response(segment.stable_key, "こんにちは"),
        ])

        revision, run_id = _translate(
            path,
            project_id=project_id,
            segment_id=segment.id,
            profile_id=profile_id,
            adapter=adapter,
        )

        assert revision.text == "こんにちは"
        assert adapter.calls == 2

        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            assert len(attempts) == 2
            first, second = attempts
            assert first.status == "failed"
            assert first.retryable is True
            assert first.error_type == "validation_error"
            assert second.status == "succeeded"
            assert second.request_id == "req-1"
            assert second.idempotency_key != first.idempotency_key
            # The repair re-sends the same rendered prompt, honestly recorded.
            assert second.prompt_hash == first.prompt_hash
            assert second.validator_summary.get("repair_attempt") == 1
            repair_reason = second.validator_summary.get("repair_reason")
            assert isinstance(repair_reason, str)
            assert "empty" in repair_reason

        completed = _get_segment(path, segment.id)
        assert completed.status == "completed"
        assert completed.current_revision_id == revision.id

    def test_repairable_contamination_repairs(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        adapter = SequenceAdapter([
            _repairable_contaminated(segment.stable_key),
            _response(segment.stable_key, "こんにちは"),
        ])

        revision, _run_id = _translate(
            path,
            project_id=project_id,
            segment_id=segment.id,
            profile_id=profile_id,
            adapter=adapter,
        )

        assert revision.text == "こんにちは"
        assert adapter.calls == 2


class TestRepairBoundary:
    """The repair budget is bounded and permanent errors are not retried."""

    def test_repair_exhausted_finalizes_permanent_failure(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        adapter = SequenceAdapter([
            _repairable_empty(segment.stable_key),
            _repairable_empty(segment.stable_key),
        ])

        with pytest.raises(TranslationServiceError, match="validation"):
            _translate(
                path,
                project_id=project_id,
                segment_id=segment.id,
                profile_id=profile_id,
                adapter=adapter,
            )

        assert adapter.calls == 2
        run_id = _latest_run_id(path, project_id)
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            assert len(attempts) == 2
            assert attempts[0].status == "failed"
            assert attempts[0].retryable is True
            assert attempts[1].status == "failed"
            assert attempts[1].retryable is False

        segment_state = _get_segment(path, segment.id)
        assert segment_state.status == "failed"
        assert segment_state.current_revision_id is None

    def test_max_repair_attempts_zero_disables_repair(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        adapter = SequenceAdapter([_repairable_empty(segment.stable_key)])

        with pytest.raises(TranslationServiceError, match="validation"):
            _translate(
                path,
                project_id=project_id,
                segment_id=segment.id,
                profile_id=profile_id,
                adapter=adapter,
                max_repair_attempts=0,
            )

        assert adapter.calls == 1

    def test_negative_repair_attempts_rejected_before_call(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        adapter = SequenceAdapter([_response(segment.stable_key, "こんにちは")])

        with pytest.raises(TranslationServiceError, match="non-negative"):
            _translate(
                path,
                project_id=project_id,
                segment_id=segment.id,
                profile_id=profile_id,
                adapter=adapter,
                max_repair_attempts=-1,
            )

        assert adapter.calls == 0

    def test_non_repairable_output_single_attempt_no_recall(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        adapter = SequenceAdapter([_non_repairable_unknown_id()])

        with pytest.raises(TranslationServiceError, match="UNKNOWN_ID"):
            _translate(
                path,
                project_id=project_id,
                segment_id=segment.id,
                profile_id=profile_id,
                adapter=adapter,
            )

        assert adapter.calls == 1
        run_id = _latest_run_id(path, project_id)
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            assert len(attempts) == 1
            assert attempts[0].status == "failed"
            assert attempts[0].retryable is False
            assert attempts[0].error_type == "validation_error"

    def test_permanent_adapter_error_is_not_business_retried(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        adapter = SequenceAdapter([
            AdapterAuthenticationError("invalid api key", provider_code=401),
        ])

        with pytest.raises(TranslationServiceError, match="authentication_error"):
            _translate(
                path,
                project_id=project_id,
                segment_id=segment.id,
                profile_id=profile_id,
                adapter=adapter,
            )

        assert adapter.calls == 1
        run_id = _latest_run_id(path, project_id)
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            assert len(attempts) == 1
            assert attempts[0].status == "failed"
            assert attempts[0].retryable is False
            assert attempts[0].error_type == "authentication_error"

        with TranslationRunService(path, app_version=APP_VERSION) as service:
            with pytest.raises(TranslationRunServiceError, match="permanent"):
                service.retry_failed(segment_id=segment.id)


class TestCrashRecovery:
    """A crash between the repair model call and finalize stays recoverable."""

    def test_crash_mid_repair_recovers_and_retranslates(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello world.\n")
        segment = segments[0]
        assert segment.id is not None
        profile_id = _create_profile(path)
        clock = AdvanceableClock()
        crash_adapter = SequenceAdapter([
            _repairable_empty(segment.stable_key),
            SimulatedCrashError("process died before finalize"),
        ])

        service = TranslationService(
            path,
            app_version=APP_VERSION,
            adapter=crash_adapter,
            clock=clock,
        )
        try:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(SimulatedCrashError):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=segment.id,
                        profile_id=profile_id,
                    ),
                )
            run_id = run.id
        finally:
            service.close()

        # The repair attempt was claimed but never finalized: segment is stuck
        # processing under the second attempt with a still-valid lease.
        stuck = _get_segment(path, segment.id)
        assert stuck.status == "processing"
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            assert len(attempts) == 2
            assert attempts[0].status == "failed"
            assert attempts[0].retryable is True
            assert attempts[1].status == "created"

        # Restart: the lease expires and startup recovery returns the segment
        # to pending while marking the stale repair attempt cancelled.
        clock.advance(120)
        with TranslationRunService(path, app_version=APP_VERSION, clock=clock) as recovery:
            assert recovery.recover_expired_leases() == 1
            attempts = recovery.list_attempts_for_run(run_id)
            assert attempts[1].status == "cancelled"
            assert attempts[1].error_type == "lease_expired"

        recovered = _get_segment(path, segment.id)
        assert recovered.status == "pending"

        # Re-translate succeeds as a fresh run; the original run stays explainable.
        good_adapter = SequenceAdapter([_response(segment.stable_key, "こんにちは")])
        revision, retranslated_run_id = _translate(
            path,
            project_id=project_id,
            segment_id=segment.id,
            profile_id=profile_id,
            adapter=good_adapter,
        )
        assert revision.text == "こんにちは"

        final_segment = _get_segment(path, segment.id)
        assert final_segment.status == "completed"
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            original_attempts = audit.list_attempts_for_run(run_id)
            assert len(original_attempts) == 2
            assert original_attempts[0].status == "failed"
            assert original_attempts[1].status == "cancelled"
            retried = audit.list_attempts_for_run(retranslated_run_id)
            assert len(retried) == 1
            assert retried[0].status == "succeeded"


def _latest_run_id(path: Path, project_id: int) -> int:
    with TranslationRunService(path, app_version=APP_VERSION) as service:
        runs = service.list_runs_for_project(project_id)
        assert runs
        run_id = runs[-1].id
        assert run_id is not None
        return run_id
