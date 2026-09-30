"""Persistence for the one current Notes value owned by a Project."""

from __future__ import annotations

from pathlib import Path

from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class ProjectNotesRepository:
    """Read and replace a Project's Notes without retaining a second copy."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> ProjectNotesRepository:
        return cls(create_database(path))

    def get(self, project_id: int) -> str:
        """Return persisted Notes, or an empty string when none were saved."""
        row = self._db.execute(
            "SELECT content FROM project_notes WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return "" if row is None else str(row[0])

    def set(self, project_id: int, content: str) -> None:
        """Replace Notes atomically; blank content clears the row."""
        with transaction(self._db):
            if content.strip():
                self._db.execute(
                    "INSERT INTO project_notes (project_id, content) VALUES (?, ?) "
                    "ON CONFLICT(project_id) DO UPDATE SET "
                    "content = excluded.content, updated_at = datetime('now')",
                    (project_id, content),
                )
            else:
                self._db.execute(
                    "DELETE FROM project_notes WHERE project_id = ?",
                    (project_id,),
                )

    def close(self) -> None:
        self._db.close()
