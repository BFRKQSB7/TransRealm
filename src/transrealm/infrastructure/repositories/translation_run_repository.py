"""SQLite-backed repository for TranslationRun entities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from transrealm.domain.translation_run import TranslationRun, TranslationRunError
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class TranslationRunRepository:
    """SQLite-backed repository for TranslationRun entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> TranslationRunRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, run: TranslationRun) -> TranslationRun:
        """Insert a new run and return the persisted entity."""
        now = datetime.now().isoformat()
        if run.id is not None:
            with transaction(self._db):
                cursor = self._db.execute(
                    "UPDATE translation_runs SET project_id = ?, workflow_id = ?, "
                    "workflow_version = ?, workflow_definition_hash = ?, "
                    "workflow_definition_snapshot = ?, status = ?, "
                    "finished_at = ? WHERE id = ?",
                    (
                        run.project_id,
                        run.workflow_id,
                        run.workflow_version,
                        run.workflow_definition_hash,
                        run.workflow_definition_snapshot,
                        run.status,
                        run.finished_at.isoformat() if run.finished_at else None,
                        run.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise TranslationRunError(f"TranslationRun with id {run.id} does not exist.")
            loaded = self.get_by_id(run.id)
            assert loaded is not None
            return loaded

        with transaction(self._db):
            cursor = self._db.execute(
                "INSERT INTO translation_runs "
                "(project_id, workflow_id, workflow_version, workflow_definition_hash, "
                "workflow_definition_snapshot, status, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.project_id,
                    run.workflow_id,
                    run.workflow_version,
                    run.workflow_definition_hash,
                    run.workflow_definition_snapshot,
                    run.status,
                    now,
                    None,
                ),
            )
            new_id = cursor.lastrowid
        assert new_id is not None
        loaded = self.get_by_id(new_id)
        assert loaded is not None
        return loaded

    def get_by_id(self, run_id: int) -> TranslationRun | None:
        """Fetch a run by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, project_id, workflow_id, workflow_version, workflow_definition_hash, "
            "workflow_definition_snapshot, status, started_at, finished_at "
            "FROM translation_runs WHERE id = ?",
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_by_project(self, project_id: int) -> list[TranslationRun]:
        """Return all runs for a project ordered by id."""
        cursor = self._db.execute(
            "SELECT id, project_id, workflow_id, workflow_version, workflow_definition_hash, "
            "workflow_definition_snapshot, status, started_at, finished_at "
            "FROM translation_runs WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
        return [self._row_to_run(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_run(row: tuple[object, ...]) -> TranslationRun:
        return TranslationRun(
            id=int(str(row[0])),
            project_id=int(str(row[1])),
            workflow_id=int(str(row[2])),
            workflow_version=str(row[3]),
            workflow_definition_hash=str(row[4]),
            workflow_definition_snapshot=str(row[5]) if row[5] is not None else None,
            status=str(row[6]),
            started_at=datetime.fromisoformat(str(row[7])),
            finished_at=datetime.fromisoformat(str(row[8])) if row[8] is not None else None,
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
