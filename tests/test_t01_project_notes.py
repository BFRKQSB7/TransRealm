"""T01: persisted Notes, upgrade safety and translation audit behavior."""

from __future__ import annotations

import hashlib
import sqlite3
import string
import zipfile
from pathlib import Path

import pytest

from test_p1_t04_m03 import (
    APP_VERSION,
    FakeAdapter,
    _create_profile,
    _create_project,
    _import_txt,
    _run,
    _valid_response,
)
from transrealm.application.archive_service import (
    export_database_archive,
    export_open_directory_archive,
)
from transrealm.application.context import ContextBudget, ContextSource, EstimateMethod
from transrealm.application.context_composer import ContextBudgetError, ContextComposer
from transrealm.application.open_directory_service import create_open_directory_project
from transrealm.application.project_notes_service import ProjectNotesService
from transrealm.application.project_service import ProjectService
from transrealm.application.prompt_renderer import PromptRenderer
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.translation_service import TranslationService
from transrealm.domain.segment import Segment
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.migrations import Migration, MigrationRunner, discover_migrations
from transrealm.infrastructure.migrations.errors import MigrationExecutionError
from transrealm.infrastructure.open_directory import regenerate_manifest

MIGRATIONS = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"


def test_real_upgrade_preserves_rows_backup_fk_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    db = create_database(path)
    runner = MigrationRunner(db)
    migrations = discover_migrations(MIGRATIONS)
    assert [m.migration_id[:3] for m in migrations] == [f"{n:03}" for n in range(1, 14)]
    runner.apply(migrations[:12], app_version=APP_VERSION)
    with transaction(db):
        db.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('Existing', 'ja', 'zh')"
        )
    applied = runner.apply(migrations, app_version=APP_VERSION)
    assert [m.migration_id for m in applied] == ["013_add_project_notes"]
    backup = runner.last_backup_path
    assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as old:
        assert old.execute("SELECT name FROM projects").fetchone() == ("Existing",)
        assert old.execute(
            "SELECT name FROM sqlite_master WHERE name = 'project_notes'"
        ).fetchone() is None
        assert old.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()
    with ProjectNotesService(path, app_version=APP_VERSION) as notes:
        assert notes.get_notes(1) == ""
        notes.set_notes(1, "Keep the name unchanged")
    with ProjectNotesService(path, app_version=APP_VERSION) as notes:
        assert notes.get_notes(1) == "Keep the name unchanged"


def test_failed_additive_migration_rolls_back_and_keeps_backup(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    db = create_database(path)
    runner = MigrationRunner(db)
    runner.apply(discover_migrations(MIGRATIONS)[:12], app_version=APP_VERSION)
    with transaction(db):
        db.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('Existing', 'ja', 'zh')"
        )
    bad_file = tmp_path / "013_broken.sql"
    bad_file.write_text(
        "CREATE TABLE project_notes (project_id INTEGER); INVALID SQL;", encoding="utf-8"
    )
    with pytest.raises(MigrationExecutionError):
        runner.apply([Migration.from_file(bad_file)], app_version=APP_VERSION)
    assert runner.last_backup_path is not None and runner.last_backup_path.is_file()
    assert db.execute("SELECT name FROM projects").fetchone() == ("Existing",)
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE name = 'project_notes'"
    ).fetchone() is None
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_notes_lifecycle_scope_clear_and_delete_cascade(tmp_path: Path) -> None:
    path = tmp_path / "project.sqlite"
    first = _create_project(path, "A")
    second = _create_project(path, "B")
    with ProjectNotesService(path, app_version=APP_VERSION) as notes:
        assert notes.get_notes(first) == ""
        assert notes.set_notes(first, " Use formal terms. ") == " Use formal terms. "
        notes.set_notes(second, "Keep brand names")
        notes.set_notes(first, "Replace guidance")
        assert notes.get_notes(first) == "Replace guidance"
        notes.set_notes(first, "  \n")
        assert notes.get_notes(first) == ""
        with pytest.raises(ValueError, match="does not exist"):
            notes.set_notes(9999, "No project")
    with ProjectNotesService(path, app_version=APP_VERSION) as notes:
        assert notes.get_notes(first) == ""
        assert notes.get_notes(second) == "Keep brand names"
        notes.set_notes(first, "Recoverable data")
    with ProjectService(path, app_version=APP_VERSION) as projects:
        backup = projects.delete_project(first)
        assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as old:
        assert old.execute(
            "SELECT content FROM project_notes WHERE project_id = ?", (first,)
        ).fetchone() == ("Recoverable data",)
    with ProjectNotesService(path, app_version=APP_VERSION) as notes:
        with pytest.raises(ValueError, match="does not exist"):
            notes.get_notes(first)
        assert notes.get_notes(second) == "Keep brand names"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM project_notes").fetchone() == (1,)


def test_notes_survive_archive_and_open_directory_snapshot(tmp_path: Path) -> None:
    bare_db = tmp_path / "bare.sqlite"
    project_id = _create_project(bare_db, "A")
    with ProjectNotesService(bare_db, app_version=APP_VERSION) as notes:
        notes.set_notes(project_id, "Archive guidance")
    bare_archive = export_database_archive(
        bare_db, tmp_path / "bare.aiproject", app_version=APP_VERSION,
    )
    extracted = tmp_path / "bare-extracted"
    with zipfile.ZipFile(bare_archive) as archive:
        archive.extractall(extracted)
    with sqlite3.connect(extracted / "project.sqlite") as db:
        assert db.execute("SELECT content FROM project_notes").fetchone() == (
            "Archive guidance",
        )

    directory = tmp_path / "open-project"
    with create_open_directory_project(
        directory, name="B", source_language="ja", target_language="zh",
        app_version=APP_VERSION,
    ):
        pass
    with ProjectNotesService(directory / "project.sqlite", app_version=APP_VERSION) as notes:
        notes.set_notes(1, "Open directory guidance")
    regenerate_manifest(directory, schema_version=1)
    open_archive = export_open_directory_archive(
        directory, tmp_path / "open.aiproject", app_version=APP_VERSION,
    )
    extracted_open = tmp_path / "open-extracted"
    with zipfile.ZipFile(open_archive) as archive:
        archive.extractall(extracted_open)
    with sqlite3.connect(extracted_open / "project.sqlite") as db:
        assert db.execute("SELECT content FROM project_notes").fetchone() == (
            "Open directory guidance",
        )


def test_notes_are_protected_and_far_neighbor_is_pruned() -> None:
    current = Segment.create(source_document_id=1, stable_key="target", source_text="A", sequence=1)
    neighbor = Segment.create(
        source_document_id=1, stable_key="neighbor", source_text="B", sequence=2
    )
    budget = ContextBudget(7, 1, 1, EstimateMethod.CHARACTER)
    composer = ContextComposer()
    manifest = composer.compose(
        profile_id="p", template_version="v", current=current,
        neighbors=[neighbor], notes="Note", budget=budget,
    )
    assert [c.source for c in manifest.selected] == [
        ContextSource.CURRENT_SEGMENT, ContextSource.JOB_NOTES,
    ]
    assert [c.source for c in manifest.pruned] == [ContextSource.NEIGHBOR_SEGMENT]
    rendered = PromptRenderer().render(profile_id="p", template_version="v", manifest=manifest)
    assert "Job Notes:\nNote" in rendered.prompt_text
    empty_manifest = composer.compose(
        profile_id="p", template_version="v", current=current, notes="", budget=budget,
    )
    empty_prompt = PromptRenderer().render(
        profile_id="p", template_version="v", manifest=empty_manifest,
    )
    assert "Job Notes:" not in empty_prompt.prompt_text
    assert all(c.source != ContextSource.JOB_NOTES for c in empty_manifest.candidates)
    custom = PromptRenderer().render(
        profile_id="p", template_version="v", manifest=manifest,
        template=string.Template("Translate $current with $notes"),
    )
    assert "Translate A with Note" in custom.prompt_text
    assert custom.prompt_text.count("Note") == 1
    with pytest.raises(ContextBudgetError):
        composer.compose(
            profile_id="p", template_version="v", current=current,
            notes="Too long", budget=budget,
        )


def test_notes_change_creates_new_audited_attempt_without_rewriting_history(tmp_path: Path) -> None:
    path = tmp_path / "project.sqlite"
    project_id = _create_project(path, "A")
    segments = _import_txt(path, project_id, "First line.\nSecond line.\n")
    assert len(segments) == 2
    profile = _create_profile(path)
    assert profile.id is not None
    assert segments[0].id is not None and segments[1].id is not None
    with ProjectNotesService(path, app_version=APP_VERSION) as notes:
        notes.set_notes(project_id, "Use formal speech")
    fake = FakeAdapter(_valid_response(segments[0].stable_key))
    with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
        run = service.create_run(project_id=project_id)
        assert run.id is not None
        first_revision = _run(service.translate_segment(
            run_id=run.id, segment_id=segments[0].id, profile_id=profile.id,
        ))
        assert "Use formal speech" in fake.last_prompt
        with ProjectNotesService(path, app_version=APP_VERSION) as notes:
            notes.set_notes(project_id, "Use concise speech")
        fake.response = _valid_response(segments[1].stable_key)
        _run(service.translate_segment(
            run_id=run.id, segment_id=segments[1].id, profile_id=profile.id,
        ))
        assert "Use concise speech" in fake.last_prompt
        assert "Use formal speech" not in fake.last_prompt
    with TranslationRunService(path, app_version=APP_VERSION) as audit:
        attempts = audit.list_attempts_for_run(run.id)
        assert len(attempts) == 2
        assert attempts[0].prompt_hash != attempts[1].prompt_hash
        assert attempts[0].context_summary["notes"] == {
            "present": True, "characters": len("Use formal speech"),
            "sha256": hashlib.sha256(b"Use formal speech").hexdigest(),
        }
        second_notes = attempts[1].context_summary["notes"]
        assert isinstance(second_notes, dict)
        assert second_notes["characters"] == len("Use concise speech")
        assert "Use formal speech" not in str(attempts[0].context_summary)
        assert audit.get_revision(first_revision.id) == first_revision


def test_oversized_notes_fail_before_attempt_or_provider(tmp_path: Path) -> None:
    path = tmp_path / "project.sqlite"
    project_id = _create_project(path, "A")
    segments = _import_txt(path, project_id, "One line.\n")
    profile = _create_profile(path, context_budget={
        "total": 10, "reserved_output": 2, "reserved_prompt": 2,
    })
    assert profile.id is not None and segments[0].id is not None
    with ProjectNotesService(path, app_version=APP_VERSION) as notes:
        notes.set_notes(project_id, "x" * 1000)
    fake = FakeAdapter(_valid_response(segments[0].stable_key))
    with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
        run = service.create_run(project_id=project_id)
        assert run.id is not None
        with pytest.raises(ContextBudgetError):
            _run(service.translate_segment(
                run_id=run.id, segment_id=segments[0].id, profile_id=profile.id,
            ))
    assert fake.calls == 0
    with TranslationRunService(path, app_version=APP_VERSION) as audit:
        assert audit.list_attempts_for_run(run.id) == []
