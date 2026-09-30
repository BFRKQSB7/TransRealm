"""Small application boundary for persisted Project/Job Notes."""

from __future__ import annotations

from pathlib import Path

from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.project_notes_repository import ProjectNotesRepository
from transrealm.infrastructure.repositories.project_repository import ProjectRepository


class ProjectNotesService:
    """Create, read, replace and clear one Notes value per Project."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db = create_database(db_path)
        self._notes = ProjectNotesRepository(self._db)
        self._projects = ProjectRepository(self._db)
        try:
            MigrationRunner(self._db).apply(
                discover_migrations(self.MIGRATIONS_DIR), app_version=app_version,
            )
        except Exception:
            self._db.close()
            raise

    def get_notes(self, project_id: int) -> str:
        """Read Notes for an existing Project."""
        self._ensure_project(project_id)
        return self._notes.get(project_id)

    def set_notes(self, project_id: int, content: str) -> str:
        """Replace Notes; whitespace-only content clears them."""
        self._ensure_project(project_id)
        if not isinstance(content, str):
            raise ValueError("Notes content must be a string.")
        value = content if content.strip() else ""
        self._notes.set(project_id, value)
        return value

    def _ensure_project(self, project_id: int) -> None:
        if self._projects.get_by_id(project_id) is None:
            raise ValueError(f"Project with id {project_id} does not exist.")

    def close(self) -> None:
        self._notes.close()

    def __enter__(self) -> ProjectNotesService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
