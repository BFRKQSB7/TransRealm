"""Workflow definition domain model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime


class WorkflowDefinitionError(ValueError):
    """Invalid workflow definition configuration."""


@dataclass
class WorkflowDefinition:
    """A versioned, read-only aware workflow definition."""

    id: int | None
    name: str
    origin: str
    parent_workflow_id: int | None
    version: str
    definition_json: dict[str, object]
    definition_hash: str
    is_read_only: bool
    created_at: datetime | None

    @classmethod
    def create_builtin(
        cls,
        *,
        name: str,
        version: str,
        definition: dict[str, object],
        parent_workflow_id: int | None = None,
    ) -> WorkflowDefinition:
        """Create a built-in workflow definition with a computed hash."""
        instance = cls(
            id=None,
            name=name,
            origin="builtin",
            parent_workflow_id=parent_workflow_id,
            version=version,
            definition_json=definition,
            definition_hash=compute_definition_hash(definition),
            is_read_only=True,
            created_at=None,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate fields and raise WorkflowDefinitionError on failure."""
        if not self.name or not self.name.strip():
            raise WorkflowDefinitionError("Workflow name is required.")

        if self.origin not in {"builtin", "user"}:
            raise WorkflowDefinitionError(
                f"Workflow origin must be 'builtin' or 'user': {self.origin!r}",
            )

        if not self.version or not self.version.strip():
            raise WorkflowDefinitionError("Workflow version is required.")

        if not isinstance(self.definition_json, dict):
            raise WorkflowDefinitionError("Workflow definition must be a JSON object.")

        try:
            canonical_definition_json(self.definition_json)
        except TypeError as exc:
            raise WorkflowDefinitionError(
                f"Workflow definition is not JSON-serializable: {exc}",
            ) from exc

        expected_hash = compute_definition_hash(self.definition_json)
        if self.definition_hash != expected_hash:
            raise WorkflowDefinitionError(
                "Workflow definition hash does not match computed hash: "
                f"expected {expected_hash}, got {self.definition_hash}",
            )

        if self.origin == "builtin" and not self.is_read_only:
            raise WorkflowDefinitionError(
                "Built-in workflow definitions must be read-only.",
            )


def canonical_definition_json(definition: dict[str, object]) -> str:
    """Return a canonical JSON string for hash computation.

    Keys are sorted and separators are compact so that equivalent dicts
    produce the same hash regardless of insertion order or whitespace.
    """
    return json.dumps(definition, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_definition_hash(definition: dict[str, object]) -> str:
    """Compute the SHA-256 hash of a canonical workflow definition."""
    canonical = canonical_definition_json(definition)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
