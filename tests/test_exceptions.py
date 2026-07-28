"""Exception-path tests for database, migrations, and Project service."""

from pathlib import Path

import pytest

from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.errors import PermissionDeniedError
from transrealm.infrastructure.migrations import (
    Migration,
    MigrationChecksumError,
    MigrationExecutionError,
    MigrationRunner,
    discover_migrations,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    """Return a temporary migrations directory."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


def test_failed_migration_does_not_record_history(db_path: Path, migrations_dir: Path) -> None:
    """A failed migration leaves no entry in schema_migrations."""
    path = migrations_dir / "001_broken.sql"
    path.write_text(
        "CREATE TABLE items (id INTEGER PRIMARY KEY); INVALID SQL;",
        encoding="utf-8",
    )
    migration = Migration.from_file(path)

    db = create_database(db_path)
    runner = MigrationRunner(db)
    with pytest.raises(MigrationExecutionError):
        runner.apply([migration], app_version="0.1.0")

    history = runner.history()
    assert history == []
    db.close()


def test_checksum_error_includes_migration_id(db_path: Path, migrations_dir: Path) -> None:
    """Checksum mismatch reports the offending migration id."""
    path = migrations_dir / "001_init.sql"
    path.write_text("SELECT 1;", encoding="utf-8")

    run_migrations_once = discover_migrations(migrations_dir)
    db = create_database(db_path)
    runner = MigrationRunner(db)
    runner.apply(run_migrations_once, app_version="0.1.0")

    path.write_text("SELECT 2;", encoding="utf-8")
    run_migrations_twice = discover_migrations(migrations_dir)
    with pytest.raises(MigrationChecksumError) as exc_info:
        runner.apply(run_migrations_twice, app_version="0.1.0")
    assert "001_init" in str(exc_info.value)
    db.close()


def test_project_service_rejects_readonly_database(db_path: Path) -> None:
    """Creating a project on a read-only database path raises PermissionDeniedError."""
    db_path.write_bytes(b"")
    db_path.chmod(0o444)
    try:
        with pytest.raises(PermissionDeniedError):
            ProjectService(db_path, app_version="0.1.0")
    finally:
        db_path.chmod(0o666)


def test_project_service_supports_unicode_path(tmp_path: Path) -> None:
    """A project can be created at a Unicode path."""
    db_path = tmp_path / "译境项目.db"
    service = ProjectService(db_path, app_version="0.1.0")
    project = service.create_project(name="中文", source_language="zh", target_language="en")
    assert project.id is not None
    service.close()


@pytest.mark.skipif("os.name != 'nt'", reason="Windows-specific long-path test")
def test_project_service_supports_long_path(tmp_path: Path) -> None:
    """A project can be created at a very long Windows path."""
    deep = tmp_path
    for segment in ["a" * 40] * 8:
        deep = deep / segment
    deep.mkdir(parents=True, exist_ok=True)
    db_path = deep / "project.db"

    service = ProjectService(db_path, app_version="0.1.0")
    project = service.create_project(name="LongPath", source_language="a", target_language="b")
    assert project.id is not None
    service.close()

    reopened = ProjectService(db_path, app_version="0.1.0")
    loaded = reopened.open_project()
    assert loaded is not None
    assert loaded.name == "LongPath"
    reopened.close()


def test_project_save_missing_id_is_noop(db_path: Path) -> None:
    """Saving a project with a non-existent id does not corrupt the database."""
    from transrealm.domain.project import Project
    from transrealm.infrastructure.repositories.project_repository import ProjectRepository

    service = ProjectService(db_path, app_version="0.1.0")
    service.create_project(name="Original", source_language="en", target_language="de")
    service.close()

    db = create_database(db_path)
    repo = ProjectRepository(db)
    bogus = Project(
        id=999,
        name="Bogus",
        source_language="x",
        target_language="y",
        created_at=None,
        updated_at=None,
        schema_version=1,
    )
    repo.save(bogus)
    repo.close()

    reopened = ProjectService(db_path, app_version="0.1.0")
    loaded = reopened.open_project()
    assert loaded is not None
    assert loaded.name == "Original"
    reopened.close()


def test_database_rejects_unicode_path_parent_missing(tmp_path: Path) -> None:
    """Opening a database under a missing Unicode parent directory raises an error."""
    from transrealm.infrastructure.errors import ConnectionError

    db_path = tmp_path / "缺失目录" / "test.db"
    with pytest.raises(ConnectionError):
        create_database(db_path)
