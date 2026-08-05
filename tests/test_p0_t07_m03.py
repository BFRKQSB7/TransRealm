"""Tests for P0-T07-M03: successful finalize transaction."""

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


class TestFinalizeSuccess:
    """Successful finalize updates segment, attempt and revision atomically."""

    def test_finalize_success_creates_revision_and_completes_segment(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        expected_current = segment.current_revision_id

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        assert attempt.id is not None
        try:
            finalized, revision = service.finalize_success(
                attempt_id=attempt.id,
                translated_text="第一条",
                expected_current_revision_id=expected_current,
                request_id="req-1",
                input_tokens=10,
                output_tokens=2,
                latency_ms=150,
            )
        finally:
            service.close()

        assert finalized.status == "succeeded"
        assert finalized.request_id == "req-1"
        assert finalized.input_tokens == 10
        assert finalized.output_tokens == 2
        assert finalized.latency_ms == 150
        assert finalized.finished_at is not None

        assert revision.segment_id == segment.id
        assert revision.text == "第一条"
        assert revision.origin == "ai"
        assert revision.attempt_id == attempt.id
        assert revision.is_locked is False

        repo = SegmentRepository.open(db_path)
        try:
            persisted = repo.find_segment_by_stable_key(
                segment.source_document_id,
                segment.stable_key,
            )
            assert persisted is not None
            assert persisted.status == "completed"
            assert persisted.current_revision_id == revision.id
            assert persisted.lease_owner is None
            assert persisted.lease_expires_at is None
        finally:
            repo.close()

    def test_finalize_success_is_reopenable(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        expected_current = segment.current_revision_id

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        assert attempt.id is not None
        try:
            finalized, revision = service.finalize_success(
                attempt_id=attempt.id,
                translated_text="第一条",
                expected_current_revision_id=expected_current,
                request_id="req-1",
                input_tokens=1,
                output_tokens=1,
                latency_ms=10,
            )
        finally:
            service.close()

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            assert finalized.id is not None
            reopened_attempt = service.get_attempt(finalized.id)
            assert reopened_attempt is not None
            assert reopened_attempt.status == "succeeded"
            assert revision.id is not None
            reopened_revision = service.get_revision(revision.id)
            assert reopened_revision is not None
            assert reopened_revision.text == "第一条"


class TestFinalizeFencing:
    """Finalize respects lease, version, current revision and attempt state."""

    def test_finalize_rejects_expired_lease(self, tmp_path: Path) -> None:
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
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第一条",
                    expected_current_revision_id=segment.current_revision_id,
                    request_id="req-1",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_finalize_rejects_wrong_lease_owner(self, tmp_path: Path) -> None:
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
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第一条",
                    expected_current_revision_id=segment.current_revision_id,
                    request_id="req-1",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_finalize_rejects_stale_version(self, tmp_path: Path) -> None:
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
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第一条",
                    expected_current_revision_id=segment.current_revision_id,
                    request_id="req-1",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_finalize_rejects_locked_current_revision(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        # Seed a locked user revision as the current revision before claiming.
        revision_repo = TranslationRevisionRepository.open(db_path)
        try:
            locked = TranslationRevision.create(
                segment_id=segment.id,
                text="人工译文",
                origin="user",
            )
            locked.is_locked = True
            locked = revision_repo.save(locked)
        finally:
            revision_repo.close()

        db = create_database(db_path)
        try:
            db.execute(
                "UPDATE segments SET current_revision_id = ? WHERE id = ?",
                (locked.id, segment.id),
            )
            db.connection.commit()
        finally:
            db.close()

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            with pytest.raises(TranslationRunServiceError, match="current revision is locked"):
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第一条",
                    expected_current_revision_id=locked.id,
                    request_id="req-1",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)
        # The locked user revision remains current.
        repo = SegmentRepository.open(db_path)
        try:
            persisted = repo.find_segment_by_stable_key(
                segment.source_document_id,
                segment.stable_key,
            )
            assert persisted is not None
            assert persisted.current_revision_id == locked.id
        finally:
            repo.close()

    def test_finalize_rejects_changed_current_revision(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        expected_current = segment.current_revision_id

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            # Another process sets a new current revision after the claim.
            revision_repo = TranslationRevisionRepository.open(db_path)
            try:
                other = revision_repo.save(
                    TranslationRevision.create(
                        segment_id=segment.id,
                        text="其他",
                        origin="user",
                    ),
                )
            finally:
                revision_repo.close()

            db = create_database(db_path)
            try:
                db.execute(
                    "UPDATE segments SET current_revision_id = ? WHERE id = ?",
                    (other.id, segment.id),
                )
                db.connection.commit()
            finally:
                db.close()

            with pytest.raises(TranslationRunServiceError, match="current revision has changed"):
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第一条",
                    expected_current_revision_id=expected_current,
                    request_id="req-1",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_finalize_rejects_non_running_run(self, tmp_path: Path) -> None:
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
            run.status = "completed"
            service._run_repository.save(run)

            with pytest.raises(TranslationRunServiceError, match="status"):
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第一条",
                    expected_current_revision_id=segment.current_revision_id,
                    request_id="req-1",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        self._assert_unchanged_after_failure(db_path, segment, attempt)

    def test_finalize_rejects_double_finalize(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        expected_current = segment.current_revision_id

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        assert attempt.id is not None
        try:
            service.finalize_success(
                attempt_id=attempt.id,
                translated_text="第一条",
                expected_current_revision_id=expected_current,
                request_id="req-1",
                input_tokens=1,
                output_tokens=1,
                latency_ms=10,
            )
            with pytest.raises(TranslationRunServiceError, match="status"):
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第二条",
                    expected_current_revision_id=expected_current,
                    request_id="req-2",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        repo = SegmentRepository.open(db_path)
        try:
            persisted = repo.find_segment_by_stable_key(
                segment.source_document_id,
                segment.stable_key,
            )
            assert persisted is not None
            assert persisted.status == "completed"
            assert persisted.current_revision_id is not None
        finally:
            repo.close()

    def _assert_unchanged_after_failure(
        self,
        db_path: Path,
        segment: Segment,
        attempt: SegmentAttempt,
    ) -> None:
        """After a failed finalize, segment remains processing and attempt created."""
        repo = SegmentRepository.open(db_path)
        try:
            persisted = repo.find_segment_by_stable_key(
                segment.source_document_id,
                segment.stable_key,
            )
            assert persisted is not None
            assert persisted.status == "processing"
        finally:
            repo.close()

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            assert attempt.id is not None
            persisted_attempt = service.get_attempt(attempt.id)
            assert persisted_attempt is not None
            assert persisted_attempt.status == "created"
            assert persisted_attempt.request_id is None


class TestFinalizeAtomicity:
    """Failed finalize leaves no partial writes."""

    def test_failed_finalize_does_not_create_revision(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            with pytest.raises(TranslationRunServiceError, match="current revision has changed"):
                service.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="第一条",
                    expected_current_revision_id=9999,
                    request_id="req-1",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )
        finally:
            service.close()

        revision_repo = TranslationRevisionRepository.open(db_path)
        try:
            revisions = revision_repo.list_by_segment(segment.id)
        finally:
            revision_repo.close()
        assert revisions == []

        db = create_database(db_path)
        try:
            row = db.execute(
                "SELECT status, current_revision_id FROM segments WHERE id = ?",
                (segment.id,),
            ).fetchone()
            assert row is not None
            assert row[0] == "processing"
            assert row[1] is None
        finally:
            db.close()
