"""Tests for P0-T07-M04: failure, cancel and startup recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import (
    BUILTIN_GENERAL_TRANSLATION_WORKFLOW,
    TranslationRunService,
    TranslationRunServiceError,
)
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.segment import Segment
from transrealm.domain.segment_attempt import SegmentAttempt
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.domain.translation_workflow import WorkflowDefinition
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)

APP_VERSION = "0.0.0-test"


def _create_project(path: Path, name: str = "Test") -> int:
    """Create a project and return its id."""
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name=name,
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_txt(path: Path, project_id: int, content: str) -> list:
    """Import a TXT file and return the created segments."""
    txt_path = path.parent / "source.txt"
    txt_path.write_text(content, encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_txt(
            project_id,
            txt_path,
            name="source.txt",
        )
    return segments


def _create_profile(path: Path) -> ModelProfile:
    """Create a provider connection and model profile."""
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
                context_budget={"total": 4096, "reserved_output": 512, "reserved_prompt": 512},
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


def _builtin_workflow(service: TranslationRunService) -> tuple[WorkflowDefinition, int]:
    """Return the seeded built-in workflow and its id, asserting it exists."""
    workflow = service._workflow_repository.get_by_name_and_version(
        BUILTIN_GENERAL_TRANSLATION_WORKFLOW.name,
        BUILTIN_GENERAL_TRANSLATION_WORKFLOW.version,
    )
    assert workflow is not None
    assert workflow.id is not None
    return workflow, workflow.id


def _claim(
    path: Path,
    project_id: int,
    segment: Segment,
    profile: ModelProfile,
    lease_duration_seconds: int = 60,
) -> tuple[TranslationRunService, SegmentAttempt]:
    """Create a run and claim the segment; return (service, attempt)."""
    service = TranslationRunService(path, app_version=APP_VERSION)
    workflow, workflow_id = _builtin_workflow(service)
    run = service.create_run(project_id=project_id, workflow_id=workflow_id)
    assert run.id is not None
    attempt = service.start_attempt(
        run_id=run.id,
        segment=segment,
        profile=profile,
        prompt_hash="abc123",
        context_summary={},
        validator_summary={},
        lease_duration_seconds=lease_duration_seconds,
    )
    assert attempt.id is not None
    return service, attempt


def _set_current_revision(
    db_path: Path,
    segment_id: int,
    revision_id: int,
) -> None:
    """Point a segment's current_revision_id at an existing revision."""
    db = create_database(db_path)
    try:
        db.execute(
            "UPDATE segments SET current_revision_id = ? WHERE id = ?",
            (revision_id, segment_id),
        )
        db.connection.commit()
    finally:
        db.close()


def _persist_segment(
    db_path: Path,
    segment: Segment,
) -> Segment:
    """Reload a segment from the database."""
    assert segment.id is not None
    repo = SegmentRepository.open(db_path)
    try:
        persisted = repo.get_by_id(segment.id)
    finally:
        repo.close()
    assert persisted is not None
    return persisted


class TestFinalizeFailure:
    """A normalized permanent/retryable error becomes an explainable attempt."""

    def test_permanent_failure_marks_segment_and_attempt_failed(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            failed = service.finalize_failure(
                attempt_id=attempt.id,
                error_type="authentication_error",
                error_message="invalid api key",
                retryable=False,
            )
        finally:
            service.close()

        assert failed.status == "failed"
        assert failed.retryable is False
        assert failed.error_type == "authentication_error"
        assert failed.error_message == "invalid api key"
        assert failed.finished_at is not None

        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "failed"
        assert persisted.lease_owner is None
        assert persisted.lease_expires_at is None
        assert persisted.current_revision_id is None

    def test_retryable_failure_sets_retryable_flag(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            failed = service.finalize_failure(
                attempt_id=attempt.id,
                error_type="timeout_error",
                error_message="request timed out",
                retryable=True,
            )
        finally:
            service.close()

        assert failed.status == "failed"
        assert failed.retryable is True
        assert failed.error_type == "timeout_error"

    def test_validation_error_is_permanent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            failed = service.finalize_failure(
                attempt_id=attempt.id,
                error_type="validation_error",
                error_message="invalid request parameters",
                retryable=False,
            )
        finally:
            service.close()

        assert failed.status == "failed"
        assert failed.retryable is False
        assert failed.error_type == "validation_error"

    def test_failure_preserves_existing_revision(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        revision_repo = TranslationRevisionRepository.open(db_path)
        try:
            existing = revision_repo.save(
                TranslationRevision.create(
                    segment_id=segment.id,
                    text="既有译文",
                    origin="user",
                ),
            )
        finally:
            revision_repo.close()
        assert segment.id is not None
        assert existing.id is not None
        _set_current_revision(db_path, segment.id, existing.id)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            failed = service.finalize_failure(
                attempt_id=attempt.id,
                error_type="server_error",
                error_message="provider down",
                retryable=True,
            )
        finally:
            service.close()

        assert failed.status == "failed"
        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "failed"
        assert persisted.current_revision_id == existing.id

        revision_repo = TranslationRevisionRepository.open(db_path)
        try:
            revisions = revision_repo.list_by_segment(segment.id)
        finally:
            revision_repo.close()
        assert [revision.id for revision in revisions] == [existing.id]

    def test_failure_is_reopenable(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            failed = service.finalize_failure(
                attempt_id=attempt.id,
                error_type="connection_error",
                error_message="network down",
                retryable=True,
            )
        finally:
            service.close()

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            assert failed.id is not None
            reopened = service.get_attempt(failed.id)
            assert reopened is not None
            assert reopened.status == "failed"
            assert reopened.error_type == "connection_error"
            assert reopened.finished_at is not None


class TestFinalizeFailureFencing:
    """Failure writes verify claim owner/version and a valid lease."""

    def _assert_unchanged_after_failure(
        self,
        db_path: Path,
        segment: Segment,
        attempt: SegmentAttempt,
    ) -> None:
        """After a rejected failure write, segment and attempt are unchanged."""
        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "processing"

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            assert attempt.id is not None
            persisted_attempt = service.get_attempt(attempt.id)
            assert persisted_attempt is not None
            assert persisted_attempt.status == "created"
            assert persisted_attempt.error_message is None
            assert persisted_attempt.finished_at is None

    def test_failure_rejects_expired_lease(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service = TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        )
        workflow, workflow_id = _builtin_workflow(service)
        run = service.create_run(project_id=project_id, workflow_id=workflow_id)
        assert run.id is not None
        attempt = service.start_attempt(
            run_id=run.id,
            segment=segment,
            profile=profile,
            prompt_hash="abc123",
            context_summary={},
            validator_summary={},
            lease_duration_seconds=1,
        )
        assert attempt.id is not None
        clock_times.append(fixed_now + timedelta(seconds=2))
        try:
            with pytest.raises(TranslationRunServiceError, match="lease has expired"):
                service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="timeout_error",
                    error_message="late failure",
                    retryable=True,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_failure_rejects_wrong_lease_owner(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            db = create_database(db_path)
            try:
                db.execute(
                    "UPDATE segments SET lease_owner = ? WHERE id = ?",
                    ("owner:intruder", segment.id),
                )
                db.connection.commit()
            finally:
                db.close()

            with pytest.raises(TranslationRunServiceError, match="lease owner"):
                service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="timeout_error",
                    error_message="boom",
                    retryable=True,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_failure_rejects_stale_version(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            db = create_database(db_path)
            try:
                db.execute(
                    "UPDATE segments SET version = version + 1 WHERE id = ?",
                    (segment.id,),
                )
                db.connection.commit()
            finally:
                db.close()

            with pytest.raises(TranslationRunServiceError, match="claim version mismatch"):
                service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="timeout_error",
                    error_message="boom",
                    retryable=True,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_failure_rejects_double_finalize(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.finalize_failure(
                attempt_id=attempt.id,
                error_type="timeout_error",
                error_message="first failure",
                retryable=True,
            )
            with pytest.raises(TranslationRunServiceError, match="status"):
                service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="server_error",
                    error_message="second failure",
                    retryable=False,
                )
        finally:
            service.close()

    def test_failure_rejects_non_running_run(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            run = service._run_repository.get_by_id(attempt.run_id)
            assert run is not None
            run.status = "cancelled"
            service._run_repository.save(run)

            with pytest.raises(TranslationRunServiceError, match="status"):
                service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="timeout_error",
                    error_message="boom",
                    retryable=True,
                )
        finally:
            service.close()

    def test_failure_write_is_atomic(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            db = create_database(db_path)
            try:
                db.execute(
                    "UPDATE segments SET version = version + 1 WHERE id = ?",
                    (segment.id,),
                )
                db.connection.commit()
            finally:
                db.close()

            with pytest.raises(TranslationRunServiceError, match="claim version mismatch"):
                service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="timeout_error",
                    error_message="boom",
                    retryable=True,
                )
        finally:
            service.close()

        # The failed write left no partial state: segment still processing,
        # attempt still created without error details.
        self._assert_unchanged_after_failure(db_path, segment, attempt)


class TestCancel:
    """Cancelling an in-flight attempt returns the segment to pending."""

    def test_cancel_returns_segment_to_pending(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            cancelled = service.cancel_attempt(
                attempt_id=attempt.id,
                reason="user cancelled run",
            )
        finally:
            service.close()

        assert cancelled.status == "cancelled"
        assert cancelled.error_type == "cancelled"
        assert cancelled.error_message == "user cancelled run"
        assert cancelled.finished_at is not None

        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "pending"
        assert persisted.lease_owner is None
        assert persisted.lease_expires_at is None

    def test_cancel_preserves_existing_revision_and_reason(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        revision_repo = TranslationRevisionRepository.open(db_path)
        try:
            existing = revision_repo.save(
                TranslationRevision.create(
                    segment_id=segment.id,
                    text="已确认译文",
                    origin="user",
                ),
            )
        finally:
            revision_repo.close()
        assert segment.id is not None
        assert existing.id is not None
        _set_current_revision(db_path, segment.id, existing.id)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.cancel_attempt(
                attempt_id=attempt.id,
                reason="user cancelled run",
            )
        finally:
            service.close()

        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "pending"
        assert persisted.current_revision_id == existing.id

        revision_repo = TranslationRevisionRepository.open(db_path)
        try:
            revisions = revision_repo.list_by_segment(segment.id)
        finally:
            revision_repo.close()
        assert [revision.id for revision in revisions] == [existing.id]

    def test_cancel_requires_valid_lease(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service = TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        )
        workflow, workflow_id = _builtin_workflow(service)
        run = service.create_run(project_id=project_id, workflow_id=workflow_id)
        assert run.id is not None
        attempt = service.start_attempt(
            run_id=run.id,
            segment=segment,
            profile=profile,
            prompt_hash="abc123",
            context_summary={},
            validator_summary={},
            lease_duration_seconds=1,
        )
        assert attempt.id is not None
        clock_times.append(fixed_now + timedelta(seconds=2))
        try:
            with pytest.raises(TranslationRunServiceError, match="lease has expired"):
                service.cancel_attempt(attempt_id=attempt.id, reason="stop")
        finally:
            service.close()

        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "processing"

    def test_cancel_rejects_wrong_lease_owner(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            db = create_database(db_path)
            try:
                db.execute(
                    "UPDATE segments SET lease_owner = ? WHERE id = ?",
                    ("owner:intruder", segment.id),
                )
                db.connection.commit()
            finally:
                db.close()

            with pytest.raises(TranslationRunServiceError, match="lease owner"):
                service.cancel_attempt(attempt_id=attempt.id, reason="stop")
        finally:
            service.close()

        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "processing"

    def test_cancel_rejects_non_created_attempt(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.finalize_success(
                attempt_id=attempt.id,
                translated_text="第一条",
                expected_current_revision_id=segment.current_revision_id,
                request_id="req-1",
                input_tokens=1,
                output_tokens=1,
                latency_ms=10,
            )
            with pytest.raises(TranslationRunServiceError, match="status"):
                service.cancel_attempt(attempt_id=attempt.id, reason="too late")
        finally:
            service.close()


class TestRecoverExpiredLeases:
    """Startup recovery recycles only expired processing leases."""

    def _claim_with_clock(
        self,
        db_path: Path,
        project_id: int,
        segment: Segment,
        profile: ModelProfile,
        clock_times: list[datetime],
        lease_duration_seconds: int = 1,
    ) -> tuple[TranslationRunService, SegmentAttempt]:
        """Claim under a mutable clock so the lease can be made to expire."""
        service = TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        )
        workflow, workflow_id = _builtin_workflow(service)
        run = service.create_run(project_id=project_id, workflow_id=workflow_id)
        assert run.id is not None
        attempt = service.start_attempt(
            run_id=run.id,
            segment=segment,
            profile=profile,
            prompt_hash="abc123",
            context_summary={},
            validator_summary={},
            lease_duration_seconds=lease_duration_seconds,
        )
        assert attempt.id is not None
        return service, attempt

    def test_recovers_expired_processing_to_pending(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service, attempt = self._claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        assert attempt.id is not None
        clock_times.append(fixed_now + timedelta(seconds=2))
        try:
            recovered = service.recover_expired_leases()
        finally:
            service.close()

        assert recovered == 1
        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "pending"
        assert persisted.lease_owner is None
        assert persisted.lease_expires_at is None

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            stale_attempt = service.get_attempt(attempt.id)
            assert stale_attempt is not None
            assert stale_attempt.status == "cancelled"
            assert stale_attempt.error_type == "lease_expired"
            assert stale_attempt.finished_at is not None

    def test_does_not_touch_active_lease(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service, attempt = self._claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=120,
        )
        assert attempt.id is not None
        try:
            recovered = service.recover_expired_leases()
        finally:
            service.close()

        assert recovered == 0
        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "processing"
        assert persisted.lease_owner == attempt.lease_owner
        assert persisted.lease_expires_at is not None

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            active_attempt = service.get_attempt(attempt.id)
            assert active_attempt is not None
            assert active_attempt.status == "created"

    def test_expired_locked_current_converges_without_replacement(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        revision_repo = TranslationRevisionRepository.open(db_path)
        try:
            locked = TranslationRevision.create(
                segment_id=segment.id,
                text="锁定译文",
                origin="user",
            )
            locked.is_locked = True
            locked = revision_repo.save(locked)
        finally:
            revision_repo.close()
        assert segment.id is not None
        assert locked.id is not None
        _set_current_revision(db_path, segment.id, locked.id)

        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]
        service, attempt = self._claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        assert attempt.id is not None
        clock_times.append(fixed_now + timedelta(seconds=2))
        try:
            recovered = service.recover_expired_leases()
        finally:
            service.close()

        assert recovered == 1
        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "completed"
        assert persisted.current_revision_id == locked.id
        assert persisted.lease_owner is None
        assert persisted.lease_expires_at is None

        with TranslationRunService(db_path, app_version=APP_VERSION) as reopened:
            stale_attempt = reopened.get_attempt(attempt.id)
            assert stale_attempt is not None
            assert stale_attempt.status == "cancelled"
            assert stale_attempt.error_type == "lease_expired"
            assert reopened.recover_expired_leases() == 0

    def test_recovery_is_reopenable(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service, attempt = self._claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        assert attempt.id is not None
        clock_times.append(fixed_now + timedelta(seconds=2))
        try:
            assert service.recover_expired_leases() == 1
        finally:
            service.close()

        # A second startup run sees the segment pending and can re-claim it.
        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        ) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            retried_segment = _persist_segment(db_path, segment)
            assert retried_segment.status == "pending"
            new_attempt = service.start_attempt(
                run_id=run.id,
                segment=retried_segment,
                profile=profile,
                prompt_hash="new-hash",
                context_summary={},
                validator_summary={},
            )
            assert new_attempt.id != attempt.id


class TestRetryBoundary:
    """Retry semantics: transport retry same attempt, business retry new attempt."""

    def test_retryable_failed_requeues_and_creates_new_attempt(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.finalize_failure(
                attempt_id=attempt.id,
                error_type="timeout_error",
                error_message="request timed out",
                retryable=True,
            )

            requeued = service.retry_failed(segment_id=segment.id)
            assert requeued.status == "pending"

            run = service._run_repository.get_by_id(attempt.run_id)
            assert run is not None
            assert run.id is not None
            new_attempt = service.start_attempt(
                run_id=run.id,
                segment=requeued,
                profile=profile,
                prompt_hash="hash-after-retry",
                context_summary={"retry": True},
                validator_summary={},
            )
        finally:
            service.close()

        assert new_attempt.id != attempt.id
        assert new_attempt.idempotency_key != attempt.idempotency_key
        assert new_attempt.prompt_hash == "hash-after-retry"
        assert new_attempt.status == "created"

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            old = service.get_attempt(attempt.id)
            assert old is not None
            assert old.status == "failed"
            assert old.retryable is True
            attempts = service.list_attempts_for_run(attempt.run_id)
            assert [a.id for a in attempts] == [attempt.id, new_attempt.id]

    def test_transport_retry_same_key_returns_same_attempt(
        self,
        tmp_path: Path,
    ) -> None:
        """Repeating the same logical request (same key) is one attempt."""
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        key = "transport-retry-key"

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            first = service.start_attempt(
                run_id=run.id,
                segment=segment,
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
                idempotency_key=key,
            )
            second = service.start_attempt(
                run_id=run.id,
                segment=segment,
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
                idempotency_key=key,
            )
            assert first.id == second.id
            assert len(service.list_attempts_for_run(run.id)) == 1

    def test_permanent_failure_cannot_be_requeued(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.finalize_failure(
                attempt_id=attempt.id,
                error_type="authentication_error",
                error_message="invalid api key",
                retryable=False,
            )
            with pytest.raises(TranslationRunServiceError, match="permanent"):
                service.retry_failed(segment_id=segment.id)
        finally:
            service.close()

        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "failed"

    def test_retry_rejects_non_failed_segment(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(TranslationRunServiceError, match="expected 'failed'"):
                service.retry_failed(segment_id=segment.id)

        # Also reject a completed segment.
        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.finalize_success(
                attempt_id=attempt.id,
                translated_text="第一条",
                expected_current_revision_id=segment.current_revision_id,
                request_id="req-1",
                input_tokens=1,
                output_tokens=1,
                latency_ms=10,
            )
            with pytest.raises(TranslationRunServiceError, match="expected 'failed'"):
                service.retry_failed(segment_id=segment.id)
        finally:
            service.close()

    def test_retry_rejects_when_last_attempt_not_retryable(
        self,
        tmp_path: Path,
    ) -> None:
        """Retryability is read from the last effective attempt, not timestamps."""
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.finalize_failure(
                attempt_id=attempt.id,
                error_type="server_error",
                error_message="provider down",
                retryable=True,
            )
            # Flip the persisted retryable flag to permanent: the guard must
            # read the real attempt state, not assume retryability.
            db = create_database(db_path)
            try:
                db.execute(
                    "UPDATE segment_attempts SET retryable = 0 WHERE id = ?",
                    (attempt.id,),
                )
                db.connection.commit()
            finally:
                db.close()

            with pytest.raises(TranslationRunServiceError, match="permanent"):
                service.retry_failed(segment_id=segment.id)
        finally:
            service.close()

        persisted = _persist_segment(db_path, segment)
        assert persisted.status == "failed"

    def test_cancelled_last_attempt_cannot_requeue(self, tmp_path: Path) -> None:
        """A cancelled attempt is not a retryable failure."""
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            service.cancel_attempt(attempt_id=attempt.id, reason="user stop")
            # Segment is pending again; retry_failed requires a failed segment.
            with pytest.raises(TranslationRunServiceError, match="expected 'failed'"):
                service.retry_failed(segment_id=segment.id)
        finally:
            service.close()
