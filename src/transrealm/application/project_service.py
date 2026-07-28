"""Project application service."""

from pathlib import Path

from transrealm.domain.project import Project
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.project_repository import ProjectRepository


class ProjectService:
    """Application service for Project lifecycle operations."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._db = create_database(db_path)
        self._repository = ProjectRepository(self._db)
        self._run_migrations()

    def _run_migrations(self) -> None:
        from transrealm.infrastructure.migrations.discovery import discover_migrations

        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

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

    def save_project(self, project: Project) -> Project:
        """Persist project changes."""
        return self._repository.save(project)

    def close(self) -> None:
        """Close the service and release resources."""
        self._repository.close()
