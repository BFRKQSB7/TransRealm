"""SQLite-backed repository for WorkflowDefinition entities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from transrealm.domain.translation_workflow import (
    WorkflowDefinition,
    WorkflowDefinitionError,
)
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class WorkflowDefinitionRepository:
    """SQLite-backed repository for WorkflowDefinition entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> WorkflowDefinitionRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        """Insert a new workflow definition and return the persisted entity.

        Updates of existing built-in workflows are rejected at the domain
        level; the repository raises WorkflowDefinitionError for read-only
        conflicts.
        """
        now = datetime.now().isoformat()
        with transaction(self._db):
            if workflow.id is not None:
                existing = self._fetch_row(workflow.id)
                if existing is not None and existing.is_read_only:
                    raise WorkflowDefinitionError(
                        f"Built-in workflow {workflow.name} is read-only.",
                    )
                cursor = self._db.execute(
                    "UPDATE workflow_definitions SET name = ?, origin = ?, "
                    "parent_workflow_id = ?, version = ?, definition_json = ?, "
                    "definition_hash = ?, is_read_only = ? WHERE id = ?",
                    (
                        workflow.name,
                        workflow.origin,
                        workflow.parent_workflow_id,
                        workflow.version,
                        json.dumps(workflow.definition_json),
                        workflow.definition_hash,
                        1 if workflow.is_read_only else 0,
                        workflow.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise WorkflowDefinitionError(
                        f"WorkflowDefinition with id {workflow.id} does not exist.",
                    )
                loaded = self.get_by_id(workflow.id)
                assert loaded is not None
                return loaded

            cursor = self._db.execute(
                "INSERT INTO workflow_definitions "
                "(name, origin, parent_workflow_id, version, definition_json, "
                "definition_hash, is_read_only, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workflow.name,
                    workflow.origin,
                    workflow.parent_workflow_id,
                    workflow.version,
                    json.dumps(workflow.definition_json),
                    workflow.definition_hash,
                    1 if workflow.is_read_only else 0,
                    now,
                ),
            )
            new_id = cursor.lastrowid
        assert new_id is not None
        loaded = self.get_by_id(new_id)
        assert loaded is not None
        return loaded

    def _fetch_row(self, workflow_id: int) -> WorkflowDefinition | None:
        return self.get_by_id(workflow_id)

    def get_by_id(self, workflow_id: int) -> WorkflowDefinition | None:
        """Fetch a workflow by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, name, origin, parent_workflow_id, version, definition_json, "
            "definition_hash, is_read_only, created_at FROM workflow_definitions WHERE id = ?",
            (workflow_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_workflow(row)

    def get_by_name(self, name: str) -> WorkflowDefinition | None:
        """Fetch the most recent workflow by name, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, name, origin, parent_workflow_id, version, definition_json, "
            "definition_hash, is_read_only, created_at FROM workflow_definitions "
            "WHERE name = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_workflow(row)

    def get_by_name_and_version(self, name: str, version: str) -> WorkflowDefinition | None:
        """Fetch a workflow by name and version, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, name, origin, parent_workflow_id, version, definition_json, "
            "definition_hash, is_read_only, created_at FROM workflow_definitions "
            "WHERE name = ? AND version = ?",
            (name, version),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_workflow(row)

    def list_all(self) -> list[WorkflowDefinition]:
        """Return all workflows ordered by id."""
        cursor = self._db.execute(
            "SELECT id, name, origin, parent_workflow_id, version, definition_json, "
            "definition_hash, is_read_only, created_at FROM workflow_definitions ORDER BY id",
        )
        return [self._row_to_workflow(row) for row in cursor.fetchall()]

    def delete(self, workflow_id: int) -> bool:
        """Delete a workflow by id. Returns True if a row was removed."""
        with transaction(self._db):
            cursor = self._db.execute(
                "DELETE FROM workflow_definitions WHERE id = ?",
                (workflow_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_workflow(row: tuple[object, ...]) -> WorkflowDefinition:
        return WorkflowDefinition(
            id=int(str(row[0])),
            name=str(row[1]),
            origin=str(row[2]),
            parent_workflow_id=int(str(row[3])) if row[3] is not None else None,
            version=str(row[4]),
            definition_json=json.loads(str(row[5])),
            definition_hash=str(row[6]),
            is_read_only=bool(row[7]),
            created_at=datetime.fromisoformat(str(row[8])),
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
