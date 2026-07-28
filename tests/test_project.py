"""Tests for Project lifecycle API."""

from pathlib import Path

import pytest

from transrealm.application.project_service import ProjectService
from transrealm.domain.project import Project
from transrealm.infrastructure.repositories.project_repository import ProjectRepository


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "project.db"


def test_create_project_persists_metadata(db_path: Path) -> None:
    """Creating a project writes metadata to the database."""
    service = ProjectService(db_path, app_version="0.1.0")
    project = service.create_project(
        name="Test Project",
        source_language="zh",
        target_language="en",
    )
    assert project.id is not None
    assert project.name == "Test Project"
    assert project.source_language == "zh"
    assert project.target_language == "en"
    assert project.schema_version == 1
    service.close()


def test_open_project_loads_existing_project(db_path: Path) -> None:
    """Opening a database with a project loads it back."""
    service = ProjectService(db_path, app_version="0.1.0")
    created = service.create_project(
        name="Existing",
        source_language="ja",
        target_language="zh",
    )
    service.close()

    reopened = ProjectService(db_path, app_version="0.1.0")
    loaded = reopened.open_project()
    assert loaded is not None
    assert loaded.id == created.id
    assert loaded.name == "Existing"
    assert loaded.source_language == "ja"
    assert loaded.target_language == "zh"
    reopened.close()


def test_open_project_returns_none_for_empty_database(db_path: Path) -> None:
    """Opening a database without projects returns None."""
    service = ProjectService(db_path, app_version="0.1.0")
    assert service.open_project() is None
    service.close()


def test_save_project_updates_metadata(db_path: Path) -> None:
    """Saving a project updates its fields and updated_at."""
    service = ProjectService(db_path, app_version="0.1.0")
    project = service.create_project(
        name="Original",
        source_language="en",
        target_language="de",
    )
    original_updated_at = project.updated_at

    renamed = project.with_updated_name("Renamed")
    saved = service.save_project(renamed)
    assert saved.name == "Renamed"
    assert saved.updated_at is not None
    assert saved.updated_at != original_updated_at
    service.close()


def test_save_project_persists_changes_for_reopen(db_path: Path) -> None:
    """Saved changes survive closing and reopening the database."""
    service = ProjectService(db_path, app_version="0.1.0")
    project = service.create_project(
        name="Original",
        source_language="en",
        target_language="de",
    )
    service.save_project(project.with_updated_name("Renamed"))
    service.close()

    reopened = ProjectService(db_path, app_version="0.1.0")
    loaded = reopened.open_project()
    assert loaded is not None
    assert loaded.name == "Renamed"
    reopened.close()


def test_migrations_are_idempotent_on_reopen(db_path: Path) -> None:
    """Re-opening a database does not re-apply migrations or duplicate data."""
    service = ProjectService(db_path, app_version="0.1.0")
    service.create_project(name="P1", source_language="a", target_language="b")
    service.close()

    reopened = ProjectService(db_path, app_version="0.1.0")
    reopened.create_project(name="P2", source_language="c", target_language="d")
    projects = reopened._repository.list_all()  # noqa: SLF001
    assert len(projects) == 2
    reopened.close()


def test_repository_returns_none_for_missing_project(db_path: Path) -> None:
    """Repository returns None when a project id does not exist."""
    service = ProjectService(db_path, app_version="0.1.0")
    assert service._repository.get_by_id(999) is None  # noqa: SLF001
    service.close()


def test_project_repository_can_be_opened_directly(db_path: Path) -> None:
    """ProjectRepository can be opened after migrations have been applied."""
    service = ProjectService(db_path, app_version="0.1.0")
    service.close()

    repo = ProjectRepository.open(db_path)
    project = Project.create(name="Direct", source_language="x", target_language="y")
    saved = repo.save(project)
    assert saved.id is not None
    loaded = repo.get_by_id(saved.id)
    assert loaded is not None
    assert loaded.name == "Direct"
    repo.close()
