"""SQLite-backed repository for TranslationRevision entities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from transrealm.domain.translation_revision import TranslationRevision, TranslationRevisionError
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class TranslationRevisionRepository:
    """SQLite-backed repository for TranslationRevision entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> TranslationRevisionRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, revision: TranslationRevision) -> TranslationRevision:
        """Insert a new revision and return the persisted entity."""
        if revision.id is not None:
            raise TranslationRevisionError(
                "TranslationRevision is immutable and cannot be updated.",
            )

        now = datetime.now().isoformat()
        with transaction(self._db):
            cursor = self._db.execute(
                "INSERT INTO translation_revisions "
                "(segment_id, text, origin, attempt_id, is_locked, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    revision.segment_id,
                    revision.text,
                    revision.origin,
                    revision.attempt_id,
                    1 if revision.is_locked else 0,
                    now,
                ),
            )
            new_id = cursor.lastrowid
        assert new_id is not None
        loaded = self.get_by_id(new_id)
        assert loaded is not None
        return loaded

    def get_by_id(self, revision_id: int) -> TranslationRevision | None:
        """Fetch a revision by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, segment_id, text, origin, attempt_id, is_locked, created_at "
            "FROM translation_revisions WHERE id = ?",
            (revision_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_revision(row)

    def list_by_segment(self, segment_id: int) -> list[TranslationRevision]:
        """Return all revisions for a segment ordered by creation time."""
        cursor = self._db.execute(
            "SELECT id, segment_id, text, origin, attempt_id, is_locked, created_at "
            "FROM translation_revisions WHERE segment_id = ? ORDER BY created_at, id",
            (segment_id,),
        )
        return [self._row_to_revision(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_revision(row: tuple[object, ...]) -> TranslationRevision:
        return TranslationRevision(
            id=int(str(row[0])),
            segment_id=int(str(row[1])),
            text=str(row[2]),
            origin=str(row[3]),
            attempt_id=int(str(row[4])) if row[4] is not None else None,
            is_locked=bool(row[5]),
            created_at=datetime.fromisoformat(str(row[6])),
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
