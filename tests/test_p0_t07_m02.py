"""Tests for P0-T07-M02: atomic claim, idempotency and lease expiry."""

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
from transrealm.domain.translation_workflow import WorkflowDefinition
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository

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


def _set_segment_lease(
    db_path: Path,
    segment_id: int,
    lease_owner: str,
    lease_expires_at: datetime,
    updated_at: datetime,
) -> None:
    """Set the lease fields of a segment directly for test setup."""
    db = create_database(db_path)
    try:
        db.execute(
            "UPDATE segments SET lease_owner = ?, lease_expires_at = ?, updated_at = ? "
            "WHERE id = ?",
            (lease_owner, lease_expires_at.isoformat(), updated_at.isoformat(), segment_id),
        )
        db.connection.commit()
    finally:
        db.close()


class TestAtomicClaim:
    """Segment claim is atomic and respects lease/version boundaries."""

    def test_claim_succeeds_only_for_pending_with_empty_lease(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
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
            )
            assert attempt.id is not None

        assert attempt.status == "created"
        assert attempt.claim_version == segment.version + 1

    def test_claim_rejects_non_expired_lease(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)

        # Pre-seed the segment with a pending status and a non-expired lease.
        _set_segment_lease(
            db_path,
            segment.id,
            "owner:existing",
            fixed_now + timedelta(seconds=120),
            fixed_now,
        )

        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: fixed_now,
        ) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            with pytest.raises(TranslationRunServiceError, match="lease"):
                service.start_attempt(
                    run_id=run.id,
                    segment=segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )

    def test_claim_reclaims_expired_lease(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)

        # Pre-seed the segment with a pending status and an expired lease.
        _set_segment_lease(
            db_path,
            segment.id,
            "owner:existing",
            fixed_now - timedelta(seconds=1),
            fixed_now,
        )

        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: fixed_now,
        ) as service:
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
                lease_duration_seconds=120,
            )
            assert attempt.id is not None

        repo = SegmentRepository.open(db_path)
        try:
            persisted = repo.find_segment_by_stable_key(
                segment.source_document_id,
                segment.stable_key,
            )
            assert persisted is not None
            assert persisted.status == "processing"
            assert persisted.lease_owner == attempt.lease_owner
            assert persisted.lease_expires_at is not None
            assert persisted.lease_expires_at > fixed_now + timedelta(seconds=119)
        finally:
            repo.close()

    def test_claim_rejects_stale_version(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            # Simulate a concurrent claim that advanced the version in DB.
            db = create_database(db_path)
            try:
                db.execute(
                    "UPDATE segments SET version = version + 1 WHERE id = ?",
                    (segment.id,),
                )
                db.connection.commit()
            finally:
                db.close()

            with pytest.raises(TranslationRunServiceError, match="stale version"):
                service.start_attempt(
                    run_id=run.id,
                    segment=segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )

    def test_claim_rejects_completed_segment(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        segment.status = "completed"

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            with pytest.raises(TranslationRunServiceError, match="pending"):
                service.start_attempt(
                    run_id=run.id,
                    segment=segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )


class TestIdempotency:
    """Duplicate idempotency keys return the existing attempt."""

    def test_duplicate_idempotency_key_returns_existing_attempt(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        key = "my-idempotency-key"

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
                prompt_hash="different",
                context_summary={"different": True},
                validator_summary={"different": True},
                idempotency_key=key,
            )

            assert first.id == second.id
            assert second.id is not None
            assert second.prompt_hash == "abc123"
            # Segment should not have been claimed twice: only one attempt exists.
            assert service.list_attempts_for_run(run.id) == [second]

        # After closing, the result should be reopenable.
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            reopened = service.get_attempt(second.id)
            assert reopened is not None
            assert reopened.idempotency_key == key

    def test_duplicate_key_for_different_run_is_rejected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "line one\nline two\n")
        segment_a = segments[0]
        segment_b = segments[1]
        profile = _create_profile(db_path)
        key = "shared-key"

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            service.start_attempt(
                run_id=run.id,
                segment=segment_a,
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
                idempotency_key=key,
            )
            with pytest.raises(TranslationRunServiceError, match="different run/segment"):
                service.start_attempt(
                    run_id=run.id,
                    segment=segment_b,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                    idempotency_key=key,
                )


class TestReopenAndRecovery:
    """Lease expiry and database reopen boundaries."""

    def test_expired_lease_can_be_claimed_after_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)

        # Pre-seed the segment with a pending status and an expired lease.
        _set_segment_lease(
            db_path,
            segment.id,
            "owner:existing",
            fixed_now - timedelta(seconds=1),
            fixed_now,
        )

        # Reopen after lease expiry and reclaim.
        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: fixed_now,
        ) as service:
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
                lease_duration_seconds=60,
            )
            assert attempt.id is not None

    def test_active_lease_survives_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)

        # Pre-seed the segment with a pending status and a non-expired lease.
        _set_segment_lease(
            db_path,
            segment.id,
            "owner:existing",
            fixed_now + timedelta(seconds=120),
            fixed_now,
        )

        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: fixed_now + timedelta(seconds=60),
        ) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            with pytest.raises(TranslationRunServiceError, match="lease"):
                service.start_attempt(
                    run_id=run.id,
                    segment=segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )
