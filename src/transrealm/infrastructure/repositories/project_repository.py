"""Project repository implementation."""

from datetime import datetime
from pathlib import Path

from transrealm.domain.project import Project
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


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
