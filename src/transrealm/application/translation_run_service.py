"""Application service for translation run and attempt lifecycle."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from transrealm.domain.model_profile import ModelProfile
from transrealm.domain.segment import Segment
from transrealm.domain.segment_attempt import SegmentAttempt, SegmentAttemptError
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.domain.translation_run import TranslationRun
from transrealm.domain.translation_workflow import (
    WorkflowDefinition,
    WorkflowDefinitionError,
    canonical_definition_json,
)
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.project_repository import ProjectRepository
from transrealm.infrastructure.repositories.segment_attempt_repository import (
    SegmentAttemptRepository,
)
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)
from transrealm.infrastructure.repositories.translation_run_repository import (
    TranslationRunRepository,
)
from transrealm.infrastructure.repositories.translation_workflow_repository import (
    WorkflowDefinitionRepository,
)

BUILTIN_GENERAL_TRANSLATION_WORKFLOW = WorkflowDefinition.create_builtin(
    name="general_translation",
    version="1.0.0",
    definition={
        "steps": [
            {
                "step": "compose_context",
                "description": "Gather current segment and minimal context.",
            },
            {
                "step": "render_prompt",
                "description": "Render profile template and output contract.",
            },
            {
                "step": "call_model",
                "description": "Call the configured model adapter.",
            },
            {
                "step": "parse_output",
                "description": "Parse and validate model output.",
            },
            {
                "step": "finalize_revision",
                "description": "Store translation revision and update segment.",
            },
        ],
    },
)


class TranslationRunServiceError(RuntimeError):
    """Invalid translation run or attempt operation."""


class TranslationRunService:
    """Application service for creating translation runs and attempts.

    The service owns a single database connection and runs migrations on open.
    It seeds the built-in workflow definition idempotently and verifies its hash
    on every open so that tampering is detected.
    """

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(
        self,
        db_path: Path,
        *,
        app_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._db = create_database(db_path)
        self._workflow_repository = WorkflowDefinitionRepository(self._db)
        self._run_repository = TranslationRunRepository(self._db)
        self._attempt_repository = SegmentAttemptRepository(self._db)
        self._revision_repository = TranslationRevisionRepository(self._db)
        self._project_repository = ProjectRepository(self._db)
        self._segment_repository = SegmentRepository(self._db)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._run_migrations()
        self._seed_builtin_workflow()

    def _run_migrations(self) -> None:
        from transrealm.infrastructure.migrations.discovery import discover_migrations

        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

    def _seed_builtin_workflow(self) -> None:
        """Ensure the built-in workflow is present and unchanged.

        If the built-in workflow is missing, insert it. If it exists but its hash
        does not match the expected definition, the database has been tampered with
        and the service refuses to start.
        """
        existing = self._workflow_repository.get_by_name_and_version(
            BUILTIN_GENERAL_TRANSLATION_WORKFLOW.name,
            BUILTIN_GENERAL_TRANSLATION_WORKFLOW.version,
        )
        if existing is None:
            self._workflow_repository.save(BUILTIN_GENERAL_TRANSLATION_WORKFLOW)
            return

        expected_hash = BUILTIN_GENERAL_TRANSLATION_WORKFLOW.definition_hash
        if existing.definition_hash != expected_hash:
            raise WorkflowDefinitionError(
                "Built-in workflow definition has been modified: "
                f"expected hash {expected_hash}, got {existing.definition_hash}",
            )
        if not existing.is_read_only:
            raise WorkflowDefinitionError(
                f"Built-in workflow {existing.name} is not marked read-only.",
            )

    def create_run(self, *, project_id: int, workflow_id: int) -> TranslationRun:
        """Create a new translation run referencing a workflow version snapshot."""
        project = self._project_repository.get_by_id(project_id)
        if project is None:
            raise TranslationRunServiceError(
                f"Project with id {project_id} does not exist.",
            )

        workflow = self._workflow_repository.get_by_id(workflow_id)
        if workflow is None:
            raise TranslationRunServiceError(
                f"WorkflowDefinition with id {workflow_id} does not exist.",
            )

        assert project.id is not None
        assert workflow.id is not None
        run = TranslationRun.create(
            project_id=project.id,
            workflow_id=workflow.id,
            workflow_version=workflow.version,
            workflow_definition_hash=workflow.definition_hash,
            workflow_definition_snapshot=canonical_definition_json(workflow.definition_json),
        )
        return self._run_repository.save(run)

    def start_attempt(
        self,
        *,
        run_id: int,
        segment: Segment,
        profile: ModelProfile,
        prompt_hash: str,
        context_summary: dict[str, object],
        validator_summary: dict[str, object],
        idempotency_key: str | None = None,
        lease_duration_seconds: int = 60,
    ) -> SegmentAttempt:
        """Claim a pending segment and persist a pre-request attempt.

        If ``idempotency_key`` is provided and an attempt with that key already
        exists, the existing attempt is returned without claiming the segment
        again. Otherwise a new key is generated and the segment is atomically
        claimed when it is pending with a current version and an empty or expired
        lease.
        """
        run = self._run_repository.get_by_id(run_id)
        if run is None:
            raise TranslationRunServiceError(f"TranslationRun with id {run_id} does not exist.")

        if run.status != "running":
            raise TranslationRunServiceError(
                f"Cannot start attempt: run {run_id} status is {run.status!r}.",
            )

        assert run.id is not None
        assert segment.id is not None
        assert profile.id is not None

        existing = self._segment_repository.find_segment_by_stable_key(
            segment.source_document_id,
            segment.stable_key,
        )
        if existing is None or existing.id != segment.id:
            raise TranslationRunServiceError(
                "Segment id does not match the persisted segment for its stable key.",
            )
        source_document = self._segment_repository.get_source_document_by_id(
            segment.source_document_id,
        )
        if source_document is None or source_document.project_id != run.project_id:
            raise TranslationRunServiceError(
                f"Segment {segment.id} does not belong to run {run_id}'s project.",
            )

        if segment.status != "pending":
            raise TranslationRunServiceError(
                f"Segment {segment.id} is not pending (status={segment.status!r}).",
            )

        lease_owner = self._generate_lease_owner()
        now = self._clock()
        lease_expires_at = now + timedelta(seconds=lease_duration_seconds)
        key = idempotency_key or self._generate_idempotency_key(run, segment)

        profile_snapshot: dict[str, object] = {
            "profile_id": profile.id,
            "name": profile.name,
            "model_id": profile.model_id,
            "template_version": profile.template_version,
            "output_protocol": profile.output_protocol,
            "capability_snapshot": profile.capability_snapshot,
        }

        try:
            return self._attempt_repository.create_after_claim(
                run_id=run_id,
                segment_id=segment.id,
                expected_version=segment.version,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                idempotency_key=key,
                model_profile_id=profile.id,
                profile_snapshot=profile_snapshot,
                prompt_hash=prompt_hash,
                context_summary=context_summary,
                validator_summary=validator_summary,
                now=now,
            )
        except SegmentAttemptError as exc:
            raise TranslationRunServiceError(str(exc)) from exc

    def _generate_lease_owner(self) -> str:
        """Generate a unique lease owner token."""
        return f"owner:{uuid.uuid4().hex}"

    def _generate_idempotency_key(self, run: TranslationRun, segment: Segment) -> str:
        """Generate a deterministic idempotency key for a run/segment pair."""
        return f"run:{run.id}:segment:{segment.id}:{secrets.token_hex(8)}"

    def finalize_success(
        self,
        *,
        attempt_id: int,
        translated_text: str,
        expected_current_revision_id: int | None,
        request_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> tuple[SegmentAttempt, TranslationRevision]:
        """Finalize a successful model call for an attempt.

        Atomically saves response audit, appends an AI revision, updates the
        segment's current revision and marks both segment and attempt as
        completed.  The caller must provide the ``current_revision_id`` value
        observed at claim time; if it has changed or points to a locked
        revision, the finalize is rejected.
        """
        attempt = self._attempt_repository.get_by_id(attempt_id)
        if attempt is None:
            raise TranslationRunServiceError(
                f"SegmentAttempt with id {attempt_id} does not exist.",
            )

        run = self._run_repository.get_by_id(attempt.run_id)
        if run is None:
            raise TranslationRunServiceError(
                f"TranslationRun with id {attempt.run_id} does not exist.",
            )
        if run.status != "running":
            raise TranslationRunServiceError(
                f"Cannot finalize attempt: run {run.id} status is {run.status!r}.",
            )

        now = self._clock()
        try:
            return self._attempt_repository.finalize_success(
                attempt_id=attempt_id,
                translated_text=translated_text,
                expected_current_revision_id=expected_current_revision_id,
                request_id=request_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                now=now,
            )
        except SegmentAttemptError as exc:
            raise TranslationRunServiceError(str(exc)) from exc

    def finalize_failure(
        self,
        *,
        attempt_id: int,
        error_type: str,
        error_message: str,
        retryable: bool,
    ) -> SegmentAttempt:
        """Record a failed model call for an attempt.

        The caller passes a normalized error (category, safe message and
        retryable flag, e.g. derived from an ``AdapterError``). The segment
        becomes ``failed`` and its lease is released; only a retryable failure
        can later be requeued.
        """
        attempt = self._attempt_repository.get_by_id(attempt_id)
        if attempt is None:
            raise TranslationRunServiceError(
                f"SegmentAttempt with id {attempt_id} does not exist.",
            )
        run = self._run_repository.get_by_id(attempt.run_id)
        if run is None:
            raise TranslationRunServiceError(
                f"TranslationRun with id {attempt.run_id} does not exist.",
            )
        if run.status != "running":
            raise TranslationRunServiceError(
                f"Cannot finalize failure: run {run.id} status is {run.status!r}.",
            )
        now = self._clock()
        try:
            return self._attempt_repository.finalize_failure(
                attempt_id=attempt_id,
                error_type=error_type,
                error_message=error_message,
                retryable=retryable,
                now=now,
            )
        except SegmentAttemptError as exc:
            raise TranslationRunServiceError(str(exc)) from exc

    def cancel_attempt(self, *, attempt_id: int, reason: str) -> SegmentAttempt:
        """Cancel an in-flight attempt and release its segment back to pending.

        The attempt must still hold a valid lease; the segment returns to
        ``pending`` so it can be claimed again. Existing revisions and the
        current revision are preserved.
        """
        attempt = self._attempt_repository.get_by_id(attempt_id)
        if attempt is None:
            raise TranslationRunServiceError(
                f"SegmentAttempt with id {attempt_id} does not exist.",
            )
        now = self._clock()
        try:
            return self._attempt_repository.cancel(
                attempt_id=attempt_id,
                reason=reason,
                now=now,
            )
        except SegmentAttemptError as exc:
            raise TranslationRunServiceError(str(exc)) from exc

    def finish_run(self, *, run_id: int, status: str) -> TranslationRun:
        """Persist a terminal run status after its worker has stopped."""
        if status not in {"completed", "failed", "cancelled"}:
            raise TranslationRunServiceError(f"Invalid terminal run status: {status!r}.")
        run = self._run_repository.get_by_id(run_id)
        if run is None:
            raise TranslationRunServiceError(f"TranslationRun with id {run_id} does not exist.")
        if run.status != "running":
            raise TranslationRunServiceError(
                f"Cannot finish run {run_id}: status is {run.status!r}.",
            )
        run.status = status
        run.finished_at = self._clock()
        return self._run_repository.save(run)

    def recover_expired_leases(self) -> int:
        """Converge processing segments whose leases have expired at startup."""
        now = self._clock()
        return self._attempt_repository.recover_expired_leases(now=now)

    def retry_failed(self, *, segment_id: int) -> Segment:
        """Re-queue a failed segment whose last effective attempt is retryable.

        The segment must be ``failed`` and its last effective attempt (the one
        whose claim version matches the failed generation) must have failed
        with ``retryable=True``. Returns the segment in ``pending`` state, ready
        to be claimed again as a new attempt with a new idempotency key.
        """
        segment = self._segment_repository.get_by_id(segment_id)
        if segment is None:
            raise TranslationRunServiceError(
                f"Segment with id {segment_id} does not exist.",
            )
        if segment.status != "failed":
            raise TranslationRunServiceError(
                f"Cannot retry segment {segment_id}: status is {segment.status!r}, "
                "expected 'failed'.",
            )
        assert segment.version is not None
        last_attempt = self._attempt_repository.get_by_segment_and_claim_version(
            segment_id,
            segment.version - 1,
        )
        if last_attempt is None:
            raise TranslationRunServiceError(
                f"Cannot retry segment {segment_id}: no attempt matches the "
                "current failed generation.",
            )
        if last_attempt.status != "failed":
            raise TranslationRunServiceError(
                f"Cannot retry segment {segment_id}: last attempt status is "
                f"{last_attempt.status!r}, expected 'failed'.",
            )
        if not last_attempt.retryable:
            raise TranslationRunServiceError(
                f"Cannot retry segment {segment_id}: last failure is permanent "
                "(not retryable).",
            )
        now = self._clock()
        try:
            self._attempt_repository.requeue_failed(segment_id=segment_id, now=now)
        except SegmentAttemptError as exc:
            raise TranslationRunServiceError(str(exc)) from exc
        updated = self._segment_repository.get_by_id(segment_id)
        assert updated is not None
        return updated

    def get_revision(self, revision_id: int) -> TranslationRevision | None:
        """Fetch a revision by id."""
        return self._revision_repository.get_by_id(revision_id)

    def get_run(self, run_id: int) -> TranslationRun | None:
        """Fetch a run by id."""
        return self._run_repository.get_by_id(run_id)

    def get_attempt(self, attempt_id: int) -> SegmentAttempt | None:
        """Fetch an attempt by id."""
        return self._attempt_repository.get_by_id(attempt_id)

    def list_runs_for_project(self, project_id: int) -> list[TranslationRun]:
        """Return all runs for a project."""
        return self._run_repository.list_by_project(project_id)

    def list_attempts_for_run(self, run_id: int) -> list[SegmentAttempt]:
        """Return all attempts for a run."""
        return self._attempt_repository.list_by_run(run_id)

    def close(self) -> None:
        """Close the service and release resources."""
        self._attempt_repository.close()
        self._revision_repository.close()
        self._run_repository.close()
        self._workflow_repository.close()
        self._project_repository.close()
        self._segment_repository.close()

    def __enter__(self) -> TranslationRunService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
