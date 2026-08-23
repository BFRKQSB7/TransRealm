"""Project repository implementation."""

from datetime import datetime
from pathlib import Path
from typing import TypedDict

from transrealm.domain.project import Project
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class ProjectDeletionCounts(TypedDict):
    """Project-owned row counts and deletion blockers."""

    source_documents: int
    segments: int
    translation_runs: int
    segment_attempts: int
    translation_revisions: int
    glossary_entries: int
    running_runs: int
    active_processing_leases: int


class ProjectRepository:
    """SQLite-backed repository for Project entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> "ProjectRepository":
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, project: Project) -> Project:
        """Insert or update a project and return the persisted entity."""
        now = datetime.now().isoformat()
        if project.id is None:
            with transaction(self._db):
                cursor = self._db.execute(
                    "INSERT INTO projects "
                    "(name, source_language, target_language, created_at, updated_at, "
                    "schema_version, active_profile_id, mode) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        project.name,
                        project.source_language,
                        project.target_language,
                        now,
                        now,
                        project.schema_version,
                        project.active_profile_id,
                        project.mode,
                    ),
                )
                new_id = cursor.lastrowid
            return Project(
                id=new_id,
                name=project.name,
                source_language=project.source_language,
                target_language=project.target_language,
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
                schema_version=project.schema_version,
                active_profile_id=project.active_profile_id,
                mode=project.mode,
            )

        with transaction(self._db):
            cursor = self._db.execute(
                "UPDATE projects SET name = ?, source_language = ?, target_language = ?, "
                "updated_at = ?, schema_version = ?, active_profile_id = ?, mode = ? "
                "WHERE id = ?",
                (
                    project.name,
                    project.source_language,
                    project.target_language,
                    now,
                    project.schema_version,
                    project.active_profile_id,
                    project.mode,
                    project.id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Project with id {project.id} does not exist.")
        return Project(
            id=project.id,
            name=project.name,
            source_language=project.source_language,
            target_language=project.target_language,
            created_at=project.created_at,
            updated_at=datetime.fromisoformat(now),
            schema_version=project.schema_version,
            active_profile_id=project.active_profile_id,
            mode=project.mode,
        )

    def get_by_id(self, project_id: int) -> Project | None:
        """Fetch a project by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, name, source_language, target_language, created_at, updated_at, "
            "schema_version, active_profile_id, mode FROM projects WHERE id = ?",
            (project_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def list_all(self) -> list[Project]:
        """Return all projects ordered by id."""
        cursor = self._db.execute(
            "SELECT id, name, source_language, target_language, created_at, updated_at, "
            "schema_version, active_profile_id, mode FROM projects ORDER BY id",
        )
        return [self._row_to_project(row) for row in cursor.fetchall()]

    def list_by_active_profile(self, profile_id: int) -> list[Project]:
        """Return all projects whose active profile references ``profile_id``."""
        cursor = self._db.execute(
            "SELECT id, name, source_language, target_language, created_at, updated_at, "
            "schema_version, active_profile_id, mode FROM projects "
            "WHERE active_profile_id = ? ORDER BY id",
            (profile_id,),
        )
        return [self._row_to_project(row) for row in cursor.fetchall()]

    def get_deletion_counts(self, project_id: int, *, now: str) -> ProjectDeletionCounts:
        """Return Project-owned row counts and active deletion blockers."""
        row = self._db.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM source_documents WHERE project_id = ?), "
            "(SELECT COUNT(*) FROM segments s "
            "JOIN source_documents d ON d.id = s.source_document_id "
            "WHERE d.project_id = ?), "
            "(SELECT COUNT(*) FROM translation_runs WHERE project_id = ?), "
            "(SELECT COUNT(*) FROM segment_attempts a "
            "JOIN translation_runs r ON r.id = a.run_id "
            "WHERE r.project_id = ?), "
            "(SELECT COUNT(*) FROM translation_revisions v "
            "JOIN segments s ON s.id = v.segment_id "
            "JOIN source_documents d ON d.id = s.source_document_id "
            "WHERE d.project_id = ?), "
            "(SELECT COUNT(*) FROM glossary_entries WHERE project_id = ?), "
            "(SELECT COUNT(*) FROM translation_runs "
            "WHERE project_id = ? AND status = 'running'), "
            "(SELECT COUNT(*) FROM segments s "
            "JOIN source_documents d ON d.id = s.source_document_id "
            "WHERE d.project_id = ? AND s.status = 'processing' "
            "AND s.lease_expires_at IS NOT NULL AND s.lease_expires_at > ?)",
            (
                project_id,
                project_id,
                project_id,
                project_id,
                project_id,
                project_id,
                project_id,
                project_id,
                now,
            ),
        ).fetchone()
        assert row is not None
        return {
            "source_documents": int(str(row[0])),
            "segments": int(str(row[1])),
            "translation_runs": int(str(row[2])),
            "segment_attempts": int(str(row[3])),
            "translation_revisions": int(str(row[4])),
            "glossary_entries": int(str(row[5])),
            "running_runs": int(str(row[6])),
            "active_processing_leases": int(str(row[7])),
        }

    def delete_project(self, project_id: int, *, now: str) -> bool:
        """Delete a Project atomically unless active work is observed."""
        with transaction(self._db):
            # Reserve the write transaction before checking blockers so a second
            # local writer cannot start a run between the check and the cascade.
            self._db.execute("BEGIN IMMEDIATE")
            blockers = self._db.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM translation_runs "
                "WHERE project_id = ? AND status = 'running'), "
                "(SELECT COUNT(*) FROM segments s "
                "JOIN source_documents d ON d.id = s.source_document_id "
                "WHERE d.project_id = ? AND s.status = 'processing' "
                "AND s.lease_expires_at IS NOT NULL AND s.lease_expires_at > ?)",
                (project_id, project_id, now),
            ).fetchone()
            assert blockers is not None
            if int(str(blockers[0])) or int(str(blockers[1])):
                return False

            cursor = self._db.execute(
                "DELETE FROM projects WHERE id = ?",
                (project_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_project(row: tuple[object, ...]) -> Project:
        active_profile_id = row[7]
        return Project(
            id=int(str(row[0])),
            name=str(row[1]),
            source_language=str(row[2]),
            target_language=str(row[3]),
            created_at=datetime.fromisoformat(str(row[4])),
            updated_at=datetime.fromisoformat(str(row[5])),
            schema_version=int(str(row[6])),
            active_profile_id=None if active_profile_id is None else int(str(active_profile_id)),
            mode=str(row[8]),
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
