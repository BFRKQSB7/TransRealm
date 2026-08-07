"""SQLite-backed repository for GlossaryEntry entities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from transrealm.domain.glossary_entry import GlossaryEntry
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class GlossaryEntryRepository:
    """SQLite-backed repository for GlossaryEntry entities."""

    _COLUMNS = (
        "id, project_id, source_term, target_term, scope, priority, is_locked, "
        "origin, created_at, updated_at"
    )

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> GlossaryEntryRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, entry: GlossaryEntry) -> GlossaryEntry:
        """Insert or update a glossary entry and return the persisted entity."""
        now = datetime.now().isoformat()
        if entry.id is None:
            with transaction(self._db):
                cursor = self._db.execute(
                    "INSERT INTO glossary_entries "
                    "(project_id, source_term, target_term, scope, priority, "
                    "is_locked, origin, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.project_id,
                        entry.source_term,
                        entry.target_term,
                        entry.scope,
                        entry.priority,
                        1 if entry.is_locked else 0,
                        entry.origin,
                        now,
                        now,
                    ),
                )
                new_id = cursor.lastrowid
            assert new_id is not None
            loaded = self.get_by_id(new_id)
            assert loaded is not None
            return loaded

        with transaction(self._db):
            cursor = self._db.execute(
                "UPDATE glossary_entries SET source_term = ?, target_term = ?, "
                "scope = ?, priority = ?, is_locked = ?, updated_at = ? WHERE id = ?",
                (
                    entry.source_term,
                    entry.target_term,
                    entry.scope,
                    entry.priority,
                    1 if entry.is_locked else 0,
                    now,
                    entry.id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"GlossaryEntry with id {entry.id} does not exist.")
        loaded = self.get_by_id(entry.id)
        assert loaded is not None
        return loaded

    def get_by_id(self, entry_id: int) -> GlossaryEntry | None:
        """Fetch a glossary entry by id, or None if not found."""
        cursor = self._db.execute(
            f"SELECT {self._COLUMNS} FROM glossary_entries WHERE id = ?",
            (entry_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def find_by_project_and_source(
        self,
        project_id: int,
        source_term: str,
    ) -> GlossaryEntry | None:
        """Return the entry for a source term within a project, or None."""
        cursor = self._db.execute(
            f"SELECT {self._COLUMNS} FROM glossary_entries "
            "WHERE project_id = ? AND source_term = ?",
            (project_id, source_term),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def list_by_project(self, project_id: int) -> list[GlossaryEntry]:
        """Return all entries for a project ordered by priority then id."""
        cursor = self._db.execute(
            f"SELECT {self._COLUMNS} FROM glossary_entries "
            "WHERE project_id = ? ORDER BY priority DESC, id",
            (project_id,),
        )
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    def list_locked_by_project(self, project_id: int) -> list[GlossaryEntry]:
        """Return only locked entries for a project ordered by priority then id."""
        cursor = self._db.execute(
            f"SELECT {self._COLUMNS} FROM glossary_entries "
            "WHERE project_id = ? AND is_locked = 1 ORDER BY priority DESC, id",
            (project_id,),
        )
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    def delete(self, entry_id: int) -> bool:
        """Delete a glossary entry by id. Returns True if a row was removed."""
        with transaction(self._db):
            cursor = self._db.execute(
                "DELETE FROM glossary_entries WHERE id = ?",
                (entry_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_entry(row: tuple[object, ...]) -> GlossaryEntry:
        return GlossaryEntry(
            id=int(str(row[0])),
            project_id=int(str(row[1])),
            source_term=str(row[2]),
            target_term=str(row[3]),
            scope=str(row[4]),
            priority=int(str(row[5])),
            is_locked=bool(int(str(row[6]))),
            origin=str(row[7]),
            created_at=datetime.fromisoformat(str(row[8])),
            updated_at=datetime.fromisoformat(str(row[9])),
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
