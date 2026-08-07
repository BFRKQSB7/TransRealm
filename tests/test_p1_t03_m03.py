"""P1-T03-M03: controlled Prompt Override.

The preset template is read-only; a user's edited copy is saved as an override
recording the parent preset version. Unknown variables, stale parent versions
and attempts to remove the output boundary are rejected, and template text is
never executed (``string.Template`` performs pure substitution). The vertical
slice is: save / reopen / reject, then rendering + attempt audit, then the
workbench prompt editor.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.application.context import (
    ContextBudget,
    ContextManifest,
    ContextSource,
    EstimateMethod,
)
from transrealm.application.context_composer import ContextComposer
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.preset_templates import (
    ALLOWED_PLACEHOLDERS,
    PRESET_TEMPLATE_ID,
    current_preset,
    get_preset_template,
    resolve_override_template,
)
from transrealm.application.project_service import ProjectService
from transrealm.application.prompt_renderer import PromptRenderer
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.translation_service import (
    TranslationService,
)
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.project import MODE_WORKBENCH
from transrealm.domain.prompt_override import (
    PromptOverride,
    PromptOverrideError,
    validate_override_template,
)
from transrealm.domain.segment import Segment
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.repositories.prompt_override_repository import (
    PromptOverrideRepository,
)
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.ui.main_window import MainWindow
from transrealm.ui.workbench import WorkbenchPromptEditor

APP_VERSION = "0.1.0"
DEFAULT_BUDGET: dict[str, object] = {
    "total": 8192,
    "reserved_output": 1024,
    "reserved_prompt": 1024,
}


# --------------------------------------------------------------------------- #
# Shared helpers (service level)
# --------------------------------------------------------------------------- #


class RecordingAdapter:
    """In-memory ModelAdapter recording every request it receives."""

    def __init__(self, responses: list[AdapterResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.last_request: AdapterRequest | None = None

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
            name="M03",
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


def _create_profile(
    path: Path,
    *,
    capability: ModelCapability | None = None,
    default_params: dict[str, object] | None = None,
) -> ModelProfile:
    cap = capability or ModelCapability(
        context_window=128000,
        max_output_tokens=4096,
        supports_streaming=False,
        supports_structured_output=False,
        supported_parameters={"temperature", "max_tokens"},
    )
    params: dict[str, object] = (
        default_params if default_params is not None else {"temperature": 0.3}
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
                default_params=params,
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
        request_id="req-m03",
        raw_response=None,
    )


def _ids(segments: list[Segment]) -> list[int]:
    ids: list[int] = []
    for segment in segments:
        assert segment.id is not None
        ids.append(segment.id)
    return ids


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _override_template() -> str:
    return "Translate $current with great formality."


# --------------------------------------------------------------------------- #
# Preset template registry
# --------------------------------------------------------------------------- #


class TestPresetTemplates:
    def test_current_preset_is_versioned_and_stable(self) -> None:
        preset = current_preset()
        assert preset.template_id == PRESET_TEMPLATE_ID
        assert preset.version
        assert get_preset_template(PRESET_TEMPLATE_ID) is preset
        assert get_preset_template("nope") is None

    def test_renderer_default_matches_preset(self) -> None:
        preset = current_preset()
        renderer = PromptRenderer()
        assert renderer._default_template.template == preset.template_text

    def test_allowed_placeholders_match_renderer_placeholders(self) -> None:
        renderer = PromptRenderer()
        manifest = _manifest()
        current = next(
            candidate
            for candidate in manifest.selected
            if candidate.source == ContextSource.CURRENT_SEGMENT
        )
        placeholders = set(
            renderer._build_placeholders([current], manifest, "{}", "en", "zh"),
        )
        assert placeholders == set(ALLOWED_PLACEHOLDERS)


def _segment(stable_key: str, source_text: str, sequence: int) -> Segment:
    return Segment.create(
        source_document_id=1,
        stable_key=stable_key,
        source_text=source_text,
        sequence=sequence,
    )


def _manifest() -> ContextManifest:
    composer = ContextComposer()
    current = _segment("seg-1", "Hello", 1)
    budget = ContextBudget(
        total_budget=100,
        reserved_output=10,
        reserved_prompt=10,
        estimate_method=EstimateMethod.CHARACTER,
    )
    return composer.compose(
        profile_id="general",
        template_version="v1",
        current=current,
        neighbors=[_segment("seg-2", "World", 2)],
        budget=budget,
    )


# --------------------------------------------------------------------------- #
# Override domain validation
# --------------------------------------------------------------------------- #


class TestPromptOverrideDomain:
    def test_create_valid_override(self) -> None:
        override = PromptOverride.create(
            model_profile_id=1,
            parent_template_version="1.0.0",
            template_text=_override_template(),
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        assert override.id is None
        assert override.parent_template_version == "1.0.0"

    def test_unknown_variable_rejected(self) -> None:
        with pytest.raises(PromptOverrideError, match=r"\$unknown"):
            PromptOverride.create(
                model_profile_id=1,
                parent_template_version="1.0.0",
                template_text="Translate $unknown.",
                allowed_placeholders=ALLOWED_PLACEHOLDERS,
            )

    def test_empty_template_rejected(self) -> None:
        with pytest.raises(PromptOverrideError, match="empty"):
            validate_override_template("   ", allowed_placeholders=ALLOWED_PLACEHOLDERS)

    def test_non_string_template_rejected(self) -> None:
        with pytest.raises(PromptOverrideError, match="string"):
            validate_override_template(123, allowed_placeholders=ALLOWED_PLACEHOLDERS)  # type: ignore[arg-type]

    def test_invalid_dollar_syntax_rejected(self) -> None:
        with pytest.raises(PromptOverrideError, match="syntax"):
            validate_override_template(
                "Translate $ ",
                allowed_placeholders=ALLOWED_PLACEHOLDERS,
            )

    def test_literal_dollar_must_be_escaped(self) -> None:
        # ``string.Template`` reads ``$5`` as a malformed placeholder, so a bare
        # currency amount is rejected with ``$$`` guidance and the escaped form
        # is accepted.
        with pytest.raises(PromptOverrideError, match=r"\$\$"):
            validate_override_template(
                "Price: $5 per $current.",
                allowed_placeholders=ALLOWED_PLACEHOLDERS,
            )
        validate_override_template(
            "Price: $$5 per $current.",
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )

    def test_parent_version_required(self) -> None:
        with pytest.raises(PromptOverrideError, match="parent_template_version"):
            PromptOverride.create(
                model_profile_id=1,
                parent_template_version=" ",
                template_text=_override_template(),
                allowed_placeholders=ALLOWED_PLACEHOLDERS,
            )

    def test_profile_id_must_be_positive(self) -> None:
        with pytest.raises(PromptOverrideError, match="positive integer"):
            PromptOverride.create(
                model_profile_id=0,
                parent_template_version="1.0.0",
                template_text=_override_template(),
                allowed_placeholders=ALLOWED_PLACEHOLDERS,
            )

    def test_with_text_revalidates(self) -> None:
        override = PromptOverride.create(
            model_profile_id=1,
            parent_template_version="1.0.0",
            template_text=_override_template(),
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        updated = override.with_text(
            "Translate $current softly.",
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        assert updated.template_text == "Translate $current softly."
        with pytest.raises(PromptOverrideError, match=r"\$bogus"):
            override.with_text(
                "Translate $bogus.",
                allowed_placeholders=ALLOWED_PLACEHOLDERS,
            )


# --------------------------------------------------------------------------- #
# Override repository and old-schema migration
# --------------------------------------------------------------------------- #


class TestPromptOverrideRepository:
    def test_save_get_update_delete(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        profile = _create_profile(path)
        assert profile.id is not None
        override = PromptOverride.create(
            model_profile_id=profile.id,
            parent_template_version="1.0.0",
            template_text=_override_template(),
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        repo = PromptOverrideRepository.open(path)
        try:
            saved = repo.save(override)
            assert saved.id is not None
            loaded = repo.get_by_profile(profile.id)
            assert loaded is not None
            assert loaded.template_text == _override_template()
            # Saving again updates the single row rather than duplicating.
            updated = repo.save(saved.with_text(
                "Translate $current twice.",
                allowed_placeholders=ALLOWED_PLACEHOLDERS,
            ))
            assert updated.id == saved.id
            assert repo.get_by_profile(profile.id) is not None
            rows = repo._db.execute(
                "SELECT COUNT(*) FROM prompt_overrides WHERE model_profile_id = ?",
                (profile.id,),
            ).fetchone()
            assert rows is not None and rows[0] == 1
            assert repo.delete_by_profile(profile.id) is True
            assert repo.get_by_profile(profile.id) is None
            assert repo.delete_by_profile(profile.id) is False
        finally:
            repo.close()

    def test_old_schema_upgrades_to_012_preserving_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        migrations = discover_migrations(ModelProfileService.MIGRATIONS_DIR)
        old = [m for m in migrations if m.migration_id <= "011_add_project_mode"]
        assert any(m.migration_id == "011_add_project_mode" for m in old)
        assert not any(m.migration_id.startswith("012") for m in old)

        runner = MigrationRunner.open(path)
        try:
            runner.apply(old, app_version=APP_VERSION)
        finally:
            runner.close()

        # Seed a connection + profile row against the 001-011 schema, then let
        # ModelProfileService run the pending 012 migration.
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "INSERT INTO provider_connections (name, provider_type, endpoint, "
                    "timeout_seconds) VALUES ('local', 'openai-compatible', "
                    "'http://localhost:8080/v1', 60)",
                )
                db.execute(
                    "INSERT INTO model_profiles (name, provider_connection_id, model_id, "
                    "template_version, output_protocol, context_budget, default_params, "
                    "capability_snapshot) VALUES ('general', 1, 'gpt-4o-mini', '1.0.0', "
                    "'json', '{}', '{}', '{}')",
                )
        finally:
            db.close()

        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            assert profiles.get_profile(1) is not None
            saved = profiles.set_prompt_override(1, _override_template())
            assert saved.parent_template_version == current_preset().version
            loaded = profiles.get_prompt_override(1)
            assert loaded is not None
            assert loaded.template_text == _override_template()

        runner = MigrationRunner.open(path)
        try:
            applied = [h["migration_id"] for h in runner.history()]
        finally:
            runner.close()
        assert "012_add_prompt_override" in applied


# --------------------------------------------------------------------------- #
# Override application service
# --------------------------------------------------------------------------- #


class TestPromptOverrideService:
    def test_set_get_clear_override(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        profile = _create_profile(path)
        assert profile.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            saved = profiles.set_prompt_override(profile.id, _override_template())
            assert saved.parent_template_version == current_preset().version
            loaded = profiles.get_prompt_override(profile.id)
            assert loaded is not None
            assert loaded.template_text == _override_template()
            assert profiles.clear_prompt_override(profile.id) is True
            assert profiles.get_prompt_override(profile.id) is None
            assert profiles.clear_prompt_override(profile.id) is False

    def test_override_reopens_after_new_service(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        profile = _create_profile(path)
        assert profile.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            profiles.set_prompt_override(profile.id, _override_template())
        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            loaded = profiles.get_prompt_override(profile.id)
            assert loaded is not None
            assert loaded.parent_template_version == current_preset().version
            assert loaded.template_text == _override_template()

    def test_unknown_variable_rejected_without_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        profile = _create_profile(path)
        assert profile.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            with pytest.raises(PromptOverrideError, match=r"\$bogus"):
                profiles.set_prompt_override(profile.id, "Translate $bogus.")
            assert profiles.get_prompt_override(profile.id) is None

    def test_missing_profile_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            with pytest.raises(Exception, match="does not exist"):
                profiles.set_prompt_override(999, _override_template())

    def test_profile_delete_cascades_override(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        profile = _create_profile(path)
        assert profile.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            profiles.set_prompt_override(profile.id, _override_template())
            assert profiles.get_prompt_override(profile.id) is not None
            assert profiles.delete_profile(profile.id) is True
            assert profiles.get_prompt_override(profile.id) is None


# --------------------------------------------------------------------------- #
# Render-time resolution (stale parent, boundary preservation)
# --------------------------------------------------------------------------- #


class TestResolveOverrideTemplate:
    def test_stale_parent_version_rejected(self) -> None:
        override = PromptOverride.create(
            model_profile_id=1,
            parent_template_version="0.0.1",
            template_text=_override_template(),
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        with pytest.raises(PromptOverrideError, match="based on template version"):
            resolve_override_template(override, current_preset())

    def test_unknown_variable_rejected_at_render_time(self) -> None:
        # A tampered/persisted override re-validates on render, so a bad record
        # cannot reach the model even if it bypassed save-time validation.
        override = PromptOverride(
            id=1,
            model_profile_id=1,
            parent_template_version=current_preset().version,
            template_text="Translate $bogus.",
            created_at=None,
            updated_at=None,
        )
        with pytest.raises(PromptOverrideError, match=r"\$bogus"):
            resolve_override_template(override, current_preset())

    def test_renderer_always_appends_output_contract(self) -> None:
        override = PromptOverride.create(
            model_profile_id=1,
            parent_template_version=current_preset().version,
            template_text="Translate $current with great formality.",
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        template = resolve_override_template(override, current_preset())
        renderer = PromptRenderer()
        result = renderer.render(
            profile_id="1",
            template_version="1.0.0",
            template=template,
            manifest=_manifest(),
            source_language="ja",
            target_language="zh",
        )
        assert "great formality" in result.prompt_text
        assert "---OUTPUT CONTRACT---" in result.prompt_text
        assert result.output_contract.items[0].segment_id == "seg-1"

    def test_no_override_uses_preset_template(self) -> None:
        renderer = PromptRenderer()
        result = renderer.render(
            profile_id="1",
            template_version="1.0.0",
            manifest=_manifest(),
            source_language="ja",
            target_language="zh",
        )
        assert "Translate the following text from ja to zh" in result.prompt_text


# --------------------------------------------------------------------------- #
# Translation vertical (override rendered + audited, stale fails closed)
# --------------------------------------------------------------------------- #


class TestTranslationServiceOverride:
    def test_override_used_in_prompt_and_audited(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profiles:
            profiles.set_prompt_override(profile.id, _override_template())
        adapter = RecordingAdapter([_valid_response(segments[0].stable_key, "こんにちは")])

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )

        assert adapter.last_request is not None
        prompt = adapter.last_request.messages[0].content
        assert "with great formality" in prompt
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run.id)
            assert len(attempts) == 1
            summary = attempts[0].context_summary
            assert summary["override_parent_version"] == current_preset().version

    def test_stale_override_rejected_before_request(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        # Simulate DB drift: an override whose parent version no longer matches
        # the current preset (e.g. after an app update).
        stale = PromptOverride.create(
            model_profile_id=profile.id,
            parent_template_version="0.0.1",
            template_text=_override_template(),
            allowed_placeholders=ALLOWED_PLACEHOLDERS,
        )
        repo = PromptOverrideRepository.open(path)
        try:
            repo.save(stale)
        finally:
            repo.close()
        adapter = RecordingAdapter([_valid_response(segments[0].stable_key, "こんにちは")])

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(PromptOverrideError, match="based on template version"):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )

        assert adapter.calls == 0
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            assert audit.list_attempts_for_run(run.id) == []

    def test_no_override_uses_preset_and_no_marker(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "Hello.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        adapter = RecordingAdapter([_valid_response(segments[0].stable_key, "こんにちは")])

        with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )

        assert adapter.last_request is not None
        prompt = adapter.last_request.messages[0].content
        assert "Translate the following text from ja to zh" in prompt
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run.id)
            assert "override_parent_version" not in attempts[0].context_summary


# --------------------------------------------------------------------------- #
# Workbench prompt editor widget
# --------------------------------------------------------------------------- #


class TestWorkbenchPromptEditor:
    def test_preset_preview_read_only_and_editor_seeded(self, qtbot: Any) -> None:
        preset_text = current_preset().template_text
        editor = WorkbenchPromptEditor(preset_text)
        qtbot.addWidget(editor)
        assert editor._preview.toPlainText() == preset_text
        assert editor._preview.isReadOnly()
        assert editor.text() == preset_text
        assert not editor._clear.isEnabled()

    def test_editor_seeded_with_override(self, qtbot: Any) -> None:
        editor = WorkbenchPromptEditor(
            current_preset().template_text,
            override_text=_override_template(),
            override_parent_version="1.0.0",
        )
        qtbot.addWidget(editor)
        assert editor.text() == _override_template()
        assert editor._clear.isEnabled()

    def test_save_and_clear_signals(self, qtbot: Any) -> None:
        editor = WorkbenchPromptEditor(
            current_preset().template_text,
            override_text=_override_template(),
        )
        qtbot.addWidget(editor)
        saved: list[str] = []
        cleared: list[bool] = []
        editor.save_requested.connect(saved.append)
        editor.clear_requested.connect(lambda: cleared.append(True))
        editor._editor.setPlainText("Translate $current softly.")
        editor._save.click()
        assert saved == ["Translate $current softly."]
        editor._clear.click()
        assert cleared == [True]

    def test_initial_draft_preserved(self, qtbot: Any) -> None:
        editor = WorkbenchPromptEditor(
            current_preset().template_text,
            initial="Translate $current with great formality.",
        )
        qtbot.addWidget(editor)
        assert editor.text() == "Translate $current with great formality."

    def test_stale_override_surfaces_warning(self, qtbot: Any) -> None:
        editor = WorkbenchPromptEditor(
            current_preset().template_text,
            override_text=_override_template(),
            override_parent_version="0.0.1",
            stale=True,
        )
        qtbot.addWidget(editor)
        assert "no longer matches" in editor._status.text()
        assert editor._clear.isEnabled()


# --------------------------------------------------------------------------- #
# pytest-qt: workbench prompt override surface
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


def _segments(db_path: Path, document_id: int) -> list[Segment]:
    repo = SegmentRepository.open(db_path)
    try:
        return repo.list_segments_by_document(document_id)
    finally:
        repo.close()


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


class TestTranslationPageWorkbenchOverride:
    def test_workbench_shows_prompt_editor_with_preset(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(
            lambda: translation._prompt_editor is not None,
            timeout=5000,
        )
        assert translation._prompt_editor is not None
        assert translation._prompt_editor._preview.isReadOnly()
        assert current_preset().template_text in translation._prompt_editor._preview.toPlainText()
        assert not translation._prompt_editor._clear.isEnabled()

    def test_save_override_persists_via_worker(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._prompt_editor is not None, timeout=5000)
        assert translation._active_profile_id is not None

        translation._prompt_editor._editor.setPlainText(_override_template())
        translation._prompt_editor._save.click()
        qtbot.waitUntil(
            lambda: "saved" in translation._status.text().lower(),
            timeout=5000,
        )
        with ModelProfileService(
            translation._db_path,
            app_version=APP_VERSION,
        ) as profiles:
            override = profiles.get_prompt_override(translation._active_profile_id)
            assert override is not None
            assert override.template_text == _override_template()
            assert override.parent_template_version == current_preset().version
        qtbot.waitUntil(
            lambda: translation._prompt_editor is not None
            and translation._prompt_editor._clear.isEnabled(),
            timeout=5000,
        )

    def test_save_override_unknown_var_shows_error_and_persists_nothing(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._prompt_editor is not None, timeout=5000)
        assert translation._active_profile_id is not None

        translation._prompt_editor._editor.setPlainText("Translate $bogus.")
        translation._prompt_editor._save.click()
        qtbot.waitUntil(
            lambda: "$bogus" in translation._status.text(),
            timeout=5000,
        )
        with ModelProfileService(
            translation._db_path,
            app_version=APP_VERSION,
        ) as profiles:
            assert profiles.get_prompt_override(translation._active_profile_id) is None

    def test_clear_override_returns_to_preset(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._prompt_editor is not None, timeout=5000)
        assert translation._active_profile_id is not None
        profile_id = translation._active_profile_id

        translation._prompt_editor._editor.setPlainText(_override_template())
        translation._prompt_editor._save.click()
        qtbot.waitUntil(
            lambda: translation._prompt_editor is not None
            and translation._prompt_editor._clear.isEnabled(),
            timeout=5000,
        )

        translation._prompt_editor._clear.click()
        qtbot.waitUntil(
            lambda: "cleared" in translation._status.text().lower(),
            timeout=5000,
        )
        with ModelProfileService(translation._db_path, app_version=APP_VERSION) as profiles:
            assert profiles.get_prompt_override(profile_id) is None
        qtbot.waitUntil(
            lambda: translation._prompt_editor is not None
            and not translation._prompt_editor._clear.isEnabled(),
            timeout=5000,
        )

    def test_stale_override_surfaces_warning_in_workbench(
        self,
        qtbot: Any,
        window_factory: Any,
        tmp_path: Path,
    ) -> None:
        window, _holder = window_factory()
        _setup_workbench_project(window, qtbot, tmp_path)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._prompt_editor is not None, timeout=5000)
        assert translation._active_profile_id is not None
        profile_id = translation._active_profile_id

        translation._prompt_editor._editor.setPlainText(_override_template())
        translation._prompt_editor._save.click()
        qtbot.waitUntil(
            lambda: translation._prompt_editor is not None
            and translation._prompt_editor._clear.isEnabled(),
            timeout=5000,
        )

        # Simulate a preset bump (e.g. an app update changed the preset version)
        # by corrupting the recorded parent version directly in the database.
        db = create_database(translation._db_path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE prompt_overrides SET parent_template_version = '0.0.1' "
                    "WHERE model_profile_id = ?",
                    (profile_id,),
                )
        finally:
            db.close()

        translation.refresh()
        qtbot.waitUntil(
            lambda: translation._prompt_editor is not None
            and "no longer matches" in translation._prompt_editor._status.text(),
            timeout=5000,
        )


# --------------------------------------------------------------------------- #
# Structural guard: the override path never executes template code
# --------------------------------------------------------------------------- #


class TestNoTemplateCodeExecution:
    def test_string_template_does_not_execute_code(self) -> None:
        import string

        template = string.Template("Translate $current.")
        assert not any(
            hasattr(template, name) for name in ("exec", "eval")
        )

    def test_override_modules_have_no_eval_or_exec(self) -> None:
        import inspect

        import transrealm.application.preset_templates as preset_module
        import transrealm.domain.prompt_override as domain_module

        for module in (preset_module, domain_module):
            assert "eval(" not in inspect.getsource(module)
            assert "exec(" not in inspect.getsource(module)
