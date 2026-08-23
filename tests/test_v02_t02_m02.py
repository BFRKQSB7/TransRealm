"""V02-T02-M02 acceptance for recoverable Project deletion."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from transrealm.application import project_service as project_service_module
from transrealm.application.project_service import (
    ProjectDeletionBlockedError,
    ProjectService,
)
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.migrations.errors import MigrationBackupError

APP_VERSION = "0.2.0"


def _create_project(db_path: Path, name: str) -> int:
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name=name,
            source_language="en",
            target_language="zh-CN",
        )
    assert project.id is not None
    return project.id


def _seed_project_data(
    db_path: Path,
    project_id: int,
    *,
    run_status: str = "completed",
    lease_expires_at: str | None = None,
) -> None:
    db = create_database(db_path)
    try:
        with transaction(db):
            workflow = db.execute(
                "INSERT INTO workflow_definitions "
                "(name, origin, version, definition_json, definition_hash) "
                "VALUES (?, 'builtin', ?, ?, ?)",
                (f"workflow-{project_id}", "1.0", "{}", f"hash-{project_id}"),
            )
            workflow_id = workflow.lastrowid
            assert workflow_id is not None
            run = db.execute(
                "INSERT INTO translation_runs "
                "(project_id, workflow_id, workflow_version, workflow_definition_hash, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, workflow_id, "1.0", f"hash-{project_id}", run_status),
            )
            assert run.lastrowid is not None
            document = db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, ?, 'txt', 'utf-8', ?, '1.0.0')",
                (project_id, f"source-{project_id}.txt", f"source-hash-{project_id}"),
            )
            document_id = document.lastrowid
            assert document_id is not None
            db.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence, status, "
                "lease_owner, lease_expires_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
                (
                    document_id,
                    f"segment-{project_id}",
                    "Hello",
                    "processing" if lease_expires_at is not None else "completed",
                    "worker" if lease_expires_at is not None else None,
                    lease_expires_at,
                ),
            )
            db.execute(
                "INSERT INTO glossary_entries "
                "(project_id, source_term, target_term, scope, origin) "
                "VALUES (?, 'Hello', '你好', 'general', 'user')",
                (project_id,),
            )
    finally:
        db.close()


def _delete_backups(db_path: Path) -> list[Path]:
    return sorted(db_path.parent.glob(f"{db_path.stem}.project-delete-*.db.bak"))


def _project_exists(db_path: Path, project_id: int) -> bool:
    db = create_database(db_path)
    try:
        row = db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        return row is not None
    finally:
        db.close()


def test_delete_project_creates_recoverable_backup_and_preserves_other_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _create_project(db_path, "Delete me")
    other_id = _create_project(db_path, "Keep me")
    _seed_project_data(db_path, project_id)
    source_file = tmp_path / "outside-source.txt"
    export_file = tmp_path / "outside-export.txt"
    source_file.write_text("source", encoding="utf-8")
    export_file.write_text("export", encoding="utf-8")

    with ProjectService(db_path, app_version=APP_VERSION) as service:
        summary = service.get_project_deletion_summary(project_id)
        backup_path = service.delete_project(project_id)

    assert summary.project_name == "Delete me"
    assert summary.source_documents == 1
    assert summary.segments == 1
    assert summary.translation_runs == 1
    assert summary.glossary_entries == 1
    assert backup_path is not None and backup_path.exists()
    assert _delete_backups(db_path) == [backup_path]
    assert not _project_exists(db_path, project_id)
    assert _project_exists(db_path, other_id)
    assert source_file.read_text(encoding="utf-8") == "source"
    assert export_file.read_text(encoding="utf-8") == "export"

    with sqlite3.connect(backup_path) as backup:
        assert backup.execute(
            "SELECT name FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is not None
        assert backup.execute(
            "SELECT COUNT(*) FROM source_documents WHERE project_id = ?", (project_id,)
        ).fetchone() == (1,)
        assert backup.execute(
            "SELECT COUNT(*) FROM glossary_entries WHERE project_id = ?", (project_id,)
        ).fetchone() == (1,)


def test_delete_missing_project_is_noop_without_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    _create_project(db_path, "Existing")

    with ProjectService(db_path, app_version=APP_VERSION) as service:
        assert service.delete_project(99999) is None

    assert _delete_backups(db_path) == []


def test_backup_failure_blocks_delete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _create_project(db_path, "Backup failure")

    def fail_backup(*args: object, **kwargs: object) -> Path:
        raise MigrationBackupError("forced backup failure", path=db_path)

    monkeypatch.setattr(project_service_module, "create_consistent_snapshot", fail_backup)
    with ProjectService(db_path, app_version=APP_VERSION) as service:
        with pytest.raises(MigrationBackupError, match="forced backup failure"):
            service.delete_project(project_id)

    assert _project_exists(db_path, project_id)
    assert _delete_backups(db_path) == []


def test_running_run_blocks_delete_without_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _create_project(db_path, "Running")
    _seed_project_data(db_path, project_id, run_status="running")

    with ProjectService(db_path, app_version=APP_VERSION) as service:
        with pytest.raises(ProjectDeletionBlockedError, match="running"):
            service.delete_project(project_id)

    assert _project_exists(db_path, project_id)
    assert _delete_backups(db_path) == []


def test_active_processing_lease_blocks_delete_without_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _create_project(db_path, "Leased")
    lease = (datetime.now() + timedelta(minutes=5)).isoformat()
    _seed_project_data(db_path, project_id, lease_expires_at=lease)

    with ProjectService(db_path, app_version=APP_VERSION) as service:
        with pytest.raises(ProjectDeletionBlockedError, match="lease"):
            service.delete_project(project_id)

    assert _project_exists(db_path, project_id)
    assert _delete_backups(db_path) == []


def test_expired_processing_lease_does_not_block_delete(tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _create_project(db_path, "Expired lease")
    lease = (datetime.now() - timedelta(minutes=5)).isoformat()
    _seed_project_data(db_path, project_id, lease_expires_at=lease)

    with ProjectService(db_path, app_version=APP_VERSION) as service:
        backup_path = service.delete_project(project_id)

    assert backup_path is not None and backup_path.exists()
    assert not _project_exists(db_path, project_id)


def test_delete_transaction_failure_rolls_back_and_keeps_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _create_project(db_path, "Transaction failure")
    _seed_project_data(db_path, project_id)

    with ProjectService(db_path, app_version=APP_VERSION) as service:
        original_execute = service._repository._db.execute

        def fail_delete(sql: str, parameters: tuple[object, ...] | None = None):
            if sql.strip().upper().startswith("DELETE FROM PROJECTS"):
                raise RuntimeError("forced delete failure")
            return original_execute(sql, parameters)

        monkeypatch.setattr(service._repository._db, "execute", fail_delete)
        with pytest.raises(RuntimeError, match="forced delete failure"):
            service.delete_project(project_id)

    assert _project_exists(db_path, project_id)
    backups = _delete_backups(db_path)
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is not None
