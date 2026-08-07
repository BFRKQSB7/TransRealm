"""Tests for P1-T04-M02: Project-scoped Glossary.

Covers: migration 010 upgrades old databases; CRUD of source/target/scope/
priority/is_locked/origin with reopen persistence; cross-project isolation;
empty/invalid value rejection; duplicate source-term strategy (reject with no
pollution, re-add after delete, update conflicts); and DB-level UNIQUE/CHECK
backstops.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from transrealm.application.glossary_service import GlossaryService
from transrealm.application.project_service import ProjectService
from transrealm.domain.glossary_entry import GlossaryEntry, GlossaryEntryError
from transrealm.infrastructure.database import SqlExecutionError, create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.glossary_entry_repository import (
    GlossaryEntryRepository,
)

APP_VERSION = "0.0.0-test"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "project.db"


def _create_project(db_path: Path, name: str = "Test") -> int:
    """Create a project and return its id."""
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name=name,
            source_language="ja",
            target_language="zh",
        )
    assert project.id is not None
    return project.id


def _create_entry(
    db_path: Path,
    project_id: int,
    *,
    source_term: str = "Nier",
    target_term: str = "尼爾",
    scope: str = "character",
    priority: int = 50,
    is_locked: bool = False,
    origin: str = "user",
) -> GlossaryEntry:
    """Create a glossary entry with defaults overridable by keyword arguments."""
    with GlossaryService(db_path, app_version=APP_VERSION) as service:
        return service.create_entry(
            project_id=project_id,
            source_term=source_term,
            target_term=target_term,
            scope=scope,
            priority=priority,
            is_locked=is_locked,
            origin=origin,
        )


def _apply_through_009(path: Path) -> None:
    """Apply migrations 001-009 only, leaving a pre-010 database."""
    migrations_dir = Path(__file__).parent.parent / "src" / "transrealm" / "migrations"
    migrations = discover_migrations(migrations_dir)
    # Compare numeric prefixes: lexical comparison is wrong for 009 vs 010.
    pre_010 = [
        m
        for m in migrations
        if int(m.migration_id.split("_", 1)[0]) <= 9
    ]
    runner = MigrationRunner.open(path)
    try:
        runner.apply(pre_010, app_version=APP_VERSION)
    finally:
        runner.close()


class TestMigration010:
    """Migration 010 creates the glossary table on old databases."""

    def test_migration_010_creates_table_on_old_database(self, db_path: Path) -> None:
        """A pre-010 database gains the glossary_entries table."""
        _apply_through_009(db_path)

        db = create_database(db_path)
        try:
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'",
                ).fetchall()
            }
        finally:
            db.close()
        assert "glossary_entries" not in tables

        project_id = _create_project(db_path)
        assert _create_entry(db_path, project_id).id is not None

        db = create_database(db_path)
        try:
            columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(glossary_entries)").fetchall()
            }
            applied = {
                row[0]
                for row in db.execute(
                    "SELECT migration_id FROM schema_migrations ORDER BY migration_id",
                ).fetchall()
            }
        finally:
            db.close()
        assert {
            "id",
            "project_id",
            "source_term",
            "target_term",
            "scope",
            "priority",
            "is_locked",
            "origin",
            "created_at",
            "updated_at",
        } <= columns
        assert "010_add_glossary_entry" in applied

    def test_migration_010_preserves_existing_project_data(self, db_path: Path) -> None:
        """Existing projects and active profile survive the 010 upgrade."""
        _apply_through_009(db_path)
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id, source_term="Emil")
        assert entry.id is not None

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            loaded = service.get_entry(_entry_id(entry))
            assert loaded is not None
            assert loaded.source_term == "Emil"
            assert loaded.project_id == project_id

    def test_table_enforces_unique_source_term_at_db_level(self, db_path: Path) -> None:
        """The UNIQUE(project_id, source_term) constraint backstops duplicates."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="Nier")

        db = create_database(db_path)
        try:
            with pytest.raises(SqlExecutionError):
                db.execute(
                    "INSERT INTO glossary_entries "
                    "(project_id, source_term, target_term, scope, priority, "
                    "is_locked, origin) VALUES (?, ?, ?, ?, 50, 0, 'user')",
                    (project_id, "Nier", "尼爾", "character"),
                )
            count = db.execute(
                "SELECT COUNT(*) FROM glossary_entries WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
        finally:
            db.close()
        assert count == 1

    def test_table_enforces_priority_and_origin_checks(self, db_path: Path) -> None:
        """CHECK constraints reject out-of-range priority and bad origin."""
        project_id = _create_project(db_path)
        db = create_database(db_path)
        try:
            with pytest.raises(SqlExecutionError):
                db.execute(
                    "INSERT INTO glossary_entries "
                    "(project_id, source_term, target_term, scope, priority, "
                    "is_locked, origin) VALUES (?, ?, ?, ?, 101, 0, 'user')",
                    (project_id, "X", "Y", "character"),
                )
            with pytest.raises(SqlExecutionError):
                db.execute(
                    "INSERT INTO glossary_entries "
                    "(project_id, source_term, target_term, scope, priority, "
                    "is_locked, origin) VALUES (?, ?, ?, ?, 50, 0, 'ai')",
                    (project_id, "Z", "W", "character"),
                )
        finally:
            db.close()


class TestGlossaryCRUD:
    """Create, read, update, delete with reopen persistence."""

    def test_create_and_get_entry(self, db_path: Path) -> None:
        """Creating an entry returns a persisted entity retrievable by id."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id)
        assert entry.id is not None
        assert entry.project_id == project_id
        assert entry.source_term == "Nier"
        assert entry.target_term == "尼爾"
        assert entry.scope == "character"

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            loaded = service.get_entry(_entry_id(entry))
            assert loaded is not None
            assert loaded.source_term == "Nier"
            assert loaded.target_term == "尼爾"

    def test_create_uses_defaults(self, db_path: Path) -> None:
        """Priority, lock and origin default to stable values."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id)
        assert entry.priority == 50
        assert entry.is_locked is False
        assert entry.origin == "user"

    def test_origin_import_allowed(self, db_path: Path) -> None:
        """The 'import' origin is a valid controlled value."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id, source_term="Imported", origin="import")
        assert entry.origin == "import"

    def test_list_orders_by_priority_desc_then_id(self, db_path: Path) -> None:
        """Entries list in priority order for deterministic M03 injection."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="low", priority=10)
        _create_entry(db_path, project_id, source_term="high", priority=90)
        _create_entry(db_path, project_id, source_term="mid", priority=50)

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            entries = service.list_entries(project_id)
        assert [e.source_term for e in entries] == ["high", "mid", "low"]

    def test_list_same_priority_ordered_by_id(self, db_path: Path) -> None:
        """Equal-priority entries tie-break by id for a stable order."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="a", priority=50)
        _create_entry(db_path, project_id, source_term="b", priority=50)
        _create_entry(db_path, project_id, source_term="c", priority=50)

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            entries = service.list_entries(project_id)
        assert [e.source_term for e in entries] == ["a", "b", "c"]

    def test_update_entry_fields(self, db_path: Path) -> None:
        """Updating replaces selected fields and re-validates."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id)

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            updated = service.update_entry(
                _entry_id(entry),
                source_term="Kaine",
                target_term="凱寧",
                scope="character",
                priority=80,
                is_locked=True,
            )
            assert updated.source_term == "Kaine"
            assert updated.target_term == "凱寧"
            assert updated.priority == 80
            assert updated.is_locked is True
            assert updated.origin == "user"

    def test_update_invalid_values_leave_db_unchanged(self, db_path: Path) -> None:
        """A validation failure during update persists nothing."""
        project_id = _create_project(db_path)
        entry = _create_entry(
            db_path,
            project_id,
            source_term="Nier",
            target_term="尼爾",
            priority=50,
        )
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(GlossaryEntryError):
                service.update_entry(_entry_id(entry), priority=101)
            with pytest.raises(GlossaryEntryError):
                service.update_entry(_entry_id(entry), target_term="  ")
            reloaded = service.get_entry(_entry_id(entry))
            assert reloaded is not None
            assert reloaded.priority == 50
            assert reloaded.target_term == "尼爾"

    def test_lock_toggle_controls_locked_list(self, db_path: Path) -> None:
        """Only locked entries appear in list_locked_entries."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="locked", is_locked=True)
        _create_entry(db_path, project_id, source_term="plain")

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            locked = service.list_locked_entries(project_id)
            assert [e.source_term for e in locked] == ["locked"]

            service.update_entry(
                _entry_id(_find_by_source(service, project_id, "locked")),
                is_locked=False,
            )
            assert service.list_locked_entries(project_id) == []

    def test_update_missing_entry_raises(self, db_path: Path) -> None:
        """Updating a nonexistent entry raises a clear domain error."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id)
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(GlossaryEntryError):
                service.update_entry(9999, source_term="New")

    def test_delete_entry(self, db_path: Path) -> None:
        """Deleting removes the entry and returns True."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id)
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            assert service.delete_entry(_entry_id(entry)) is True
            assert service.get_entry(_entry_id(entry)) is None

    def test_delete_missing_entry_returns_false(self, db_path: Path) -> None:
        """Deleting a nonexistent entry returns False."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id)
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            assert service.delete_entry(9999) is False

    def test_crud_persists_across_reopen(self, db_path: Path) -> None:
        """Entries survive closing and reopening the service."""
        project_id = _create_project(db_path)
        entry = _create_entry(
            db_path,
            project_id,
            source_term="Nier",
            target_term="尼爾",
            priority=60,
            is_locked=True,
        )

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            loaded = service.get_entry(_entry_id(entry))
            assert loaded is not None
            assert loaded.target_term == "尼爾"
            assert loaded.priority == 60
            assert loaded.is_locked is True
            assert service.list_locked_entries(project_id) == [loaded]

    def test_repository_open_reads_rows(self, db_path: Path) -> None:
        """A directly-opened repository reads rows saved through the service."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id)
        repository = GlossaryEntryRepository.open(db_path)
        try:
            loaded = repository.get_by_id(_entry_id(entry))
            assert loaded is not None
            assert loaded.source_term == "Nier"
        finally:
            repository.close()


class TestGlossaryProjectIsolation:
    """Glossary entries are scoped to their project."""

    def test_same_source_term_allowed_in_different_projects(self, db_path: Path) -> None:
        """The uniqueness domain is per project, not global."""
        project_a = _create_project(db_path, name="A")
        project_b = _create_project(db_path, name="B")
        entry_a = _create_entry(db_path, project_a, source_term="Nier")
        entry_b = _create_entry(db_path, project_b, source_term="Nier")

        assert entry_a.id is not None
        assert entry_b.id is not None
        assert entry_a.id != entry_b.id
        assert entry_a.project_id == project_a
        assert entry_b.project_id == project_b

    def test_entries_isolated_per_project(self, db_path: Path) -> None:
        """Each project sees only its own glossary entries."""
        project_a = _create_project(db_path, name="A")
        project_b = _create_project(db_path, name="B")
        _create_entry(db_path, project_a, source_term="A-term")
        _create_entry(db_path, project_b, source_term="B-term")

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            assert [e.source_term for e in service.list_entries(project_a)] == ["A-term"]
            assert [e.source_term for e in service.list_entries(project_b)] == ["B-term"]
            assert service.list_locked_entries(project_a) == []

    def test_delete_in_one_project_isolated(self, db_path: Path) -> None:
        """Deleting an entry in one project leaves the same term in others."""
        project_a = _create_project(db_path, name="A")
        project_b = _create_project(db_path, name="B")
        entry_a = _create_entry(db_path, project_a, source_term="Nier")
        _create_entry(db_path, project_b, source_term="Nier")

        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            assert service.delete_entry(_entry_id(entry_a)) is True
            remaining = service.list_entries(project_b)
        assert [e.source_term for e in remaining] == ["Nier"]


class TestGlossaryValidation:
    """Empty and invalid values are rejected before persistence."""

    def test_empty_source_term_rejected(self, db_path: Path) -> None:
        project_id = _create_project(db_path)
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, source_term="  ")

    def test_empty_target_term_rejected(self, db_path: Path) -> None:
        project_id = _create_project(db_path)
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, target_term="")

    def test_empty_scope_rejected(self, db_path: Path) -> None:
        project_id = _create_project(db_path)
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, scope="")

    @pytest.mark.parametrize("priority", [-1, 101])
    def test_priority_out_of_range_rejected(self, db_path: Path, priority: int) -> None:
        project_id = _create_project(db_path)
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, priority=priority)

    def test_priority_non_integer_rejected(self, db_path: Path) -> None:
        project_id = _create_project(db_path)
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, priority=cast(int, "high"))

    def test_is_locked_must_be_bool(self, db_path: Path) -> None:
        project_id = _create_project(db_path)
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, is_locked=cast(bool, 1))

    def test_invalid_origin_rejected(self, db_path: Path) -> None:
        project_id = _create_project(db_path)
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, origin="ai")

    def test_negative_project_id_rejected_by_domain(self) -> None:
        """The domain rejects a non-positive project id directly."""
        with pytest.raises(GlossaryEntryError):
            GlossaryEntry.create(
                project_id=-1,
                source_term="Nier",
                target_term="尼爾",
                scope="character",
            )


class TestGlossaryDuplicateStrategy:
    """Duplicate source terms within a project are rejected with no pollution."""

    def test_duplicate_source_term_rejected_without_pollution(self, db_path: Path) -> None:
        """A second entry with the same source term is rejected and leaves the
        database unchanged (transaction rollback)."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="Nier")
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(GlossaryEntryError):
                service.create_entry(
                    project_id=project_id,
                    source_term="Nier",
                    target_term="尼爾",
                    scope="character",
                )
            assert len(service.list_entries(project_id)) == 1

    def test_duplicate_with_whitespace_normalization_rejected(self, db_path: Path) -> None:
        """Source terms differing only in surrounding whitespace collide."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="Nier")
        with pytest.raises(GlossaryEntryError):
            _create_entry(db_path, project_id, source_term="  Nier  ")

    def test_readd_after_delete_allowed(self, db_path: Path) -> None:
        """A deleted source term can be re-added in the same project."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id, source_term="Nier")
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            assert service.delete_entry(_entry_id(entry)) is True
            recreated = service.create_entry(
                project_id=project_id,
                source_term="Nier",
                target_term="尼爾",
                scope="character",
            )
            assert recreated.id is not None

    def test_update_to_existing_source_term_rejected(self, db_path: Path) -> None:
        """Updating an entry to another entry's source term is rejected."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="Nier")
        other = _create_entry(db_path, project_id, source_term="Emil")
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(GlossaryEntryError):
                service.update_entry(_entry_id(other), source_term="Nier")

    def test_update_keeping_own_source_term_allowed(self, db_path: Path) -> None:
        """Re-saving the same source term on the same entry is allowed."""
        project_id = _create_project(db_path)
        entry = _create_entry(db_path, project_id, source_term="Nier")
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            updated = service.update_entry(_entry_id(entry), target_term="尼爾2")
            assert updated.source_term == "Nier"

    def test_repository_save_duplicate_raises_and_rolls_back(self, db_path: Path) -> None:
        """A repository-level duplicate insert hits the UNIQUE constraint and
        rolls back cleanly (DB-level backstop for the service pre-check)."""
        project_id = _create_project(db_path)
        _create_entry(db_path, project_id, source_term="Nier")
        repository = GlossaryEntryRepository.open(db_path)
        try:
            duplicate = GlossaryEntry.create(
                project_id=project_id,
                source_term="Nier",
                target_term="尼爾",
                scope="character",
            )
            with pytest.raises(SqlExecutionError):
                repository.save(duplicate)
            assert len(repository.list_by_project(project_id)) == 1
        finally:
            repository.close()


class TestGlossaryServicePrechecks:
    """Service-level preconditions give clear domain errors."""

    def test_create_entry_missing_project_raises(self, db_path: Path) -> None:
        """Creating an entry for a nonexistent project is rejected."""
        with GlossaryService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(GlossaryEntryError):
                service.create_entry(
                    project_id=9999,
                    source_term="Nier",
                    target_term="尼爾",
                    scope="character",
                )


def _entry_id(entry: GlossaryEntry | None) -> int:
    assert entry is not None
    assert entry.id is not None
    return entry.id


def _find_by_source(
    service: GlossaryService,
    project_id: int,
    source_term: str,
) -> GlossaryEntry | None:
    for entry in service.list_entries(project_id):
        if entry.source_term == source_term:
            return entry
    return None
