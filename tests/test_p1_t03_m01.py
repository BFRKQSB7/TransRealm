"""P1-T03-M01: auto-mode minimal journey.

M01 makes ``projects.mode`` (``011`` migration) the persisted interaction
mode, defaulting to the safe ``auto`` for new and pre-existing projects, and
wires the auto journey: the translation worker resolves the project's active
Profile (never a manual picker), translates the imported document, reports
status, and exports; when the project has no active Profile the worker emits
``config_missing`` so the UI can show a single recoverable step. Mode and the
active Profile must survive restarts and both Project forms.

Service-level tests cover the mode column (default, set, reopen, backfill,
DB CHECK backstop); pytest-qt tests cover the auto journey end to end
(import -> translate -> progress -> export), the missing-config guidance, and
restart persistence.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.application.archive_service import (
    export_open_directory_archive,
    import_archive_to_staging,
)
from transrealm.application.install_service import install_staging_to_target
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.project import MODE_WORKBENCH, ProjectError
from transrealm.domain.segment import Segment
from transrealm.infrastructure.database import SqlExecutionError, create_database, transaction
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.open_directory import (
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_FORMAT_VERSION,
    ManifestInfo,
    compute_entry,
    write_manifest,
)
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.1.0"
_CRED_ENV = "TRANSLATOR_M01_P1T03_KEY"
MIGRATIONS_DIR = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"


# --------------------------------------------------------------------------- #
# Service-level: mode persistence, backfill and DB backstop
# --------------------------------------------------------------------------- #


def test_new_project_defaults_to_auto_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "project.db"
    with ProjectService(db_path, app_version=APP_VERSION) as svc:
        project = svc.create_project(
            name="Demo",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        assert project.mode == "auto"
        loaded = svc.get_project(project.id)
        assert loaded is not None
        assert loaded.mode == "auto"


def test_set_mode_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "project.db"
    with ProjectService(db_path, app_version=APP_VERSION) as svc:
        project = svc.create_project(
            name="Demo",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        project_id = project.id
        switched = svc.set_mode(project_id, MODE_WORKBENCH)
        assert switched.mode == MODE_WORKBENCH

    # A fresh service reopens the persisted mode.
    with ProjectService(db_path, app_version=APP_VERSION) as svc:
        reopened = svc.get_project(project_id)
        assert reopened is not None
        assert reopened.mode == MODE_WORKBENCH
        # Switching back is allowed.
        assert svc.set_mode(project_id, "auto").mode == "auto"


def test_set_mode_rejects_unknown_mode(tmp_path: Path) -> None:
    with ProjectService(tmp_path / "project.db", app_version=APP_VERSION) as svc:
        project = svc.create_project(
            name="Demo",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        with pytest.raises(ProjectError):
            svc.set_mode(project.id, "turbo")


def test_set_mode_rejects_missing_project(tmp_path: Path) -> None:
    with ProjectService(tmp_path / "project.db", app_version=APP_VERSION) as svc:
        with pytest.raises(ProjectError):
            svc.set_mode(9999, "workbench")


def test_get_project_returns_none_for_missing(tmp_path: Path) -> None:
    with ProjectService(tmp_path / "project.db", app_version=APP_VERSION) as svc:
        assert svc.get_project(9999) is None


def test_legacy_database_upgrade_backfills_auto_mode(tmp_path: Path) -> None:
    """A database migrated through 010 gains mode='auto' on its projects."""
    db_path = tmp_path / "legacy.db"
    migrations = discover_migrations(MIGRATIONS_DIR)
    db = create_database(db_path)
    try:
        runner = MigrationRunner(db)
        runner.apply(migrations[:10], app_version="0.1.0")
        with transaction(db):
            project_id = db.execute(
                "INSERT INTO projects (name, source_language, target_language) "
                "VALUES ('Legacy', 'ja', 'zh')",
            ).lastrowid
        # Applying only 011 to the legacy schema backfills the new column.
        runner.apply(migrations[10:], app_version="0.1.0")
        (mode,) = db.execute("SELECT mode FROM projects WHERE id = ?", (project_id,)).fetchone()
        assert mode == "auto"
        (name,) = db.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
        assert name == "Legacy"
        assert any(
            record["migration_id"] == "011_add_project_mode" for record in runner.history()
        )
    finally:
        db.close()


def test_database_check_backstops_invalid_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "project.db"
    with ProjectService(db_path, app_version=APP_VERSION) as svc:
        project = svc.create_project(
            name="Demo",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        project_id = project.id

    db = create_database(db_path)
    try:
        with pytest.raises(SqlExecutionError):
            with transaction(db):
                db.execute(
                    "UPDATE projects SET mode = 'bogus' WHERE id = ?",
                    (project_id,),
                )
        (mode,) = db.execute("SELECT mode FROM projects WHERE id = ?", (project_id,)).fetchone()
        assert mode == "auto"
    finally:
        db.close()


def test_dual_form_round_trip_preserves_mode_and_active_profile(tmp_path: Path) -> None:
    """Open dir -> .aiproject -> second machine keeps mode and active Profile."""
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir(parents=True, exist_ok=True)
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ) as created:
        assert created.project.id is not None
        project_id = created.project.id
    db_path = directory / DATABASE_FILENAME

    with ProviderConnectionService(db_path, app_version=APP_VERSION) as svc:
        connection = svc.create_connection(
            name="openai",
            provider_type="openai-compatible",
            endpoint="https://example.invalid/v1",
            credential_reference=f"env:{_CRED_ENV}",
        )
        assert connection.id is not None

    with ModelProfileService(db_path, app_version=APP_VERSION) as svc:
        profile = svc.create_profile(
            name="default",
            provider_connection_id=connection.id,
            model_id="gpt-4o-mini",
            template_version="1",
            output_protocol="json",
            context_budget={"max_tokens": 4096},
            default_params={"temperature": 0.2},
            capability=ModelCapability(
                context_window=8000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_structured_output=True,
                supported_parameters={"temperature"},
            ),
        )
        assert profile.id is not None
        profile_id = profile.id

    with ProjectService(db_path, app_version=APP_VERSION) as svc:
        svc.select_active_profile(project_id, profile_id)
        svc.set_mode(project_id, MODE_WORKBENCH)

    _checkpoint_clean(db_path)
    _refresh_manifest(directory)

    machine_b = tmp_path / "machine_b"
    machine_b.mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "machine_a" / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    staging = machine_b / "staging"
    import_archive_to_staging(archive, staging)
    target = machine_b / "project"
    install_staging_to_target(staging, target, app_version=APP_VERSION)

    with open_open_directory_project(target, app_version=APP_VERSION) as opened:
        assert opened.project.id == project_id
        assert opened.project.mode == MODE_WORKBENCH
        assert opened.project.active_profile_id == profile_id


# --------------------------------------------------------------------------- #
# pytest-qt: auto journey, guidance, restart persistence
# --------------------------------------------------------------------------- #


class SequenceAdapter:
    """In-memory adapter returning a fixed response sequence."""

    def __init__(self, responses: list[AdapterResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get_capabilities(self) -> ModelCapability:
        return ModelCapability(
            context_window=128000,
            max_output_tokens=4096,
            supports_streaming=False,
            supports_structured_output=False,
            supported_parameters={"temperature", "max_tokens"},
        )

    def filter_params(self, params: dict[str, object]) -> dict[str, object]:
        return params

    async def chat_completion(self, request: AdapterRequest) -> AdapterResponse:
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _valid_response(stable_key: str, translation: str) -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-m01",
        raw_response=None,
    )


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path) -> Any:
    """Build MainWindows against a shared database path and per-window adapters."""
    created: list[MainWindow] = []

    def make(db_path: Path | None = None) -> tuple[MainWindow, dict[str, Any]]:
        holder: dict[str, Any] = {}
        window = MainWindow(
            db_path or (tmp_path / "project.sqlite"),
            app_version=APP_VERSION,
            adapter_factory=lambda profile_id: holder["adapter"],
        )
        qtbot.addWidget(window)
        created.append(window)
        return window, holder

    yield make
    for window in created:
        window.shutdown()


def _segments(db_path: Path, document_id: int) -> list[Segment]:
    repo = SegmentRepository.open(db_path)
    try:
        return repo.list_segments_by_document(document_id)
    finally:
        repo.close()


def _wait_finished(qtbot: Any, worker: Any) -> None:
    done = [False]

    def mark() -> None:
        done[0] = True

    worker.finished.connect(mark)
    qtbot.waitUntil(lambda: done[0], timeout=20000)


def _setup_profile(qtbot: Any, window: MainWindow) -> None:
    settings = window._settings
    settings._conn_name.setText("local")
    settings._conn_endpoint.setText("http://localhost:8080/v1")
    settings._add_connection.click()
    qtbot.waitUntil(lambda: settings._connections_list.count() == 1, timeout=5000)

    settings._profile_name.setText("general")
    settings._profile_model.setText("gpt-4o-mini")
    qtbot.waitUntil(lambda: settings._profile_connection.count() == 1, timeout=5000)
    settings._add_profile.click()
    qtbot.waitUntil(lambda: settings._profiles_list.count() == 1, timeout=5000)


def _setup_project_and_document(
    window: MainWindow,
    qtbot: Any,
    tmp_path: Path,
    content: str,
    *,
    set_active: bool = True,
) -> tuple[int, int]:
    """Create a project (+ optional active profile) and import ``content``.

    Returns ``(project_id, document_id)``. Auto mode translates with the
    active Profile, so ``set_active=True`` (the default) exercises the auto
    resolution path; ``set_active=False`` produces the missing-config state.
    """
    _setup_profile(qtbot, window)
    project = window._project
    translation = window._translation

    project._project_name.setText("Demo")
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
    assert project._project_id is not None
    project_id = project._project_id

    if set_active:
        qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
        project._active_profile_combo.setCurrentIndex(
            project._active_profile_combo.findData(
                project._active_profile_combo.itemData(0),
            ),
        )
        project._set_active.click()
        qtbot.waitUntil(
            lambda: "Active:" in project._active_profile_label.text(),
            timeout=5000,
        )

    source = tmp_path / "source.txt"
    source.write_text(content, encoding="utf-8")
    project.import_file(source)
    qtbot.waitUntil(lambda: translation._document_id is not None, timeout=5000)
    assert translation._document_id is not None
    return project_id, translation._document_id


class TestAutoJourney:
    """Auto mode resolves the active Profile and completes import -> export."""

    def test_auto_translate_resolves_active_profile_and_exports(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        project_id, document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha line.\nBeta line.\n",
        )

        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = SequenceAdapter([
            _valid_response(segments[0].stable_key, "甲"),
            _valid_response(segments[1].stable_key, "乙"),
        ])

        translation = window._translation
        # The page reports the persisted mode and the resolved active profile.
        qtbot.waitUntil(lambda: "Mode: auto" in translation._mode_label.text(), timeout=5000)
        qtbot.waitUntil(
            lambda: "Active profile:" in translation._active_profile_label.text(),
            timeout=5000,
        )

        translation.translate()
        _wait_finished(qtbot, window._translation_worker)

        adapter = holder["adapter"]
        assert adapter.calls == 2, (
            f"adapter.calls={adapter.calls} status={translation._status.text()!r} "
            f"progress={translation._progress.value()}"
        )
        assert translation._progress.value() == 2
        assert translation._progress.maximum() == 2

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        target = out_dir / "translated.txt"
        translation.export_to(target)
        qtbot.waitUntil(lambda: "Export written" in translation._status.text(), timeout=5000)
        assert target.read_text(encoding="utf-8") == "甲\n乙\n"

    def test_translate_with_no_pending_segments_finishes(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        """Re-translating a completed document ends cleanly, not stuck."""
        window, holder = window_factory()
        _, document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\n",
        )
        segments = _segments(tmp_path / "project.sqlite", document_id)
        holder["adapter"] = SequenceAdapter([
            _valid_response(segments[0].stable_key, "甲"),
        ])

        translation = window._translation
        translation.translate()
        _wait_finished(qtbot, window._translation_worker)
        assert holder["adapter"].calls == 1
        assert translation._progress.value() == 1

        # All segments are now completed; a second run has zero pending segments.
        translation.translate()
        _wait_finished(qtbot, window._translation_worker)
        assert holder["adapter"].calls == 1
        assert translation._status.text() == "Translation finished."


class TestMissingConfigGuidance:
    """Without an active Profile, auto mode stops with a recoverable step."""

    def test_auto_translate_without_active_profile_emits_config_missing(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, holder = window_factory()
        project_id, document_id = _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\n",
            set_active=False,
        )
        holder["adapter"] = SequenceAdapter([])

        messages: list[str] = []
        window._translation_worker.config_missing.connect(messages.append)

        translation = window._translation
        translation.translate()
        _wait_finished(qtbot, window._translation_worker)

        assert messages and "active profile" in messages[0].lower()
        assert holder["adapter"].calls == 0
        # No run was created: the adapter was never reached.
        with TranslationRunService(tmp_path / "project.sqlite", app_version=APP_VERSION) as svc:
            assert svc.list_runs_for_project(project_id) == []

        # The one-step recoverable guidance is visible and jumps to the Project tab.
        assert not translation._config_missing_label.isHidden()
        assert not translation._set_active_profile.isHidden()
        translation._set_active_profile.click()
        assert window.centralWidget().currentIndex() == 1

    def test_guidance_clears_after_setting_active_profile(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        """Setting the active Profile from the recovery step dismisses the banner."""
        window, holder = window_factory()
        _setup_project_and_document(
            window,
            qtbot,
            tmp_path,
            "Alpha.\n",
            set_active=False,
        )
        holder["adapter"] = SequenceAdapter([])

        translation = window._translation
        translation.translate()
        _wait_finished(qtbot, window._translation_worker)
        assert not translation._config_missing_label.isHidden()

        # The one-step recovery: set the active Profile on the Project tab.
        # The create-project refresh may have been superseded by the import on
        # the shared worker, so refresh once more before reading the combo.
        project = window._project
        project.refresh()
        qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
        project._active_profile_combo.setCurrentIndex(
            project._active_profile_combo.findData(
                project._active_profile_combo.itemData(0),
            ),
        )
        project._set_active.click()
        qtbot.waitUntil(lambda: translation._config_missing_label.isHidden(), timeout=5000)
        qtbot.waitUntil(
            lambda: "Active profile:" in translation._active_profile_label.text(),
            timeout=5000,
        )

    def test_auto_translate_missing_project_emits_config_missing(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        """A non-existent project id stops with config guidance, not a call."""
        # Initialize the schema before the window starts its workers so the
        # translation worker's ProjectService does not race the service
        # worker's migration step on a brand-new database.
        db_path = tmp_path / "project.sqlite"
        with ProjectService(db_path, app_version=APP_VERSION):
            pass

        window, holder = window_factory(db_path)
        holder["adapter"] = SequenceAdapter([])

        messages: list[str] = []
        window._translation_worker.config_missing.connect(messages.append)

        window._translation_worker.start_translate_auto.emit(9999, 0)
        _wait_finished(qtbot, window._translation_worker)

        assert messages and "does not exist" in messages[0]
        assert holder["adapter"].calls == 0

    def test_auto_translate_service_error_emits_failed(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        """A service failure on the worker is reported, never stuck on the UI."""
        window, holder = window_factory()
        holder["adapter"] = SequenceAdapter([])

        errors: list[str] = []
        done = [False]
        window._translation_worker.failed.connect(errors.append)
        # Connect `finished` before emitting: this worker fails before any model
        # call, so `finished` can otherwise be emitted (and, for a direct
        # callable connection, run) before the wait helper connects to it.
        window._translation_worker.finished.connect(lambda: done.__setitem__(0, True))

        class BoomService:
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("boom")

        monkeypatch.setattr("transrealm.ui.worker.ProjectService", BoomService)

        window._translation_worker.start_translate_auto.emit(1, 2)
        qtbot.waitUntil(lambda: done[0], timeout=20000)

        assert errors and "boom" in errors[0]


class TestRestartPersistence:
    """Mode and active Profile survive a window restart and still translate."""

    def test_auto_mode_works_after_window_reopen(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "project.sqlite"

        window1, _ = window_factory(db_path)
        project_id, document_id = _setup_project_and_document(
            window1,
            qtbot,
            tmp_path,
            "Alpha.\nBeta.\n",
        )
        window1.shutdown()

        # A fresh window against the same database keeps mode + active profile.
        window2, holder = window_factory(db_path)
        window2._project.select_project(project_id)
        qtbot.waitUntil(
            lambda: "Mode: auto" in window2._translation._mode_label.text(),
            timeout=5000,
        )
        qtbot.waitUntil(
            lambda: "Active profile:" in window2._translation._active_profile_label.text(),
            timeout=5000,
        )

        # Re-importing the same file returns the existing document (hash idempotent).
        source = tmp_path / "source.txt"
        source.write_text("Alpha.\nBeta.\n", encoding="utf-8")
        window2._project.import_file(source)
        qtbot.waitUntil(lambda: window2._translation._document_id is not None, timeout=5000)
        assert window2._translation._document_id is not None
        document_id = window2._translation._document_id

        segments = _segments(db_path, document_id)
        holder["adapter"] = SequenceAdapter([
            _valid_response(segment.stable_key, f"T{i}")
            for i, segment in enumerate(segments)
        ])
        window2._translation.translate()
        _wait_finished(qtbot, window2._translation_worker)

        assert holder["adapter"].calls == len(segments)
        assert window2._translation._progress.value() == len(segments)


# --------------------------------------------------------------------------- #
# Dual-form helpers shared by the service-level round-trip test above
# --------------------------------------------------------------------------- #


def _checkpoint_clean(db_path: Path) -> None:
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        raw.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _refresh_manifest(directory: Path) -> None:
    db_path = directory / DATABASE_FILENAME
    entries = [
        compute_entry(DATABASE_FILENAME, db_path, entry_type=CRITICAL_ENTRY_TYPE),
    ]
    sidecars = {f"{DATABASE_FILENAME}-wal", f"{DATABASE_FILENAME}-shm"}
    for entry in directory.rglob("*"):
        if (
            entry.is_file()
            and entry.name != MANIFEST_FILENAME
            and entry != db_path
            and entry.name not in sidecars
        ):
            relpath = entry.relative_to(directory).as_posix()
            entries.append(compute_entry(relpath, entry, entry_type="attachment"))
    write_manifest(
        directory,
        ManifestInfo(MANIFEST_FORMAT_VERSION, 1, APP_VERSION, tuple(entries)),
    )
