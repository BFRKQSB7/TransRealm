"""Translation run domain model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from transrealm.domain.translation_workflow import compute_definition_hash


class TranslationRunError(ValueError):
    """Invalid translation run state or configuration."""


@dataclass
class TranslationRun:
    """A single execution of a workflow against a project."""

    id: int | None
    project_id: int
    workflow_id: int
    workflow_version: str
    workflow_definition_hash: str
    workflow_definition_snapshot: str | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        project_id: int,
        workflow_id: int,
        workflow_version: str,
        workflow_definition_hash: str,
        workflow_definition_snapshot: str,
    ) -> TranslationRun:
        """Create a new, unsaved translation run."""
        instance = cls(
            id=None,
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_definition_hash=workflow_definition_hash,
            workflow_definition_snapshot=workflow_definition_snapshot,
            status="running",
            started_at=None,
            finished_at=None,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate fields and raise TranslationRunError on failure."""
        if not isinstance(self.project_id, int) or self.project_id <= 0:
            raise TranslationRunError("project_id must be a positive integer.")

        if not isinstance(self.workflow_id, int) or self.workflow_id <= 0:
            raise TranslationRunError("workflow_id must be a positive integer.")

        if not self.workflow_version or not self.workflow_version.strip():
            raise TranslationRunError("workflow_version is required.")

        if not self.workflow_definition_hash or not self.workflow_definition_hash.strip():
            raise TranslationRunError("workflow_definition_hash is required.")

        if self.workflow_definition_snapshot is not None:
            try:
                definition = json.loads(self.workflow_definition_snapshot)
            except json.JSONDecodeError as exc:
                raise TranslationRunError(
                    "workflow_definition_snapshot must be valid JSON.",
                ) from exc
            if not isinstance(definition, dict):
                raise TranslationRunError("workflow_definition_snapshot must be a JSON object.")
            if compute_definition_hash(definition) != self.workflow_definition_hash:
                raise TranslationRunError(
                    "workflow_definition_snapshot hash does not match workflow_definition_hash.",
                )

        if self.status not in {"running", "completed", "failed", "cancelled"}:
            raise TranslationRunError(f"Invalid run status: {self.status!r}")
