"""Tests for P1-T04-M01: Project active Profile selection.

Covers: select/change/clear active profile with reopen persistence, clear
errors for invalid references, and delete protection when a profile is active
in a project or referenced by historical attempts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import (
    BUILTIN_GENERAL_TRANSLATION_WORKFLOW,
    TranslationRunService,
)
from transrealm.domain.model_profile import (
    ModelCapability,
    ModelProfile,
    ModelProfileInUseError,
)
from transrealm.domain.project import Project, ProjectError
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner

APP_VERSION = "0.0.0-test"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "project.db"


def _create_connection(db_path: Path, name: str = "local") -> int:
    """Create a provider connection and return its id."""
    with ProviderConnectionService(db_path, app_version=APP_VERSION) as service:
        connection = service.create_connection(
            name=name,
            provider_type="openai-compatible",
            endpoint="http://localhost:8080/v1",
            timeout_seconds=30,
            max_retries=0,
            retry_delay_seconds=0.0,
            credential_reference="env:TEST_KEY",
        )
    assert connection.id is not None
    return connection.id


def _create_profile(db_path: Path, connection_id: int, name: str = "profile") -> ModelProfile:
    """Create a model profile and return it."""
    with ModelProfileService(db_path, app_version=APP_VERSION) as service:
        profile = service.create_profile(
            name=name,
            provider_connection_id=connection_id,
            model_id="test-model",
            template_version="1.0",
            output_protocol="json",
            context_budget={"max_context": 2048},
            default_params={"temperature": 0.3},
            capability=ModelCapability(
                context_window=4096,
                max_output_tokens=512,
                supports_streaming=False,
                supports_structured_output=True,
                supported_parameters={"temperature"},
            ),
        )
    return profile


def _create_project(db_path: Path, name: str = "Test") -> Project:
    """Create a project and return it."""
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        return service.create_project(
            name=name,
            source_language="ja",
            target_language="zh",
        )


def _project_id(project: object) -> int:
    assert getattr(project, "id") is not None
    return int(getattr(project, "id"))


def _import_segments(db_path: Path, project_id: int, content: str = "first line\n") -> list:
    """Import a TXT file and return the created segments."""
    txt_path = db_path.parent / "source.txt"
    txt_path.write_text(content, encoding="utf-8")
    with ImportService(db_path, app_version=APP_VERSION) as service:
        _, segments = service.import_txt(
            project_id,
            txt_path,
            name="source.txt",
        )
    return segments


class TestProjectActiveProfileSelection:
    """Project select/change/clear active profile and reopen persistence."""

    def test_new_project_has_no_active_profile(self, db_path: Path) -> None:
        """A freshly created project has no active profile."""
        project = _create_project(db_path)
        assert project.active_profile_id is None

    def test_select_active_profile_persists_across_reopen(self, db_path: Path) -> None:
        """Selecting an active profile survives closing and reopening."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id)
        assert profile.id is not None
        project = _create_project(db_path)
        project_id = _project_id(project)

        with ProjectService(db_path, app_version=APP_VERSION) as service:
            selected = service.select_active_profile(project_id, profile.id)
            assert selected.active_profile_id == profile.id

        reopened = ProjectService(db_path, app_version=APP_VERSION)
        try:
            loaded = reopened.open_project()
            assert loaded is not None
            assert loaded.active_profile_id == profile.id
        finally:
            reopened.close()

    def test_change_active_profile(self, db_path: Path) -> None:
        """Changing the active profile replaces the previous selection."""
        connection_id = _create_connection(db_path)
        profile_a = _create_profile(db_path, connection_id, name="a")
        profile_b = _create_profile(db_path, connection_id, name="b")
        assert profile_a.id is not None and profile_b.id is not None
        project = _create_project(db_path)
        project_id = _project_id(project)

        with ProjectService(db_path, app_version=APP_VERSION) as service:
            service.select_active_profile(project_id, profile_a.id)
            changed = service.select_active_profile(project_id, profile_b.id)
            assert changed.active_profile_id == profile_b.id

        reopened = ProjectService(db_path, app_version=APP_VERSION)
        try:
            loaded = reopened.open_project()
            assert loaded is not None
            assert loaded.active_profile_id == profile_b.id
        finally:
            reopened.close()

    def test_clear_active_profile_persists_across_reopen(self, db_path: Path) -> None:
        """Clearing the active profile survives reopening."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id)
        assert profile.id is not None
        project = _create_project(db_path)
        project_id = _project_id(project)

        with ProjectService(db_path, app_version=APP_VERSION) as service:
            service.select_active_profile(project_id, profile.id)
            cleared = service.clear_active_profile(project_id)
            assert cleared.active_profile_id is None

        reopened = ProjectService(db_path, app_version=APP_VERSION)
        try:
            loaded = reopened.open_project()
            assert loaded is not None
            assert loaded.active_profile_id is None
        finally:
            reopened.close()

    def test_active_profile_is_project_scoped(self, db_path: Path) -> None:
        """Two projects select different active profiles independently."""
        connection_id = _create_connection(db_path)
        profile_a = _create_profile(db_path, connection_id, name="a")
        profile_b = _create_profile(db_path, connection_id, name="b")
        assert profile_a.id is not None and profile_b.id is not None
        project_a = _create_project(db_path, name="A")
        project_b = _create_project(db_path, name="B")

        with ProjectService(db_path, app_version=APP_VERSION) as service:
            service.select_active_profile(_project_id(project_a), profile_a.id)
            service.select_active_profile(_project_id(project_b), profile_b.id)
            loaded_a = service.open_project()
        assert loaded_a is not None and loaded_a.name == "A"
        assert loaded_a.active_profile_id == profile_a.id

        reopened = ProjectService(db_path, app_version=APP_VERSION)
        try:
            both = reopened.list_projects()
        finally:
            reopened.close()
        by_name = {p.name: p for p in both}
        assert by_name["A"].active_profile_id == profile_a.id
        assert by_name["B"].active_profile_id == profile_b.id


class TestProjectActiveProfileErrors:
    """Clear errors for invalid active-profile references."""

    def test_select_active_profile_rejects_missing_project(self, db_path: Path) -> None:
        """Selecting for a missing project raises a clear error."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id)
        assert profile.id is not None
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ProjectError):
                service.select_active_profile(9999, profile.id)

    def test_select_active_profile_rejects_missing_profile(self, db_path: Path) -> None:
        """Selecting a non-existent profile raises a clear error."""
        project = _create_project(db_path)
        project_id = _project_id(project)
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ProjectError):
                service.select_active_profile(project_id, 9999)

    def test_clear_active_profile_rejects_missing_project(self, db_path: Path) -> None:
        """Clearing for a missing project raises a clear error."""
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ProjectError):
                service.clear_active_profile(9999)

    def test_repository_save_rejects_missing_project(self, db_path: Path) -> None:
        """Saving a project with a stale id raises ValueError."""
        _create_project(db_path)
        bogus = Project(
            id=9999,
            name="ghost",
            source_language="a",
            target_language="b",
            created_at=None,
            updated_at=None,
            schema_version=1,
            active_profile_id=None,
        )
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ValueError):
                service._repository.save(bogus)
            assert len(service.list_projects()) == 1


class TestDeleteProtection:
    """Profiles referenced by projects or attempts cannot be deleted."""

    def test_delete_profile_blocked_when_active_in_project(self, db_path: Path) -> None:
        """Deleting a profile active in a project raises a clear error."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id, name="bound")
        assert profile.id is not None
        project = _create_project(db_path, name="Alpha")
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            service.select_active_profile(_project_id(project), profile.id)

        with ModelProfileService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ModelProfileInUseError) as exc_info:
                service.delete_profile(profile.id)
            message = str(exc_info.value)
            assert "Alpha" in message
            assert service.get_profile(profile.id) is not None

    def test_delete_profile_blocked_when_shared_by_two_projects(self, db_path: Path) -> None:
        """The delete error lists every project referencing the profile."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id, name="shared")
        assert profile.id is not None
        project_a = _create_project(db_path, name="Alpha")
        project_b = _create_project(db_path, name="Beta")
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            service.select_active_profile(_project_id(project_a), profile.id)
            service.select_active_profile(_project_id(project_b), profile.id)

        with ModelProfileService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ModelProfileInUseError) as exc_info:
                service.delete_profile(profile.id)
            message = str(exc_info.value)
            assert "Alpha" in message and "Beta" in message
            assert service.get_profile(profile.id) is not None

    def test_clear_active_profile_is_idempotent(self, db_path: Path) -> None:
        """Clearing an already-cleared active profile stays None."""
        project = _create_project(db_path)
        project_id = _project_id(project)
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            first = service.clear_active_profile(project_id)
            second = service.clear_active_profile(project_id)
            assert first.active_profile_id is None
            assert second.active_profile_id is None

    def test_delete_profile_blocked_when_used_by_attempt(self, db_path: Path) -> None:
        """Deleting a profile referenced by a historical attempt raises a clear error."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id, name="attempted")
        assert profile.id is not None
        project = _create_project(db_path)
        project_id = _project_id(project)
        segments = _import_segments(db_path, project_id)

        with TranslationRunService(db_path, app_version=APP_VERSION) as service:
            workflow = service._workflow_repository.get_by_name_and_version(
                BUILTIN_GENERAL_TRANSLATION_WORKFLOW.name,
                BUILTIN_GENERAL_TRANSLATION_WORKFLOW.version,
            )
            assert workflow is not None and workflow.id is not None
            run = service.create_run(project_id=project_id, workflow_id=workflow.id)
            assert run.id is not None
            service.start_attempt(
                run_id=run.id,
                segment=segments[0],
                profile=profile,
                prompt_hash="abc123",
                context_summary={},
                validator_summary={},
            )

        with ModelProfileService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ModelProfileInUseError) as exc_info:
                service.delete_profile(profile.id)
            assert "attempt" in str(exc_info.value).lower()
            assert service.get_profile(profile.id) is not None

    def test_unreferenced_profile_can_be_deleted(self, db_path: Path) -> None:
        """A profile with no project or attempt references can be deleted."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id, name="free")
        assert profile.id is not None
        _create_project(db_path)

        with ModelProfileService(db_path, app_version=APP_VERSION) as service:
            assert service.delete_profile(profile.id) is True
            assert service.get_profile(profile.id) is None

    def test_delete_profile_blocked_after_clear_active(self, db_path: Path) -> None:
        """Clearing the project's active profile releases the delete guard."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id, name="released")
        assert profile.id is not None
        project = _create_project(db_path)
        project_id = _project_id(project)
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            service.select_active_profile(project_id, profile.id)
            service.clear_active_profile(project_id)

        with ModelProfileService(db_path, app_version=APP_VERSION) as service:
            assert service.delete_profile(profile.id) is True

    def test_db_foreign_key_backstops_active_profile_delete(self, db_path: Path) -> None:
        """The DB foreign key RESTRICT blocks a direct raw delete as a backstop."""
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id, name="backstop")
        assert profile.id is not None
        project = _create_project(db_path, name="Zed")
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            service.select_active_profile(_project_id(project), profile.id)

        db = create_database(db_path)
        try:
            with pytest.raises(Exception):
                db.execute("DELETE FROM model_profiles WHERE id = ?", (profile.id,))
                db.connection.commit()
        finally:
            db.close()


class TestMigration009:
    """Migration 009 upgrades old databases and backfills NULL active profile."""

    def _apply_through_008(self, path: Path) -> None:
        migrations_dir = Path(__file__).parent.parent / "src" / "transrealm" / "migrations"
        migrations = discover_migrations(migrations_dir)
        pre_009 = [m for m in migrations if m.migration_id < "009_add_project_active_profile"]
        runner = MigrationRunner.open(path)
        try:
            runner.apply(pre_009, app_version=APP_VERSION)
        finally:
            runner.close()

    def test_migration_009_adds_column_to_old_database(self, db_path: Path) -> None:
        """A pre-009 database gains the column with NULL for existing rows."""
        self._apply_through_008(db_path)
        project = _create_project(db_path)
        assert project.active_profile_id is None

        db = create_database(db_path)
        try:
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(projects)").fetchall()
            }
            applied = {
                row[0]
                for row in db.execute(
                    "SELECT migration_id FROM schema_migrations ORDER BY migration_id",
                ).fetchall()
            }
        finally:
            db.close()
        assert "active_profile_id" in columns
        assert "009_add_project_active_profile" in applied

    def test_old_database_can_select_after_upgrade(self, db_path: Path) -> None:
        """Old projects can select an active profile after the 009 upgrade."""
        self._apply_through_008(db_path)
        connection_id = _create_connection(db_path)
        profile = _create_profile(db_path, connection_id)
        assert profile.id is not None
        project = _create_project(db_path)
        project_id = _project_id(project)

        with ProjectService(db_path, app_version=APP_VERSION) as service:
            selected = service.select_active_profile(project_id, profile.id)
            assert selected.active_profile_id == profile.id
