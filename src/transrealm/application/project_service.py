"""Project application service."""

from pathlib import Path

from transrealm.domain.project import Project, ProjectError
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import Migration
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.model_profile_repository import (
    ModelProfileRepository,
)
from transrealm.infrastructure.repositories.project_repository import ProjectRepository


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

    def close(self) -> None:
        """Close the service and release resources."""
        self._repository.close()

    def __enter__(self) -> "ProjectService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
