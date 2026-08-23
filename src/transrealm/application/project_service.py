"""Project application service."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from transrealm.domain.project import Project, ProjectError
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.backup import create_consistent_snapshot
from transrealm.infrastructure.migrations.discovery import Migration
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.model_profile_repository import (
    ModelProfileRepository,
)
from transrealm.infrastructure.repositories.project_repository import ProjectRepository


@dataclass(frozen=True)
class ProjectDeletionSummary:
    """User-facing deletion counts and active-work blockers."""

    project_id: int
    project_name: str
    source_documents: int
    segments: int
    translation_runs: int
    segment_attempts: int
    translation_revisions: int
    glossary_entries: int
    running_runs: int
    active_processing_leases: int


class ProjectDeletionBlockedError(ProjectError):
    """Raised when a Project has active work that must not be deleted."""

    def __init__(self, summary: ProjectDeletionSummary) -> None:
        blockers: list[str] = []
        if summary.running_runs:
            blockers.append(f"{summary.running_runs} running Run(s)")
        if summary.active_processing_leases:
            blockers.append(
                f"{summary.active_processing_leases} active processing lease(s)",
            )
        super().__init__(
            f"Project {summary.project_name!r} cannot be deleted: "
            + ", ".join(blockers)
            + ".",
        )
        self.summary = summary


class ProjectService:
    """Application service for Project lifecycle operations."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._applied_migrations: tuple[Migration, ...] = ()
        self._db = create_database(db_path)
        self._repository = ProjectRepository(self._db)
        self._profile_repository = ModelProfileRepository(self._db)
        try:
            self._run_migrations()
        except Exception:
            self._db.close()
            raise

    @property
    def applied_migrations(self) -> tuple[Migration, ...]:
        """Migrations applied during construction; empty when none were pending."""
        return self._applied_migrations

    def _run_migrations(self) -> None:
        from transrealm.infrastructure.migrations.discovery import discover_migrations

        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        self._applied_migrations = tuple(
            runner.apply(migrations, app_version=self._app_version),
        )

    def create_project(
        self,
        *,
        name: str,
        source_language: str,
        target_language: str,
    ) -> Project:
        """Create a new project and persist it."""
        project = Project.create(
            name=name,
            source_language=source_language,
            target_language=target_language,
        )
        return self._repository.save(project)

    def open_project(self) -> Project | None:
        """Load the first project in the database, or None if empty."""
        projects = self._repository.list_all()
        if not projects:
            return None
        return projects[0]

    def get_project(self, project_id: int) -> Project | None:
        """Load a single project by id, or None if not found."""
        return self._repository.get_by_id(project_id)

    def list_projects(self) -> list[Project]:
        """Return all projects ordered by id."""
        return self._repository.list_all()

    def save_project(self, project: Project) -> Project:
        """Persist project changes."""
        return self._repository.save(project)

    def set_mode(self, project_id: int, mode: str) -> Project:
        """Set the interaction mode for a project and persist it.

        Raises:
            ProjectError: If the project does not exist or ``mode`` is not a
                supported interaction mode.
        """
        project = self._repository.get_by_id(project_id)
        if project is None:
            raise ProjectError(f"Project with id {project_id} does not exist.")
        return self._repository.save(project.with_mode(mode))

    def select_active_profile(self, project_id: int, profile_id: int) -> Project:
        """Select the active ModelProfile for a project and persist it.

        Raises:
            ProjectError: If the project or the referenced profile does not exist.
        """
        project = self._repository.get_by_id(project_id)
        if project is None:
            raise ProjectError(f"Project with id {project_id} does not exist.")
        if self._profile_repository.get_by_id(profile_id) is None:
            raise ProjectError(
                f"ModelProfile with id {profile_id} does not exist.",
            )
        return self._repository.save(project.with_active_profile(profile_id))

    def clear_active_profile(self, project_id: int) -> Project:
        """Clear the active ModelProfile for a project and persist it."""
        project = self._repository.get_by_id(project_id)
        if project is None:
            raise ProjectError(f"Project with id {project_id} does not exist.")
        return self._repository.save(project.with_active_profile(None))

    def get_project_deletion_summary(self, project_id: int) -> ProjectDeletionSummary | None:
        """Return deletion counts for a Project, or ``None`` if it is missing."""
        project = self._repository.get_by_id(project_id)
        if project is None:
            return None
        counts = self._repository.get_deletion_counts(
            project_id,
            now=datetime.now().isoformat(),
        )
        return ProjectDeletionSummary(
            project_id=project_id,
            project_name=project.name,
            **counts,
        )

    def delete_project(self, project_id: int) -> Path | None:
        """Create a recoverable snapshot, then atomically delete a Project.

        The snapshot is retained next to the database after a successful delete
        so the operation has a concrete recovery point. Missing Projects are a
        no-op. Active Runs or unexpired processing leases fail before snapshot
        creation and therefore cannot cause a deletion side effect.
        """
        summary = self.get_project_deletion_summary(project_id)
        if summary is None:
            return None
        if summary.running_runs or summary.active_processing_leases:
            raise ProjectDeletionBlockedError(summary)

        backup_path = self._deletion_backup_path(project_id)
        create_consistent_snapshot(self._db_path, backup_path)
        deleted = self._repository.delete_project(
            project_id,
            now=datetime.now().isoformat(),
        )
        if deleted:
            return backup_path

        current = self.get_project_deletion_summary(project_id)
        if current is not None and (
            current.running_runs or current.active_processing_leases
        ):
            raise ProjectDeletionBlockedError(current)
        return None

    def _deletion_backup_path(self, project_id: int) -> Path:
        """Return a unique, discoverable path for a Project delete snapshot."""
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        stem = self._db_path.stem
        candidate = self._db_path.with_name(
            f"{stem}.project-delete-{project_id}-{timestamp}.db.bak",
        )
        suffix = 1
        while candidate.exists():
            candidate = self._db_path.with_name(
                f"{stem}.project-delete-{project_id}-{timestamp}-{suffix}.db.bak",
            )
            suffix += 1
        return candidate

    def close(self) -> None:
        """Close the service and release resources."""
        self._repository.close()

    def __enter__(self) -> "ProjectService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
