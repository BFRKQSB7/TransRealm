"""Tests for P0-T07-M01: recoverable execution skeleton."""

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
from transrealm.domain.translation_workflow import (
    WorkflowDefinition,
    WorkflowDefinitionError,
    compute_definition_hash,
)
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.errors import MigrationExecutionError
from transrealm.infrastructure.migrations.runner import MigrationRunner

APP_VERSION = "0.0.0-test"


def _create_pre005_database(path: Path) -> None:
    """Create a database with migrations 001-005 applied and no T07 tables."""
    migrations_dir = Path(__file__).parent.parent / "src" / "transrealm" / "migrations"
    migrations = discover_migrations(migrations_dir)
    pre_t07 = [m for m in migrations if m.migration_id < "006"]
    runner = MigrationRunner.open(path)
    try:
        runner.apply(pre_t07, app_version=APP_VERSION)
    finally:
        runner.close()


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


class TestM01Migration:
    """Migration 006 applies to existing and new databases."""

    def test_migration_applies_to_pre_t07_database(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        _create_pre005_database(db_path)

        migrations_dir = Path(__file__).parent.parent / "src" / "transrealm" / "migrations"
        migrations = discover_migrations(migrations_dir)
        runner = MigrationRunner.open(db_path)
        try:
            applied = runner.apply(migrations, app_version=APP_VERSION)
        finally:
            runner.close()

        assert any(m.migration_id == "006_add_workflow_run_attempt_revision" for m in applied)
        db = create_database(db_path)
        try:
            cursor = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('workflow_definitions', 'translation_runs', 'segment_attempts', "
                "'translation_revisions')",
            )
            tables = {row[0] for row in cursor.fetchall()}
        finally:
            db.close()
        assert tables == {
            "workflow_definitions",
            "translation_runs",
            "segment_attempts",
            "translation_revisions",
        }

    def test_migration_creates_backup_before_upgrading(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        _create_pre005_database(db_path)

        migrations_dir = Path(__file__).parent.parent / "src" / "transrealm" / "migrations"
        migrations = discover_migrations(migrations_dir)
        runner = MigrationRunner.open(db_path)
        try:
            runner.apply(migrations, app_version=APP_VERSION)
        finally:
            runner.close()

        assert runner.last_backup_path is not None
        assert runner.last_backup_path.exists()
        backup = create_database(runner.last_backup_path)
        try:
            backup.execute("SELECT name FROM sqlite_master WHERE type='table'")
        finally:
            backup.close()

    def test_migration_failure_rolls_back_and_keeps_backup(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        _create_pre005_database(db_path)

        migrations_dir = Path(__file__).parent.parent / "src" / "transrealm" / "migrations"
        migrations = discover_migrations(migrations_dir)
        bad_migrations: list = []
        for migration in migrations:
            if migration.migration_id == "006_add_workflow_run_attempt_revision":
                bad_sql = migration.sql + "\nSELECT * FROM __nonexistent_table_for_rollback_test;"
                bad_migrations.append(
                    type(migration)(
                        migration_id=migration.migration_id,
                        path=migration.path,
                        sql=bad_sql,
                        checksum=migration.checksum,
                    ),
                )
            else:
                bad_migrations.append(migration)

        runner = MigrationRunner.open(db_path)
        try:
            with pytest.raises(MigrationExecutionError):
                runner.apply(bad_migrations, app_version=APP_VERSION)
        finally:
            runner.close()

        # Backup should still exist from the pending phase.
        assert runner.last_backup_path is not None
        assert runner.last_backup_path.exists()

        # The target database should not have T07 tables from the failed migration.
        db = create_database(db_path)
        try:
            cursor = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_definitions'",
            )
            assert cursor.fetchone() is None
        finally:
            db.close()

    def test_migration_is_idempotent_on_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        with ProjectService(db_path, app_version=APP_VERSION):
            pass

        with ProjectService(db_path, app_version=APP_VERSION):
            pass

        db = create_database(db_path)
        try:
            cursor = db.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
                ("006_add_workflow_run_attempt_revision",),
            )
            assert cursor.fetchone()[0] == 1
        finally:
            db.close()


class TestBuiltinWorkflow:
    """Built-in workflow is seeded, versioned, read-only and hash-verified."""

    def test_builtin_workflow_seeded_on_new_project(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            assert workflow is not None
            assert workflow.origin == "builtin"
            assert workflow.is_read_only is True
            assert workflow.definition_hash == BUILTIN_GENERAL_TRANSLATION_WORKFLOW.definition_hash

    def test_builtin_workflow_seeded_on_existing_project(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        _create_project(db_path)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            assert workflow is not None

    def test_reopening_does_not_duplicate_builtin_workflow(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        with TranslationRunService(db_path, app_version=APP_VERSION):
            pass

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflows = service._workflow_repository.list_all()
            builtin = [w for w in workflows if w.name == BUILTIN_GENERAL_TRANSLATION_WORKFLOW.name]
            assert len(builtin) == 1

    def test_builtin_workflow_definition_hash_is_verified(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            assert workflow is not None
            # Tamper with the persisted hash directly, bypassing the read-only guard.
            service._db.execute(
                "UPDATE workflow_definitions SET definition_hash = ? WHERE id = ?",
                ("tampered", workflow_id),
            )
            service._db.connection.commit()

        with pytest.raises(WorkflowDefinitionError, match="hash"):
            TranslationRunService(db_path, app_version=APP_VERSION)

    def test_builtin_workflow_is_read_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            assert workflow is not None
            workflow.definition_json = {"steps": []}
            workflow.definition_hash = compute_definition_hash(workflow.definition_json)
            with pytest.raises(WorkflowDefinitionError, match="read-only"):
                service._workflow_repository.save(workflow)

    def test_duplicate_workflow_version_is_rejected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            assert workflow is not None
            duplicate = WorkflowDefinition.create_builtin(
                name=BUILTIN_GENERAL_TRANSLATION_WORKFLOW.name,
                version=BUILTIN_GENERAL_TRANSLATION_WORKFLOW.version,
                definition={"steps": ["different"]},
            )
            with pytest.raises(Exception):
                service._workflow_repository.save(duplicate)


class TestTranslationRun:
    """TranslationRun references a valid workflow version snapshot."""

    def test_create_run_saves_workflow_version_and_hash(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None

        assert run.workflow_version == BUILTIN_GENERAL_TRANSLATION_WORKFLOW.version
        assert run.workflow_definition_hash == BUILTIN_GENERAL_TRANSLATION_WORKFLOW.definition_hash
        assert run.workflow_definition_snapshot is not None

        db = create_database(db_path)
        try:
            cursor = db.execute(
                "SELECT workflow_definition_snapshot FROM translation_runs "
                "WHERE id = ?",
                (run.id,),
            )
            assert cursor.fetchone()[0] == run.workflow_definition_snapshot
        finally:
            db.close()

    def test_create_run_rejects_invalid_project(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            with pytest.raises(TranslationRunServiceError, match="Project"):
                service.create_run(project_id=9999, workflow_id=workflow_id)

    def test_create_run_rejects_invalid_workflow(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(TranslationRunServiceError, match="Workflow"):
                service.create_run(project_id=project_id, workflow_id=9999)

    def test_run_snapshot_survives_workflow_change(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow = WorkflowDefinition(
                id=None,
                name="editable_translation",
                origin="user",
                parent_workflow_id=None,
                version="1.0.0",
                definition_json={"steps": [{"step": "original"}]},
                definition_hash=compute_definition_hash({"steps": [{"step": "original"}]}),
                is_read_only=False,
                created_at=None,
            )
            workflow = service._workflow_repository.save(workflow)
            assert workflow.id is not None
            run = service.create_run(project_id=project_id, workflow_id=workflow.id)
            assert run.id is not None
            original_snapshot = run.workflow_definition_snapshot
            assert original_snapshot is not None

            workflow.definition_json = {"steps": [{"step": "changed"}]}
            workflow.definition_hash = compute_definition_hash(workflow.definition_json)
            service._workflow_repository.save(workflow)

            reopened = service.get_run(run.id)
            assert reopened is not None
            assert reopened.workflow_definition_snapshot == original_snapshot
            assert reopened.workflow_definition_hash == compute_definition_hash(
                {"steps": [{"step": "original"}]},
            )
            current = service._workflow_repository.get_by_id(workflow.id)
            assert current is not None
            assert current.definition_json == {"steps": [{"step": "changed"}]}

    def test_run_is_reopenable(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            reopened = service.get_run(run.id)
            assert reopened is not None
            assert reopened.project_id == project_id


class TestSegmentAttempt:
    """SegmentAttempt is persisted before the first external request."""

    def test_start_attempt_claims_segment_and_creates_attempt(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\nsecond line\n")
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
                context_summary={"selected": ["seg1"], "pruned": []},
                validator_summary={"contract": "json"},
            )
            assert attempt.id is not None

        assert attempt.status == "created"
        assert attempt.claim_version > segment.version
        assert attempt.lease_owner.startswith("owner:")
        assert attempt.prompt_hash == "abc123"
        assert attempt.profile_snapshot["profile_id"] == profile.id
        assert attempt.profile_snapshot["model_id"] == profile.model_id
        assert attempt.model_profile_id == profile.id

    def test_attempt_is_reopenable(self, tmp_path: Path) -> None:
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
                context_summary={"selected": []},
                validator_summary={"contract": "json"},
            )
            assert attempt.id is not None
            reopened = service.get_attempt(attempt.id)
            assert reopened is not None
            assert reopened.idempotency_key == attempt.idempotency_key
            assert reopened.claim_version == attempt.claim_version

    def test_start_attempt_rejects_non_pending_segment(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        # Create a modified segment that is already processing.
        segment.status = "processing"
        profile = _create_profile(db_path)

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

    def test_start_attempt_rejects_invalid_run(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(TranslationRunServiceError, match="TranslationRun"):
                service.start_attempt(
                    run_id=9999,
                    segment=segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )

    def test_attempt_idempotency_key_is_unique(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            service.start_attempt(
                run_id=run.id,
                segment=segment,
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
            )

            # A second attempt with the same idempotency_key must violate the
            # unique constraint. We bypass the random key generator to prove the
            # schema protects the constraint.
            db = service._db
            with pytest.raises(Exception):
                db.execute(
                    "INSERT INTO segment_attempts "
                    "(run_id, segment_id, claim_version, lease_owner, idempotency_key, "
                    "model_profile_id, profile_snapshot, prompt_hash, context_summary, "
                    "validator_summary, status, retryable, created_at) "
                    "SELECT run_id, segment_id, claim_version, lease_owner, idempotency_key, "
                    "model_profile_id, profile_snapshot, prompt_hash, context_summary, "
                    "validator_summary, status, retryable, created_at FROM segment_attempts",
                )
                db.connection.commit()

    def test_segment_lease_is_updated_on_claim(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        fixed_now = datetime.now(UTC)

        with TranslationRunService(
            db_path,
            app_version=APP_VERSION,
            clock=lambda: fixed_now,
        ) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            service.start_attempt(
                run_id=run.id,
                segment=segment,
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
                lease_duration_seconds=120,
            )

        from transrealm.infrastructure.repositories.segment_repository import (
            SegmentRepository,
        )

        repo = SegmentRepository.open(db_path)
        try:
            persisted = repo.find_segment_by_stable_key(
                segment.source_document_id,
                segment.stable_key,
            )
            assert persisted is not None
            assert persisted.status == "processing"
            assert persisted.lease_owner is not None
            assert persisted.lease_expires_at is not None
            assert persisted.lease_expires_at > fixed_now
            assert persisted.lease_expires_at <= fixed_now + timedelta(seconds=120)
        finally:
            repo.close()

    def test_attempt_rejects_missing_segment(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        profile = _create_profile(db_path)
        segments = _import_txt(db_path, project_id, "x\n")
        fake_segment = segments[0]
        fake_segment.id = 9999

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            with pytest.raises(TranslationRunServiceError, match="stable key"):
                service.start_attempt(
                    run_id=run.id,
                    segment=fake_segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )

    def test_attempt_rejects_segment_with_changed_stable_key(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)
        segment.stable_key = "tampered-key"

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            with pytest.raises(TranslationRunServiceError, match="stable key"):
                service.start_attempt(
                    run_id=run.id,
                    segment=segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )

    def test_attempt_rejects_completed_run(self, tmp_path: Path) -> None:
        db_path = tmp_path / "project.sqlite"
        project_id = _create_project(db_path)
        segments = _import_txt(db_path, project_id, "first line\n")
        segment = segments[0]
        profile = _create_profile(db_path)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow, workflow_id = _builtin_workflow(service)
            run = service.create_run(project_id=project_id, workflow_id=workflow_id)
            assert run.id is not None
            run.status = "completed"
            service._run_repository.save(run)
            with pytest.raises(TranslationRunServiceError, match="status"):
                service.start_attempt(
                    run_id=run.id,
                    segment=segment,
                    profile=profile,
                    prompt_hash="abc123",
                    context_summary={},
                    validator_summary={},
                )
