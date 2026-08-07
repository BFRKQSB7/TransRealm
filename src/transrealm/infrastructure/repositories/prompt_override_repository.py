"""SQLite-backed repository for PromptOverride entities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from transrealm.domain.prompt_override import PromptOverride
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class PromptOverrideRepository:
    """SQLite-backed repository for PromptOverride entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> PromptOverrideRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, override: PromptOverride) -> PromptOverride:
        """Insert or update the override for the profile and return it.

        A profile has at most one override (UNIQUE on model_profile_id), so an
        existing row for the profile is updated rather than duplicated.
        """
        now = datetime.now().isoformat()
        existing = self.get_by_profile(override.model_profile_id)
        if existing is not None and existing.id is not None:
            with transaction(self._db):
                self._db.execute(
                    "UPDATE prompt_overrides SET parent_template_version = ?, "
                    "template_text = ?, updated_at = ? WHERE id = ?",
                    (
                        override.parent_template_version,
                        override.template_text,
                        now,
                        existing.id,
                    ),
                )
            loaded = self.get_by_profile(override.model_profile_id)
            assert loaded is not None
            return loaded

        with transaction(self._db):
            cursor = self._db.execute(
                "INSERT INTO prompt_overrides "
                "(model_profile_id, parent_template_version, template_text, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    override.model_profile_id,
                    override.parent_template_version,
                    override.template_text,
                    now,
                    now,
                ),
            )
            new_id = cursor.lastrowid
        assert new_id is not None
        loaded = self.get_by_profile(override.model_profile_id)
        assert loaded is not None
        return loaded

    def get_by_profile(self, profile_id: int) -> PromptOverride | None:
        """Fetch the override for a profile, or None if there is none."""
        cursor = self._db.execute(
            "SELECT id, model_profile_id, parent_template_version, template_text, "
            "created_at, updated_at FROM prompt_overrides "
            "WHERE model_profile_id = ?",
            (profile_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return PromptOverride(
            id=int(str(row[0])),
            model_profile_id=int(str(row[1])),
            parent_template_version=str(row[2]),
            template_text=str(row[3]),
            created_at=datetime.fromisoformat(str(row[4])),
            updated_at=datetime.fromisoformat(str(row[5])),
        )

    def delete_by_profile(self, profile_id: int) -> bool:
        """Delete the override for a profile. Returns True if a row was removed."""
        with transaction(self._db):
            cursor = self._db.execute(
                "DELETE FROM prompt_overrides WHERE model_profile_id = ?",
                (profile_id,),
            )
            return cursor.rowcount > 0

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
