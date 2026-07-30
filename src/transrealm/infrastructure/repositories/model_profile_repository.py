"""SQLite-backed repository for ModelProfile entities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from transrealm.domain.model_profile import ModelProfile
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class ModelProfileRepository:
    """SQLite-backed repository for ModelProfile entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> ModelProfileRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def save(self, profile: ModelProfile) -> ModelProfile:
        """Insert or update a profile and return the persisted entity."""
        now = datetime.now().isoformat()
        if profile.id is None:
            with transaction(self._db):
                cursor = self._db.execute(
                    "INSERT INTO model_profiles "
                    "(name, provider_connection_id, model_id, template_version, "
                    "output_protocol, context_budget, default_params, capability_snapshot, "
                    "created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        profile.name,
                        profile.provider_connection_id,
                        profile.model_id,
                        profile.template_version,
                        profile.output_protocol,
                        json.dumps(profile.context_budget),
                        json.dumps(profile.default_params),
                        json.dumps(profile.capability_snapshot),
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
                "UPDATE model_profiles SET name = ?, provider_connection_id = ?, "
                "model_id = ?, template_version = ?, output_protocol = ?, "
                "context_budget = ?, default_params = ?, capability_snapshot = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    profile.name,
                    profile.provider_connection_id,
                    profile.model_id,
                    profile.template_version,
                    profile.output_protocol,
                    json.dumps(profile.context_budget),
                    json.dumps(profile.default_params),
                    json.dumps(profile.capability_snapshot),
                    now,
                    profile.id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"ModelProfile with id {profile.id} does not exist.")
        loaded = self.get_by_id(profile.id)
        assert loaded is not None
        return loaded

    def get_by_id(self, profile_id: int) -> ModelProfile | None:
        """Fetch a profile by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, name, provider_connection_id, model_id, template_version, "
            "output_protocol, context_budget, default_params, capability_snapshot, "
            "created_at, updated_at FROM model_profiles WHERE id = ?",
            (profile_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    def list_all(self) -> list[ModelProfile]:
        """Return all profiles ordered by id."""
        cursor = self._db.execute(
            "SELECT id, name, provider_connection_id, model_id, template_version, "
            "output_protocol, context_budget, default_params, capability_snapshot, "
            "created_at, updated_at FROM model_profiles ORDER BY id",
        )
        return [self._row_to_profile(row) for row in cursor.fetchall()]

    def list_by_connection(self, connection_id: int) -> list[ModelProfile]:
        """Return all profiles referencing a given ProviderConnection."""
        cursor = self._db.execute(
            "SELECT id, name, provider_connection_id, model_id, template_version, "
            "output_protocol, context_budget, default_params, capability_snapshot, "
            "created_at, updated_at FROM model_profiles "
            "WHERE provider_connection_id = ? ORDER BY id",
            (connection_id,),
        )
        return [self._row_to_profile(row) for row in cursor.fetchall()]

    def delete(self, profile_id: int) -> bool:
        """Delete a profile by id. Returns True if a row was removed."""
        with transaction(self._db):
            cursor = self._db.execute(
                "DELETE FROM model_profiles WHERE id = ?",
                (profile_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_profile(row: tuple[object, ...]) -> ModelProfile:
        return ModelProfile(
            id=int(str(row[0])),
            name=str(row[1]),
            provider_connection_id=int(str(row[2])),
            model_id=str(row[3]),
            template_version=str(row[4]),
            output_protocol=str(row[5]),
            context_budget=json.loads(str(row[6])),
            default_params=json.loads(str(row[7])),
            capability_snapshot=json.loads(str(row[8])),
            created_at=datetime.fromisoformat(str(row[9])),
            updated_at=datetime.fromisoformat(str(row[10])),
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
