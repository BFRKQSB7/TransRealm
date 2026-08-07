"""Application service for project-scoped glossary entries."""

from __future__ import annotations

from pathlib import Path

from transrealm.domain.glossary_entry import (
    DEFAULT_PRIORITY,
    GlossaryEntry,
    GlossaryEntryError,
)
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.glossary_entry_repository import (
    GlossaryEntryRepository,
)
from transrealm.infrastructure.repositories.project_repository import ProjectRepository


class GlossaryService:
    """Application service for CRUD of project-scoped glossary entries."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._db = create_database(db_path)
        self._repository = GlossaryEntryRepository(self._db)
        self._project_repository = ProjectRepository(self._db)
        try:
            self._run_migrations()
        except Exception:
            self._db.close()
            raise

    def _run_migrations(self) -> None:
        from transrealm.infrastructure.migrations.discovery import discover_migrations

        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

    def create_entry(
        self,
        *,
        project_id: int,
        source_term: str,
        target_term: str,
        scope: str,
        priority: int = DEFAULT_PRIORITY,
        is_locked: bool = False,
        origin: str = "user",
    ) -> GlossaryEntry:
        """Create and persist a new glossary entry for a project.

        Raises:
            GlossaryEntryError: If the project does not exist or an entry with
                the same source term already exists in the project.
        """
        self._ensure_project_exists(project_id)
        self._ensure_no_duplicate(project_id, source_term)
        entry = GlossaryEntry.create(
            project_id=project_id,
            source_term=source_term,
            target_term=target_term,
            scope=scope,
            priority=priority,
            is_locked=is_locked,
            origin=origin,
        )
        return self._repository.save(entry)

    def update_entry(
        self,
        entry_id: int,
        *,
        source_term: str | None = None,
        target_term: str | None = None,
        scope: str | None = None,
        priority: int | None = None,
        is_locked: bool | None = None,
    ) -> GlossaryEntry:
        """Update an existing glossary entry and persist it.

        Raises:
            GlossaryEntryError: If the entry does not exist, or the new source
                term already belongs to a different entry in the same project.
        """
        existing = self._repository.get_by_id(entry_id)
        if existing is None:
            raise GlossaryEntryError(
                f"GlossaryEntry with id {entry_id} does not exist.",
            )
        if source_term is not None:
            self._ensure_no_duplicate(
                existing.project_id,
                source_term,
                exclude_id=entry_id,
            )
        updated = existing.with_updated_fields(
            source_term=source_term,
            target_term=target_term,
            scope=scope,
            priority=priority,
            is_locked=is_locked,
        )
        return self._repository.save(updated)

    def get_entry(self, entry_id: int) -> GlossaryEntry | None:
        """Fetch a glossary entry by id."""
        return self._repository.get_by_id(entry_id)

    def list_entries(self, project_id: int) -> list[GlossaryEntry]:
        """Return all glossary entries for a project."""
        return self._repository.list_by_project(project_id)

    def list_locked_entries(self, project_id: int) -> list[GlossaryEntry]:
        """Return only locked glossary entries for a project."""
        return self._repository.list_locked_by_project(project_id)

    def delete_entry(self, entry_id: int) -> bool:
        """Delete a glossary entry by id. Returns True if a row was removed."""
        return self._repository.delete(entry_id)

    def _ensure_project_exists(self, project_id: int) -> None:
        """Raise GlossaryEntryError if the referenced project does not exist."""
        if self._project_repository.get_by_id(project_id) is None:
            raise GlossaryEntryError(
                f"Project with id {project_id} does not exist.",
            )

    def _ensure_no_duplicate(
        self,
        project_id: int,
        source_term: str,
        *,
        exclude_id: int | None = None,
    ) -> None:
        """Raise GlossaryEntryError when the source term already exists.

        The ``(project_id, source_term)`` uniqueness is pre-checked here so the
        caller gets a clear domain error; the DB UNIQUE constraint backstops
        concurrent writers and rolls back the insert.
        """
        if not isinstance(source_term, str):
            raise GlossaryEntryError("source_term must be a string.")
        existing = self._repository.find_by_project_and_source(
            project_id,
            source_term.strip(),
        )
        if existing is not None and existing.id != exclude_id:
            raise GlossaryEntryError(
                f"Glossary entry with source_term {source_term!r} already "
                f"exists in project {project_id}.",
            )

    def close(self) -> None:
        """Close the service and release resources."""
        self._repository.close()

    def __enter__(self) -> GlossaryService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
