"""P1-T03-M04: manual Revision and locking.

Workbench edits append an ``origin=user`` TranslationRevision and make it the
current revision; the current revision can be switched to a historical revision
and locked/unlocked. A locked current revision cannot be replaced by an
automatic late result or a re-translation (finalize fencing, claim skip and
lease recovery all refuse), and export follows the selection semantics: the
current revision by default, an explicit revision via ``revision_overrides``.
The vertical slice is: service use cases -> locked protection -> export ->
workbench editor.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterResponse, AdapterUsage
from transrealm.application.exporter import TxtExporter
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import (
    TranslationRunService,
    TranslationRunServiceError,
)
from transrealm.application.translation_service import TranslationService
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.project import MODE_WORKBENCH
from transrealm.domain.segment import Segment
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)
from transrealm.infrastructure.repositories.translation_workflow_repository import (
    WorkflowDefinitionRepository,
)
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.1.0"
DEFAULT_BUDGET: dict[str, object] = {
    "total": 8192,
    "reserved_output": 1024,
    "reserved_prompt": 1024,
}
_BUILTIN_WORKFLOW = ("general_translation", "1.0.0")


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


class RecordingAdapter:
    """In-memory ModelAdapter recording every request it receives."""

    def __init__(self, responses: list[AdapterResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.last_request: Any = None

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

    async def chat_completion(self, request: Any) -> AdapterResponse:
        self.calls += 1
        self.last_request = request
        index = min(self.calls - 1, len(self.responses) - 1)
        item = self.responses[index]
        if isinstance(item, Exception):
            raise item
        return item


def _create_project(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="M04",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_txt(path: Path, project_id: int, content: str) -> list[Segment]:
    txt_path = path.parent / "source.txt"
    txt_path.write_text(content, encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as service:
        _document, segments = service.import_txt(project_id, txt_path, name="source.txt")
    return segments


def _segments(db_path: Path, document_id: int) -> list[Segment]:
    repo = SegmentRepository.open(db_path)
    try:
        return repo.list_segments_by_document(document_id)
    finally:
        repo.close()


def _ids(segments: list[Segment]) -> list[int]:
    ids: list[int] = []
    for segment in segments:
        assert segment.id is not None
        ids.append(segment.id)
    return ids


def _create_profile(path: Path) -> ModelProfile:
    cap = ModelCapability(
        context_window=128000,
        max_output_tokens=4096,
        supports_streaming=False,
        supports_structured_output=False,
        supported_parameters={"temperature", "max_tokens"},
    )
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.create_connection(
            name="local",
            provider_type="openai-compatible",
            endpoint="http://localhost:8080/v1",
            credential_reference="env:OPENAI_API_KEY",
        )
        assert connection.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profile_service:
            profile = profile_service.create_profile(
                name="general",
                provider_connection_id=connection.id,
                model_id="gpt-4o-mini",
                template_version="1.0.0",
                output_protocol="json",
                context_budget=DEFAULT_BUDGET,
                default_params={"temperature": 0.3},
                capability=cap,
            )
    assert profile.id is not None
    return profile


def _valid_response(stable_key: str, translation: str) -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-m04",
        raw_response=None,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _set_segment_status(db_path: Path, segment_id: int, *, status: str) -> None:
    """Directly flip a segment's status with a cleared lease (fault injection).

    Used to simulate a crash/recovery site or a concurrent re-queue that the
    service use cases must fence against.
    """
    conn = create_database(db_path)
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE segments SET status = ?, lease_owner = NULL, "
                "lease_expires_at = NULL, version = version + 1 WHERE id = ?",
                (status, segment_id),
            )
    finally:
        conn.close()


def _force_stale_processing(db_path: Path, segment_id: int) -> None:
    """Mark a segment processing with an already-expired lease."""
    conn = create_database(db_path)
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE segments SET status = 'processing', "
                "lease_owner = 'owner:stale', "
                "lease_expires_at = '2000-01-01T00:00:00+00:00', "
                "version = version + 1 WHERE id = ?",
                (segment_id,),
            )
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Service: append_user_revision
# --------------------------------------------------------------------------- #


class TestAppendUserRevision:
    def test_append_user_revision_becomes_current(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            rev = runs.append_user_revision(segment_id=seg_id, text="你好")
        assert rev.id is not None
        assert rev.origin == "user"
        assert rev.is_locked is False
        after = _segments(path, segments[0].source_document_id)[0]
        assert after.status == "completed"
        assert after.current_revision_id == rev.id

    def test_append_user_revision_keeps_prior_ai_history(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        profile = _create_profile(path)
        assert profile.id is not None
        adapter = RecordingAdapter(
            [_valid_response(segments[0].stable_key, "こんにちは")],
        )
        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=seg_id,
                    profile_id=profile.id,
                ),
            )
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            user_rev = runs.append_user_revision(segment_id=seg_id, text="你好")
            assert user_rev.id is not None
        repo = TranslationRevisionRepository.open(path)
        try:
            history = repo.list_by_segment(seg_id)
        finally:
            repo.close()
        assert [revision.origin for revision in history] == ["ai", "user"]
        after = _segments(path, segments[0].source_document_id)[0]
        assert after.current_revision_id == user_rev.id

    def test_append_user_revision_missing_segment(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        _create_project(path)
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            with pytest.raises(TranslationRunServiceError, match="does not exist"):
                runs.append_user_revision(segment_id=9999, text="x")

    def test_append_user_revision_rejects_processing(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        _set_segment_status(path, seg_id, status="processing")
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            with pytest.raises(TranslationRunServiceError, match="translation is in progress"):
                runs.append_user_revision(segment_id=seg_id, text="x")

    def test_append_user_revision_allows_empty_text(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            rev = runs.append_user_revision(segment_id=seg_id, text="")
        assert rev.text == ""


# --------------------------------------------------------------------------- #
# Service: switch current to a historical revision
# --------------------------------------------------------------------------- #


class TestSetCurrentRevision:
    def test_set_current_revision_switches_to_history(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            first = runs.append_user_revision(segment_id=seg_id, text="一")
            second = runs.append_user_revision(segment_id=seg_id, text="二")
            assert first.id is not None and second.id is not None
            after = _segments(path, segments[0].source_document_id)[0]
            assert after.current_revision_id == second.id
            runs.set_current_revision(segment_id=seg_id, revision_id=first.id)
        switched = _segments(path, segments[0].source_document_id)[0]
        assert switched.current_revision_id == first.id

    def test_set_current_revision_cross_segment_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Alpha.\nBeta.\n")
        ids = _ids(segments)
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            first = runs.append_user_revision(segment_id=ids[0], text="甲")
            assert first.id is not None
            with pytest.raises(TranslationRunServiceError, match="belongs to segment"):
                runs.set_current_revision(segment_id=ids[1], revision_id=first.id)

    def test_set_current_revision_missing_revision_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            with pytest.raises(TranslationRunServiceError, match="does not exist"):
                runs.set_current_revision(segment_id=seg_id, revision_id=9999)

    def test_set_current_revision_rejects_processing(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            first = runs.append_user_revision(segment_id=seg_id, text="甲")
            assert first.id is not None
            _set_segment_status(path, seg_id, status="processing")
            with pytest.raises(TranslationRunServiceError, match="translation is in progress"):
                runs.set_current_revision(segment_id=seg_id, revision_id=first.id)


# --------------------------------------------------------------------------- #
# Service: lock / unlock current
# --------------------------------------------------------------------------- #


class TestLockCurrent:
    def test_lock_and_unlock_current(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            rev = runs.append_user_revision(segment_id=seg_id, text="你好")
            assert rev.id is not None
            locked = runs.lock_current_revision(segment_id=seg_id)
            assert locked.is_locked is True
            unlocked = runs.unlock_current_revision(segment_id=seg_id)
            assert unlocked.is_locked is False

    def test_lock_without_current_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            with pytest.raises(TranslationRunServiceError, match="no current revision"):
                runs.lock_current_revision(segment_id=seg_id)

    def test_lock_missing_segment_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        _create_project(path)
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            with pytest.raises(TranslationRunServiceError, match="does not exist"):
                runs.lock_current_revision(segment_id=9999)


# --------------------------------------------------------------------------- #
# Locked current protection
# --------------------------------------------------------------------------- #


class TestLockedCurrentProtection:
    def test_finalize_rejects_locked_current(self, tmp_path: Path) -> None:
        """A late automatic finalize cannot replace a locked current revision."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        profile = _create_profile(path)
        assert profile.id is not None
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            user_rev = runs.append_user_revision(segment_id=seg_id, text="你好")
            assert user_rev.id is not None
            _set_segment_status(path, seg_id, status="pending")
            repo = WorkflowDefinitionRepository.open(path)
            try:
                workflow = repo.get_by_name_and_version(*_BUILTIN_WORKFLOW)
            finally:
                repo.close()
            assert workflow is not None and workflow.id is not None
            run = runs.create_run(project_id=project_id, workflow_id=workflow.id)
            assert run.id is not None
            claim_segment = _segments(path, segments[0].source_document_id)[0]
            attempt = runs.start_attempt(
                run_id=run.id,
                segment=claim_segment,
                profile=profile,
                prompt_hash="h",
                context_summary={},
                validator_summary={},
            )
            assert attempt.id is not None
            runs.lock_current_revision(segment_id=seg_id)
            with pytest.raises(TranslationRunServiceError, match="locked"):
                runs.finalize_success(
                    attempt_id=attempt.id,
                    translated_text="迟到结果",
                    expected_current_revision_id=user_rev.id,
                    request_id="req",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=1,
                )

    def test_auto_retranslate_skips_locked_current(self, tmp_path: Path) -> None:
        """A completed locked segment is never re-claimed: no second request."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        profile = _create_profile(path)
        assert profile.id is not None
        adapter = RecordingAdapter(
            [_valid_response(segments[0].stable_key, "こんにちは")],
        )
        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=seg_id,
                    profile_id=profile.id,
                ),
            )
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            user_rev = runs.append_user_revision(segment_id=seg_id, text="你好")
            assert user_rev.id is not None
            runs.lock_current_revision(segment_id=seg_id)
        retry_adapter = RecordingAdapter([])
        with TranslationService(
            path,
            app_version=APP_VERSION,
            adapter=retry_adapter,
        ) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(TranslationRunServiceError, match="not pending"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=seg_id,
                        profile_id=profile.id,
                    ),
                )
        assert retry_adapter.calls == 0
        after = _segments(path, segments[0].source_document_id)[0]
        assert after.current_revision_id == user_rev.id
        repo = TranslationRevisionRepository.open(path)
        try:
            assert len(repo.list_by_segment(seg_id)) == 2
        finally:
            repo.close()

    def test_recover_keeps_locked_current_completed(self, tmp_path: Path) -> None:
        """Recovery converges a stale processing segment to completed without
        rebuilding or replacing its locked current revision."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            user_rev = runs.append_user_revision(segment_id=seg_id, text="你好")
            assert user_rev.id is not None
            runs.lock_current_revision(segment_id=seg_id)
        _force_stale_processing(path, seg_id)
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            recovered = runs.recover_expired_leases()
            assert recovered == 1
        after = _segments(path, segments[0].source_document_id)[0]
        assert after.status == "completed"
        assert after.current_revision_id == user_rev.id
        repo = TranslationRevisionRepository.open(path)
        try:
            assert len(repo.list_by_segment(seg_id)) == 1
        finally:
            repo.close()

    def test_recover_returns_unlocked_user_current_to_pending(self, tmp_path: Path) -> None:
        """Recovery only keeps a *locked* current as final; an unlocked user
        current that somehow lands in processing returns to pending so it can be
        re-translated (normal flow never reaches this: append marks the segment
        completed, and only a crash/corruption site produces this state)."""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            runs.append_user_revision(segment_id=seg_id, text="你好")
        _force_stale_processing(path, seg_id)
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            recovered = runs.recover_expired_leases()
            assert recovered == 1
        after = _segments(path, segments[0].source_document_id)[0]
        assert after.status == "pending"
        assert after.current_revision_id is not None


# --------------------------------------------------------------------------- #
# Export follows the selection semantics
# --------------------------------------------------------------------------- #


class TestExportSelection:
    def test_export_defaults_to_locked_user_current(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            runs.append_user_revision(segment_id=seg_id, text="你好")
            runs.lock_current_revision(segment_id=seg_id)
        out = tmp_path / "out.txt"
        with TxtExporter(path, app_version=APP_VERSION) as exporter:
            exporter.export_document(
                source_document_id=segments[0].source_document_id,
                target_path=out,
            )
        assert out.read_text(encoding="utf-8") == "你好\n"

    def test_export_override_selects_historical_revision(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        seg_id = _ids(segments)[0]
        with TranslationRunService(path, app_version=APP_VERSION) as runs:
            first = runs.append_user_revision(segment_id=seg_id, text="一")
            second = runs.append_user_revision(segment_id=seg_id, text="二")
            assert first.id is not None and second.id is not None
        out = tmp_path / "out.txt"
        with TxtExporter(path, app_version=APP_VERSION) as exporter:
            exporter.export_document(
                source_document_id=segments[0].source_document_id,
                target_path=out,
                revision_overrides={seg_id: first.id},
            )
        assert out.read_text(encoding="utf-8") == "一\n"
        # The explicit override does not change the current revision.
        after = _segments(path, segments[0].source_document_id)[0]
        assert after.current_revision_id == second.id


# --------------------------------------------------------------------------- #
# Workbench editor (pytest-qt)
# --------------------------------------------------------------------------- #


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


def _activate_profile(window: MainWindow, qtbot: Any) -> None:
    project = window._project
    qtbot.waitUntil(lambda: project._active_profile_combo.count() >= 1, timeout=5000)
    project._active_profile_combo.setCurrentIndex(
        project._active_profile_combo.findData(project._active_profile_combo.itemData(0)),
    )
    project._set_active.click()
    qtbot.waitUntil(
        lambda: "Active:" in project._active_profile_label.text(),
        timeout=5000,
    )


def _setup_workbench_project(
    window: MainWindow,
    qtbot: Any,
    tmp_path: Path,
    content: str = "Alpha.\nBeta.\n",
) -> tuple[int, int]:
    _setup_profile(qtbot, window)
    project = window._project
    translation = window._translation

    project._project_name.setText("Demo")
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
    assert project._project_id is not None
    project_id = project._project_id

    with ProjectService(translation._db_path, app_version=APP_VERSION) as svc:
        svc.set_mode(project_id, MODE_WORKBENCH)

    _activate_profile(window, qtbot)

    source = tmp_path / "source.txt"
    source.write_text(content, encoding="utf-8")
    project.import_file(source)
    qtbot.waitUntil(lambda: translation._document_id is not None, timeout=5000)
    assert translation._document_id is not None
    return project_id, translation._document_id


class TestTranslationPageWorkbenchRevision:
    def test_workbench_edit_appends_user_revision(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._segment_progress.count() >= 1, timeout=5000)
        translation._segment_progress.setCurrentRow(0)
        qtbot.waitUntil(lambda: translation._revision_editor is not None, timeout=5000)
        editor = translation._revision_editor
        assert editor is not None
        editor._editor.setPlainText("你好")
        editor._save.click()
        qtbot.waitUntil(
            lambda: "Manual translation saved." in translation._status.text(),
            timeout=5000,
        )
        assert translation._document_id is not None
        with TranslationRunService(
            translation._db_path,
            app_version=APP_VERSION,
        ) as runs:
            progress = runs.list_segment_progress(
                source_document_id=translation._document_id,
            )
        assert progress[0].current_revision_id is not None
        assert progress[0].revision_text == "你好"
        assert progress[0].revision_locked is False

    def test_workbench_revision_draft_preserved_across_refresh(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        """An unsaved edit survives a refresh of the same selected segment."""
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._segment_progress.count() >= 1, timeout=5000)
        translation._segment_progress.setCurrentRow(0)
        qtbot.waitUntil(lambda: translation._revision_editor is not None, timeout=5000)
        editor = translation._revision_editor
        assert editor is not None
        editor._editor.setPlainText("草稿")
        translation.refresh()
        qtbot.waitUntil(
            lambda: translation._revision_editor is not None
            and translation._revision_editor.translation() == "草稿",
            timeout=5000,
        )

    def test_workbench_lock_and_unlock_current(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._segment_progress.count() >= 1, timeout=5000)
        translation._segment_progress.setCurrentRow(0)
        qtbot.waitUntil(lambda: translation._revision_editor is not None, timeout=5000)
        editor = translation._revision_editor
        assert editor is not None
        editor._editor.setPlainText("你好")
        editor._save.click()
        qtbot.waitUntil(
            lambda: "Manual translation saved." in translation._status.text(),
            timeout=5000,
        )
        qtbot.waitUntil(
            lambda: translation._revision_editor is not None
            and translation._revision_editor._lock.isEnabled(),
            timeout=5000,
        )
        editor = translation._revision_editor
        assert editor is not None
        editor._lock.click()
        qtbot.waitUntil(
            lambda: "Current translation locked." in translation._status.text(),
            timeout=5000,
        )
        assert translation._document_id is not None
        with TranslationRunService(
            translation._db_path,
            app_version=APP_VERSION,
        ) as runs:
            progress = runs.list_segment_progress(
                source_document_id=translation._document_id,
            )
        assert progress[0].revision_locked is True
        qtbot.waitUntil(
            lambda: translation._revision_editor is not None
            and translation._revision_editor._unlock.isEnabled(),
            timeout=5000,
        )
        editor = translation._revision_editor
        assert editor is not None
        editor._unlock.click()
        qtbot.waitUntil(
            lambda: "Current translation unlocked." in translation._status.text(),
            timeout=5000,
        )
        with TranslationRunService(
            translation._db_path,
            app_version=APP_VERSION,
        ) as runs:
            progress = runs.list_segment_progress(
                source_document_id=translation._document_id,
            )
        assert progress[0].revision_locked is False
