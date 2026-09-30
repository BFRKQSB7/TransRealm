"""T03 facade, overflow and Stop/Resume acceptance journey."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from transrealm.adapters.dto import AdapterMessage, AdapterRequest, AdapterResponse
from transrealm.adapters.errors import (
    AdapterContextOverflowError,
    AdapterValidationError,
    classify_http_error,
)
from transrealm.adapters.openai_adapter import OpenAICompatibleAdapter
from transrealm.adapters.protocol import TransportResponse
from transrealm.application.glossary_service import GlossaryService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_facade import TranslationFacade
from transrealm.application.translation_run_service import TranslationRunServiceError
from transrealm.application.translation_service import TranslationServiceError
from transrealm.domain.model_profile import ModelCapability
from transrealm.infrastructure.database import create_database, transaction
from transrealm.ui.worker import TranslationWorker

APP_VERSION = "0.2.0"


class ControlledAdapter:
    def __init__(self, *, overflow_first: bool = False, overflow_always: bool = False) -> None:
        self.overflow_first = overflow_first
        self.overflow_always = overflow_always
        self.target_key = ""
        self.requests: list[AdapterRequest] = []
        self.on_call: object = None

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
        self.requests.append(request)
        if callable(self.on_call):
            self.on_call()
        if self.overflow_always or (self.overflow_first and len(self.requests) == 1):
            raise AdapterContextOverflowError(
                "Provider context window was exceeded.", provider_code="context_length_exceeded"
            )
        return AdapterResponse(
            content=json.dumps({"items": [{
                "segment_id": self.target_key,
                "translation": "译文",
            }]}),
            finish_reason="stop",
            usage=None,
            request_id=f"request-{len(self.requests)}",
            raw_response=None,
        )


def _profile(db_path: Path) -> int:
    with ProviderConnectionService(db_path, app_version=APP_VERSION) as connections:
        connection = connections.create_connection(
            name="controlled",
            provider_type="openai-compatible",
            endpoint="http://127.0.0.1:1/v1",
            timeout_seconds=5,
            max_retries=0,
            retry_delay_seconds=0.0,
            credential_reference="env:TRANSREALM_TEST_UNUSED",
        )
        assert connection.id is not None
    with ModelProfileService(db_path, app_version=APP_VERSION) as profiles:
        profile = profiles.create_profile(
            name="controlled",
            provider_connection_id=connection.id,
            model_id="controlled-model",
            template_version="1.0.0",
            output_protocol="json",
            context_budget={"total": 4096, "reserved_output": 512, "reserved_prompt": 512},
            default_params={},
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


def test_facade_restart_resume_manual_lock_export(tmp_path: Path) -> None:
    db_path = tmp_path / "job.sqlite"
    adapter = ControlledAdapter()
    with TranslationFacade(db_path, app_version=APP_VERSION, adapter=adapter) as facade:
        job = facade.create_job(name="Novel", source_language="zh", target_language="en")
        assert job.id is not None
        profile_id = _profile(db_path)
        facade.select_active_profile(job.id, profile_id)
        facade.set_notes(job.id, "Keep names consistent")
        source = tmp_path / "novel.txt"
        source.write_text("第一句。\n第二句。\n", encoding="utf-8")
        document, segments = facade.import_document(job.id, source)
        other = tmp_path / "strings.json"
        other.write_text('{"title":"标题"}', encoding="utf-8")
        second_document, _ = facade.import_document(job.id, other)
        assert len(facade.list_documents(job.id)) == 2
        active = facade.active_profile(job.id)
        assert active is not None and active.id == profile_id
        configuration = facade.active_configuration(job.id)
        assert configuration is not None
        assert configuration.provider_name == "controlled"
        assert configuration.model_id == "controlled-model"
        assert not configuration.has_prompt_override
        assert facade.notes(job.id) == "Keep names consistent"
        assert document.id is not None and second_document.id is not None
        assert len(segments) == 2
        assert segments[0].id is not None
        adapter.target_key = segments[0].stable_key
        run = facade.start_run(job.id)
        assert run.id is not None
        first = asyncio.run(facade.translate_segment(
            run_id=run.id, segment_id=segments[0].id, profile_id=profile_id
        ))
        assert first.id is not None
        facade.stop(run.id)
        assert [row.status for row in facade.progress(document.id)] == ["completed", "pending"]

    with TranslationFacade(db_path, app_version=APP_VERSION, adapter=adapter) as reopened:
        assert reopened.open_job(job.id) is not None
        run = reopened.resume(job.id)
        assert run.id is not None and segments[1].id is not None
        adapter.target_key = segments[1].stable_key
        asyncio.run(reopened.translate_segment(
            run_id=run.id, segment_id=segments[1].id, profile_id=profile_id
        ))
        reopened.finish_run(run.id, status="completed")
        manual = reopened.save_manual_revision(segments[0].id, "人工译文")
        assert manual.id is not None
        reopened.select_revision(segments[0].id, manual.id)
        locked = reopened.lock_current(segments[0].id)
        assert locked.is_locked
        assert len(reopened.revisions(segments[0].id)) == 2
        target = tmp_path / "translated.txt"
        reopened.export_document(document.id, target)
        assert target.read_text(encoding="utf-8") == "人工译文\n译文\n"
        assert all(row.status == "completed" for row in reopened.progress(document.id))
    assert len(adapter.requests) == 2


def test_context_overflow_creates_new_audited_attempt(tmp_path: Path) -> None:
    db_path = tmp_path / "overflow.sqlite"
    adapter = ControlledAdapter(overflow_first=True)
    with TranslationFacade(db_path, app_version=APP_VERSION, adapter=adapter) as facade:
        job = facade.create_job(name="Overflow", source_language="zh", target_language="en")
        assert job.id is not None
        profile_id = _profile(db_path)
        facade.set_notes(job.id, "Protected notes")
        with GlossaryService(db_path, app_version=APP_VERSION) as glossary:
            glossary.create_entry(
                project_id=job.id, source_term="TARGET", target_term="目标",
                scope="project", is_locked=True,
            )
        source = tmp_path / "story.txt"
        source.write_text("before\nTARGET\nafter\n", encoding="utf-8")
        document, segments = facade.import_document(job.id, source)
        assert document.id is not None and segments[1].id is not None
        adapter.target_key = segments[1].stable_key
        run = facade.start_run(job.id)
        assert run.id is not None
        revision = asyncio.run(facade.translate_segment(
            run_id=run.id, segment_id=segments[1].id, profile_id=profile_id
        ))
        assert revision.id is not None
        attempts = facade.attempts(run.id)
        assert len(attempts) == 2
        assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
        assert attempts[0].error_type == "context_overflow"
        assert attempts[0].retryable
        assert attempts[0].prompt_hash != attempts[1].prompt_hash
        assert attempts[1].context_summary["overflow_reductions"] == 1
        assert attempts[0].idempotency_key != attempts[1].idempotency_key
        assert len(adapter.requests) == 2
        for request in adapter.requests:
            prompt = request.messages[0].content
            assert "TARGET" in prompt and "Protected notes" in prompt and "目标" in prompt
        facade.finish_run(run.id, status="completed")


def test_overflow_without_optional_context_fails_safely(tmp_path: Path) -> None:
    db_path = tmp_path / "overflow.sqlite"
    adapter = ControlledAdapter(overflow_first=True)
    with TranslationFacade(db_path, app_version=APP_VERSION, adapter=adapter) as facade:
        job = facade.create_job(name="One", source_language="zh", target_language="en")
        assert job.id is not None
        profile_id = _profile(db_path)
        source = tmp_path / "one.txt"
        source.write_text("TARGET", encoding="utf-8")
        document, segments = facade.import_document(job.id, source)
        assert document.id is not None and segments[0].id is not None
        adapter.target_key = segments[0].stable_key
        run = facade.start_run(job.id)
        assert run.id is not None
        with pytest.raises(TranslationServiceError, match="context overflow"):
            asyncio.run(facade.translate_segment(
                run_id=run.id, segment_id=segments[0].id, profile_id=profile_id
            ))
        attempts = facade.attempts(run.id)
        assert len(attempts) == 1 and not attempts[0].retryable
        assert facade.progress(document.id)[0].status == "failed"
        facade.finish_run(run.id, status="failed")


def test_overflow_classification_uses_only_provider_code() -> None:
    error = classify_http_error(
        400, "Provider returned HTTP 400", provider_code="context_length_exceeded"
    )
    assert isinstance(error, AdapterContextOverflowError)
    assert error.safe_message == "Provider context window was exceeded."
    other = classify_http_error(400, "Provider returned HTTP 400", provider_code="other")
    assert type(other) is AdapterValidationError


def test_openai_adapter_redacts_overflow_body() -> None:
    class OverflowTransport:
        async def post(
            self, path: str, headers: dict[str, str], body: dict[str, object], timeout: float
        ) -> TransportResponse:
            return TransportResponse(
                status_code=400,
                headers={},
                body=b'{"error":{"code":"context_length_exceeded",'
                     b'"message":"SECRET provider prose"}}',
                elapsed_seconds=0.01,
            )

    adapter = OpenAICompatibleAdapter(
        endpoint="http://127.0.0.1:1/v1",
        model_id="controlled",
        capability=ControlledAdapter().get_capabilities(),
        transport=OverflowTransport(),
    )
    request = AdapterRequest(
        model_id="controlled", messages=(AdapterMessage(role="user", content="Translate"),)
    )
    with pytest.raises(AdapterContextOverflowError) as captured:
        asyncio.run(adapter.chat_completion(request))
    assert "SECRET" not in str(captured.value)


def test_overflow_reduction_is_bounded(tmp_path: Path) -> None:
    db_path = tmp_path / "bounded.sqlite"
    adapter = ControlledAdapter(overflow_always=True)
    with TranslationFacade(db_path, app_version=APP_VERSION, adapter=adapter) as facade:
        job = facade.create_job(name="Bounded", source_language="zh", target_language="en")
        assert job.id is not None
        profile_id = _profile(db_path)
        source = tmp_path / "many.txt"
        source.write_text("A\nB\nC\nTARGET\nD\nE\nF\n", encoding="utf-8")
        document, segments = facade.import_document(job.id, source)
        assert document.id is not None and segments[3].id is not None
        adapter.target_key = segments[3].stable_key
        run = facade.start_run(job.id)
        assert run.id is not None
        with pytest.raises(TranslationServiceError, match="context overflow"):
            asyncio.run(facade.translate_segment(
                run_id=run.id, segment_id=segments[3].id, profile_id=profile_id
            ))
        attempts = facade.attempts(run.id)
        assert len(attempts) == 4
        assert [attempt.context_summary["overflow_reductions"] for attempt in attempts] == [
            0, 1, 2, 3
        ]
        assert len({attempt.prompt_hash for attempt in attempts}) == 4
        assert all(attempt.status == "failed" for attempt in attempts)
        assert not attempts[-1].retryable
        assert facade.progress(document.id)[3].status == "failed"


def test_worker_stop_before_claim_and_during_request(tmp_path: Path) -> None:
    db_path = tmp_path / "worker.sqlite"
    adapter = ControlledAdapter()
    with TranslationFacade(db_path, app_version=APP_VERSION) as facade:
        job = facade.create_job(name="Worker", source_language="zh", target_language="en")
        assert job.id is not None
        profile_id = _profile(db_path)
        source = tmp_path / "worker.txt"
        source.write_text("甲。\n乙。\n", encoding="utf-8")
        document, segments = facade.import_document(job.id, source)
        assert document.id is not None and segments[0].id is not None
    worker = TranslationWorker(db_path, app_version=APP_VERSION, adapter_factory=lambda _: adapter)
    worker.request_stop()
    worker.translate(job.id, document.id, profile_id)
    assert not adapter.requests
    with TranslationFacade(db_path, app_version=APP_VERSION) as facade:
        assert facade.runs(job.id)[-1].status == "cancelled"
        assert [row.status for row in facade.progress(document.id)] == ["pending", "pending"]

    adapter.target_key = segments[0].stable_key
    adapter.on_call = worker.request_stop
    worker.translate(job.id, document.id, profile_id)
    with TranslationFacade(db_path, app_version=APP_VERSION) as facade:
        stopped_run = facade.runs(job.id)[-1]
        assert stopped_run.status == "cancelled"
        assert stopped_run.id is not None
        assert [row.status for row in facade.progress(document.id)] == ["completed", "pending"]
        assert len(facade.attempts(stopped_run.id)) == 1

    adapter.on_call = None
    adapter.target_key = segments[1].stable_key
    worker.translate(job.id, document.id, profile_id)
    with TranslationFacade(db_path, app_version=APP_VERSION) as facade:
        assert facade.runs(job.id)[-1].status == "completed"
        assert [row.status for row in facade.progress(document.id)] == ["completed", "completed"]
    assert len(adapter.requests) == 2


def test_late_result_after_lock_is_cancelled_without_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "lock.sqlite"
    adapter = ControlledAdapter()
    with TranslationFacade(db_path, app_version=APP_VERSION, adapter=adapter) as facade:
        job = facade.create_job(name="Lock", source_language="zh", target_language="en")
        assert job.id is not None
        profile_id = _profile(db_path)
        source = tmp_path / "lock.txt"
        source.write_text("待译文本。", encoding="utf-8")
        document, segments = facade.import_document(job.id, source)
        assert document.id is not None and segments[0].id is not None
        segment_id = segments[0].id
        manual = facade.save_manual_revision(segment_id, "受保护译文")
        assert manual.id is not None
        db = create_database(db_path)
        try:
            with transaction(db):
                db.execute("UPDATE segments SET status = 'pending' WHERE id = ?", (segment_id,))
        finally:
            db.close()
        adapter.target_key = segments[0].stable_key
        adapter.on_call = lambda: facade.lock_current(segment_id)
        run = facade.start_run(job.id)
        assert run.id is not None
        with pytest.raises(TranslationRunServiceError, match="locked"):
            asyncio.run(facade.translate_segment(
                run_id=run.id, segment_id=segment_id, profile_id=profile_id
            ))
        assert len(facade.attempts(run.id)) == 1
        assert facade.attempts(run.id)[0].status == "cancelled"
        assert facade.progress(document.id)[0].status == "completed"
        revisions = facade.revisions(segment_id)
        assert len(revisions) == 1 and revisions[0].id == manual.id
        assert revisions[0].is_locked
        facade.finish_run(run.id, status="failed")
