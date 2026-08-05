"""Tests for P0-T07-M05: crash/recovery matrix and task gate.

This verification-only milestone exercises the P0-T07 recovery semantics
through composable crash injection: a crash at any point before, during or
after a finalize must never leave a fake ``completed``, an orphan current
revision, overwritten history or an unbounded retry. Repeated startup
recovery is idempotent, lease conflicts stay behind fencing, and locked
current revisions are never auto-recovered or auto-replaced.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType

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
from transrealm.infrastructure.database import DatabaseConnection, create_database
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)

APP_VERSION = "0.0.0-test"


class SimulatedCrashError(RuntimeError):
    """Raised by fault injection to model a process crash at a SQL point."""


class CrashInjector:
    """Composable crash injection over a shared ``DatabaseConnection``.

    While the injector is active, the first ``execute`` whose SQL text contains
    ``needle`` runs normally and then raises ``SimulatedCrashError`` —
    modelling a process dying right after that statement executed but before
    commit. SQLite discards the uncommitted work, so callers observe the same
    recovery semantics as a real crash at that point.
    """

    def __init__(self, connection: DatabaseConnection, needle: str) -> None:
        self._connection = connection
        self._needle = needle
        self._original: Callable[
            [str, tuple[object, ...] | None],
            sqlite3.Cursor,
        ] = connection.execute

    def __enter__(self) -> CrashInjector:
        def patched(
            sql: str,
            parameters: tuple[object, ...] | None = None,
        ) -> sqlite3.Cursor:
            result = self._original(sql, parameters)
            if self._needle in sql:
                raise SimulatedCrashError(
                    f"simulated crash after statement executed: {sql!r}",
                )
            return result

        self._connection.execute = patched  # type: ignore[method-assign]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._connection.execute = self._original  # type: ignore[assignment]
        return None


FINALIZE_CRASH_POINTS = [
    pytest.param("INSERT INTO translation_revisions", id="after-revision-insert"),
    pytest.param(
        "UPDATE segments SET status = ?, current_revision_id",
        id="after-segment-current-status-update",
    ),
    pytest.param(
        "UPDATE segment_attempts SET status = ?, request_id",
        id="after-attempt-audit-update",
    ),
]

CLAIM_CRASH_POINTS = [
    pytest.param("version = version + 1, lease_owner = ?", id="after-claim-segment-update"),
    pytest.param("INSERT INTO segment_attempts", id="after-attempt-insert"),
]

FAILURE_CRASH_POINTS = [
    pytest.param(
        "UPDATE segments SET status = ?, version = version + 1,",
        id="after-failure-segment-update",
    ),
    pytest.param(
        "UPDATE segment_attempts SET status = ?, retryable",
        id="after-failure-attempt-update",
    ),
]


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


def _import_txt(path: Path, project_id: int, content: str) -> list[Segment]:
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
                context_budget={
                    "total": 4096,
                    "reserved_output": 512,
                    "reserved_prompt": 512,
                },
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


def _claim_with_clock(
    path: Path,
    project_id: int,
    segment: Segment,
    profile: ModelProfile,
    clock_times: list[datetime],
    lease_duration_seconds: int = 1,
) -> tuple[TranslationRunService, SegmentAttempt]:
    """Claim under a mutable clock so the lease can be made to expire."""
    service = TranslationRunService(
        path,
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


def _persist_segment(db_path: Path, segment: Segment) -> Segment:
    """Reload a segment from the database."""
    assert segment.id is not None
    repo = SegmentRepository.open(db_path)
    try:
        persisted = repo.get_by_id(segment.id)
    finally:
        repo.close()
    assert persisted is not None
    return persisted


def _segment_state(db_path: Path, segment_id: int) -> tuple[str, int | None, str | None]:
    """Return (status, current_revision_id, lease_owner) for a segment."""
    db = create_database(db_path)
    try:
        row = db.execute(
            "SELECT status, current_revision_id, lease_owner "
            "FROM segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    return (
        str(row[0]),
        int(str(row[1])) if row[1] is not None else None,
        str(row[2]) if row[2] is not None else None,
    )


def _revision_ids(db_path: Path, segment_id: int) -> list[int]:
    """Return the persisted revision ids for a segment in creation order."""
    repo = TranslationRevisionRepository.open(db_path)
    try:
        revisions = repo.list_by_segment(segment_id)
    finally:
        repo.close()
    return [revision.id for revision in revisions if revision.id is not None]


def _attempt_rows(db_path: Path, segment_id: int) -> int:
    """Count persisted attempts for a segment."""
    db = create_database(db_path)
    try:
        row = db.execute(
            "SELECT COUNT(*) FROM segment_attempts WHERE segment_id = ?",
            (segment_id,),
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    return int(str(row[0]))


def _load_attempt(db_path: Path, attempt_id: int) -> SegmentAttempt:
    """Reopen the database and load an attempt."""
    with TranslationRunService(db_path, app_version=APP_VERSION) as service:
        attempt = service.get_attempt(attempt_id)
    assert attempt is not None
    return attempt


def _assert_no_orphan_current(db_path: Path, segment_id: int) -> None:
    """current_revision_id must be NULL or reference a revision of this segment."""
    db = create_database(db_path)
    try:
        row = db.execute(
            "SELECT s.current_revision_id, r.segment_id "
            "FROM segments s LEFT JOIN translation_revisions r "
            "ON r.id = s.current_revision_id WHERE s.id = ?",
            (segment_id,),
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    if row[0] is None:
        return
    assert row[1] is not None
    assert int(str(row[1])) == segment_id


def _assert_no_partial_writes(
    db_path: Path,
    segment: Segment,
    attempt: SegmentAttempt,
) -> None:
    """After a crash, the DB holds the recoverable pre-crash state.

    The segment is still ``processing`` under the claim, the attempt is still
    ``created`` without response audit, no revision row was half-written and
    the current revision is not orphaned.
    """
    assert segment.id is not None
    status, current, owner = _segment_state(db_path, segment.id)
    assert status == "processing"
    assert owner == attempt.lease_owner
    assert current == segment.current_revision_id
    assert _revision_ids(db_path, segment.id) == []
    _assert_no_orphan_current(db_path, segment.id)

    assert attempt.id is not None
    persisted = _load_attempt(db_path, attempt.id)
    assert persisted.status == "created"
    assert persisted.request_id is None
    assert persisted.finished_at is None


def _recover_and_reclaim(
    db_path: Path,
    project_id: int,
    segment: Segment,
    profile: ModelProfile,
    clock_times: list[datetime],
    stale_attempt_id: int,
) -> SegmentAttempt:
    """Advance the clock, reopen, recover the expired lease and re-claim.

    Asserts the stale attempt is marked ``cancelled`` with an explainable
    reason and returns the new attempt (a new idempotency key).
    """
    clock_times.append(clock_times[-1] + timedelta(seconds=2))
    with TranslationRunService(
        db_path,
        app_version=APP_VERSION,
        clock=lambda: clock_times[-1],
    ) as service:
        assert service.recover_expired_leases() == 1
        stale = service.get_attempt(stale_attempt_id)
        assert stale is not None
        assert stale.status == "cancelled"
        assert stale.error_type == "lease_expired"
        assert stale.finished_at is not None

        workflow, workflow_id = _builtin_workflow(service)
        run = service.create_run(project_id=project_id, workflow_id=workflow_id)
        assert run.id is not None
        pending = _persist_segment(db_path, segment)
        assert pending.status == "pending"
        new_attempt = service.start_attempt(
            run_id=run.id,
            segment=pending,
            profile=profile,
            prompt_hash="retry",
            context_summary={},
            validator_summary={},
        )
        assert new_attempt.id is not None
        assert new_attempt.id != stale_attempt_id
        return new_attempt


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


def _seed_locked_current(db_path: Path, segment: Segment) -> TranslationRevision:
    """Insert a locked user revision and make it the segment's current."""
    assert segment.id is not None
    repo = TranslationRevisionRepository.open(db_path)
    try:
        locked = TranslationRevision.create(
            segment_id=segment.id,
            text="人工锁定译文",
            origin="user",
        )
        locked.is_locked = True
        locked = repo.save(locked)
    finally:
        repo.close()
    assert locked.id is not None
    _set_current_revision(db_path, segment.id, locked.id)
    return locked


class TestClaimCrashMatrix:
    """A crash inside the claim transaction must roll the whole claim back."""

    @pytest.mark.parametrize("needle", CLAIM_CRASH_POINTS)
    def test_crash_inside_claim_rolls_back(self, tmp_path: Path, needle: str) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service = TranslationRunService(db_path, app_version=APP_VERSION)
        workflow, workflow_id = _builtin_workflow(service)
        run = service.create_run(project_id=project_id, workflow_id=workflow_id)
        assert run.id is not None
        try:
            with CrashInjector(service._db, needle):
                with pytest.raises(SimulatedCrashError, match="simulated crash"):
                    service.start_attempt(
                        run_id=run.id,
                        segment=segment,
                        profile=profile,
                        prompt_hash="abc123",
                        context_summary={},
                        validator_summary={},
                    )
        finally:
            service.close()

        # No processing segment and no attempt: the claim never happened.
        assert segment.id is not None
        status, current, owner = _segment_state(db_path, segment.id)
        assert status == "pending"
        assert current is None
        assert owner is None
        assert _attempt_rows(db_path, segment.id) == 0

        # The segment remains cleanly claimable by a fresh worker.
        with TranslationRunService(db_path, app_version=APP_VERSION) as reopened:
            workflow, workflow_id = _builtin_workflow(reopened)
            run = reopened.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            attempt = reopened.start_attempt(
                run_id=run.id,
                segment=segment,
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
            )
            assert attempt.status == "created"


class TestCrashBeforeExternalRequest:
    """A crash after claim but before the model request is safely recovered."""

    def test_crash_before_request_recovers_after_lease_expiry(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service, attempt = _claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        service.close()  # crash: no request was ever issued

        assert attempt.id is not None
        _recover_and_reclaim(db_path, project_id, segment, profile, clock_times, attempt.id)

    def test_restart_before_lease_expiry_leaves_processing(self, tmp_path: Path) -> None:
        """A crash restarted while the lease is still valid is not recycled and
        is not faked as completed."""
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service, attempt = _claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=60,
        )
        service.close()

        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        ) as reopened:
            assert reopened.recover_expired_leases() == 0
            assert attempt.id is not None
            persisted = reopened.get_attempt(attempt.id)
            assert persisted is not None
            assert persisted.status == "created"

        assert segment.id is not None
        status, current, owner = _segment_state(db_path, segment.id)
        assert status == "processing"
        assert owner == attempt.lease_owner
        assert _revision_ids(db_path, segment.id) == []
        _assert_no_orphan_current(db_path, segment.id)


class TestCrashAfterExternalRequest:
    """A response held only in memory before finalize is never persisted."""

    def test_crash_after_response_before_finalize_discards_inmemory_response(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service, attempt = _claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        # The model returned a response that lives only in worker memory.
        service.close()  # crash before finalize: the response is lost

        assert segment.id is not None
        assert _revision_ids(db_path, segment.id) == []
        status, current, _ = _segment_state(db_path, segment.id)
        assert status == "processing"
        assert current is None

        assert attempt.id is not None
        new_attempt = _recover_and_reclaim(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            attempt.id,
        )
        assert new_attempt.prompt_hash == "retry"


class TestFinalizeCrashMatrix:
    """A crash at any write inside finalize leaves only recoverable state."""

    @pytest.mark.parametrize("needle", FINALIZE_CRASH_POINTS)
    def test_crash_at_finalize_write_leaves_recoverable_state(
        self,
        tmp_path: Path,
        needle: str,
    ) -> None:
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
        try:
            with CrashInjector(service._db, needle):
                with pytest.raises(SimulatedCrashError, match="simulated crash"):
                    service.finalize_success(
                        attempt_id=attempt.id,
                        translated_text="第一条",
                        expected_current_revision_id=segment.current_revision_id,
                        request_id="req-1",
                        input_tokens=10,
                        output_tokens=2,
                        latency_ms=150,
                    )
        finally:
            service.close()

        # No fake completed, no orphan current, no half-written revision.
        _assert_no_partial_writes(db_path, segment, attempt)
        # Lease expiry makes the segment pending and claimable again.
        _recover_and_reclaim(db_path, project_id, segment, profile, clock_times, attempt.id)

    def test_power_loss_without_rollback_leaves_no_partial_state(
        self,
        tmp_path: Path,
    ) -> None:
        """A hard power loss discards uncommitted work even without a Python
        rollback path: the raw connection executes the finalize writes and is
        closed without commit."""
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        assert segment.id is not None
        service.close()

        # Execute the exact finalize writes on a raw connection, then close
        # without commit — the uncommitted transaction is discarded by SQLite.
        db = create_database(db_path)
        try:
            db.execute(
                "INSERT INTO translation_revisions "
                "(segment_id, text, origin, attempt_id, is_locked, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (segment.id, "第一条", "ai", attempt.id, 0, "2026-08-03T00:00:00+00:00"),
            )
            db.execute(
                "UPDATE segments SET status = 'completed', current_revision_id = ?, "
                "version = version + 1, lease_owner = NULL, lease_expires_at = NULL, "
                "updated_at = ? WHERE id = ?",
                (999, "2026-08-03T00:00:00+00:00", segment.id),
            )
            db.execute(
                "UPDATE segment_attempts SET status = 'succeeded', request_id = ?, "
                "finished_at = ? WHERE id = ?",
                ("req-power", "2026-08-03T00:00:00+00:00", attempt.id),
            )
        finally:
            db.close()

        _assert_no_partial_writes(db_path, segment, attempt)


class TestCrashWithExistingCurrentRevision:
    """A crash never orphans or overwrites an existing current revision."""

    def test_crash_keeps_existing_current_revision_valid(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        assert segment.id is not None

        repo = TranslationRevisionRepository.open(db_path)
        try:
            existing = repo.save(
                TranslationRevision.create(
                    segment_id=segment.id,
                    text="已有译文",
                    origin="user",
                ),
            )
        finally:
            repo.close()
        assert existing.id is not None
        _set_current_revision(db_path, segment.id, existing.id)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            with CrashInjector(service._db, "INSERT INTO translation_revisions"):
                with pytest.raises(SimulatedCrashError, match="simulated crash"):
                    service.finalize_success(
                        attempt_id=attempt.id,
                        translated_text="自动译文",
                        expected_current_revision_id=existing.id,
                        request_id="req-1",
                        input_tokens=1,
                        output_tokens=1,
                        latency_ms=10,
                    )
        finally:
            service.close()

        status, current, owner = _segment_state(db_path, segment.id)
        assert status == "processing"
        assert owner == attempt.lease_owner
        assert current == existing.id
        assert _revision_ids(db_path, segment.id) == [existing.id]
        _assert_no_orphan_current(db_path, segment.id)


class TestCrashAfterFinalizeCommitted:
    """A crash after a committed finalize is durable and redelivery is idempotent."""

    def test_crash_after_committed_finalize_redelivery_is_idempotent(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        expected_current = segment.current_revision_id

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        key = attempt.idempotency_key
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
        assert revision.id is not None

        # The worker crashed after commit but before acknowledging; the
        # transport redelivers the same logical request with the same key
        # against the same run.
        run_id = attempt.run_id
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            redelivered = service.start_attempt(
                run_id=run_id,
                segment=segment,  # the stale pending object the worker still holds
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
                idempotency_key=key,
            )
            assert redelivered.id == attempt.id
            assert redelivered.status == "succeeded"
            # No second attempt, no second revision: the model is not re-called.
            assert len(service.list_attempts_for_run(run_id)) == 1
            assert segment.id is not None
            assert _revision_ids(db_path, segment.id) == [revision.id]

        status, current, owner = _segment_state(db_path, segment.id)
        assert status == "completed"
        assert current == revision.id
        assert owner is None

    def test_committed_finalize_is_durable_across_restart(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        expected_current = segment.current_revision_id

        service, attempt = _claim(db_path, project_id, segment, profile)
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
        assert revision.id is not None

        with TranslationRunService(db_path, app_version=APP_VERSION) as reopened:
            reopened_attempt = reopened.get_attempt(attempt.id)
            assert reopened_attempt is not None
            assert reopened_attempt.status == "succeeded"
            assert reopened_attempt.request_id == "req-1"
            assert reopened.get_revision(revision.id) is not None

        assert segment.id is not None
        status, current, _ = _segment_state(db_path, segment.id)
        assert status == "completed"
        assert current == revision.id
        assert _revision_ids(db_path, segment.id) == [revision.id]


class TestRepeatedStartupRecovery:
    """Startup recovery is idempotent across repeated restarts."""

    def test_recovery_is_idempotent_across_restarts(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service, attempt = _claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        service.close()

        clock_times.append(fixed_now + timedelta(seconds=2))
        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        ) as service:
            assert service.recover_expired_leases() == 1
            # A second recover call in the same startup is a no-op.
            assert service.recover_expired_leases() == 0

            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            pending = _persist_segment(db_path, segment)
            attempt2 = service.start_attempt(
                run_id=run.id,
                segment=pending,
                profile=profile,
                prompt_hash="retry",
                context_summary={},
                validator_summary={},
            )
            assert attempt2.id != attempt.id
            assert attempt2.id is not None
            finalized, revision = service.finalize_success(
                attempt_id=attempt2.id,
                translated_text="第一条",
                expected_current_revision_id=pending.current_revision_id,
                request_id="req-2",
                input_tokens=1,
                output_tokens=1,
                latency_ms=10,
            )
            assert finalized.status == "succeeded"
            # A completed segment is never recovered by a later startup.
            assert service.recover_expired_leases() == 0

        assert revision.id is not None
        assert segment.id is not None
        status, current, _ = _segment_state(db_path, segment.id)
        assert status == "completed"
        assert current == revision.id


class TestLeaseConflictAcrossCrash:
    """A crashed owner's lease fences a second owner until it expires."""

    def test_second_owner_blocked_until_expiry_then_completes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]

        service_a, attempt_a = _claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        service_a.close()  # A crashes
        assert attempt_a.id is not None

        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        ) as service_b:
            workflow, workflow_id = _builtin_workflow(service_b)
            run = service_b.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None

            # B is fenced out while A's lease is still valid: the segment is
            # processing under A's claim, so the claim is rejected.
            with pytest.raises(TranslationRunServiceError, match="expected 'pending'"):
                service_b.start_attempt(
                    run_id=run.id,
                    segment=segment,
                    profile=profile,
                    prompt_hash="b",
                    context_summary={},
                    validator_summary={},
                )

            # A's lease expires; B recovers and claims with a new generation.
            clock_times.append(fixed_now + timedelta(seconds=2))
            assert service_b.recover_expired_leases() == 1
            pending = _persist_segment(db_path, segment)
            assert pending.status == "pending"
            attempt_b = service_b.start_attempt(
                run_id=run.id,
                segment=pending,
                profile=profile,
                prompt_hash="b2",
                context_summary={},
                validator_summary={},
            )
            assert attempt_b.id != attempt_a.id
            assert attempt_b.id is not None
            finalized_b, revision_b = service_b.finalize_success(
                attempt_id=attempt_b.id,
                translated_text="第一条",
                expected_current_revision_id=pending.current_revision_id,
                request_id="req-b",
                input_tokens=1,
                output_tokens=1,
                latency_ms=10,
            )
            assert finalized_b.status == "succeeded"

            # A wakes up and tries to finalize its stale attempt: fenced out.
            with pytest.raises(TranslationRunServiceError, match="status"):
                service_b.finalize_success(
                    attempt_id=attempt_a.id,
                    translated_text="迟到译文",
                    expected_current_revision_id=segment.current_revision_id,
                    request_id="req-a",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )

        # Exactly one completion and one revision: no duplicate, no overwrite.
        assert revision_b.id is not None
        assert segment.id is not None
        assert _revision_ids(db_path, segment.id) == [revision_b.id]
        status, current, owner = _segment_state(db_path, segment.id)
        assert status == "completed"
        assert current == revision_b.id
        assert owner is None


class TestLockRegressionAcrossCrash:
    """Locked current revisions survive crashes and are never auto-handled."""

    def test_crash_with_locked_current_not_recovered_or_replaced(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        locked = _seed_locked_current(db_path, segment)

        fixed_now = datetime.now(UTC)
        clock_times = [fixed_now]
        service, attempt = _claim_with_clock(
            db_path,
            project_id,
            segment,
            profile,
            clock_times,
            lease_duration_seconds=1,
        )
        assert attempt.id is not None
        service.close()  # crash before the request

        clock_times.append(fixed_now + timedelta(seconds=2))
        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: clock_times[-1],
        ) as reopened:
            # Recovery converges the expired lease without replacing the locked revision.
            assert reopened.recover_expired_leases() == 1
            # A stale worker can no longer finalize after its attempt is cancelled.
            with pytest.raises(TranslationRunServiceError, match="status is 'cancelled'"):
                reopened.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="自动译文",
                    expected_current_revision_id=locked.id,
                    request_id="req",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=10,
                )

        # The locked current revision is preserved; no auto replacement.
        assert segment.id is not None
        status, current, owner = _segment_state(db_path, segment.id)
        assert status == "completed"
        assert owner is None
        assert current == locked.id
        assert _revision_ids(db_path, segment.id) == [locked.id]
        _assert_no_orphan_current(db_path, segment.id)


class TestFailureCrashMatrix:
    """A crash inside a failure write rolls back to the recoverable state."""

    @pytest.mark.parametrize("needle", FAILURE_CRASH_POINTS)
    def test_crash_inside_failure_write_rolls_back(self, tmp_path: Path, needle: str) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        service, attempt = _claim(db_path, project_id, segment, profile)
        assert attempt.id is not None
        try:
            with CrashInjector(service._db, needle):
                with pytest.raises(SimulatedCrashError, match="simulated crash"):
                    service.finalize_failure(
                        attempt_id=attempt.id,
                        error_type="timeout_error",
                        error_message="boom",
                        retryable=True,
                    )
        finally:
            service.close()

        _assert_no_partial_writes(db_path, segment, attempt)
