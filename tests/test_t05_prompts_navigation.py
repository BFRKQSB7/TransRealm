"""Three-page product, prompt persistence, version fencing and credential safety."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractButton, QGroupBox

from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.preset_templates import current_preset
from transrealm.application.prompt_library_service import PromptLibraryService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_facade import TranslationFacade
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.prompt_override import PromptOverrideError
from transrealm.ui.main_window import MainWindow

VERSION = "0.2.0-test"


def seed_model(db: Path) -> int:
    with ProviderConnectionService(db, app_version=VERSION) as service:
        connection = service.create_connection(
            name="Local provider",
            provider_type="openai-compatible",
            endpoint="http://127.0.0.1:9876/v1",
            timeout_seconds=3,
            max_retries=0,
            retry_delay_seconds=0,
            credential_reference="env:TRANSREALM_T05_TEST_KEY",
        )
    assert connection.id is not None
    with ModelProfileService(db, app_version=VERSION) as service:
        model = service.create_profile(
            name="Local model",
            provider_connection_id=connection.id,
            model_id="test-model",
            template_version=current_preset().version,
            output_protocol="json",
            capability=ModelCapability(8192, 1024, False, False, {"temperature", "max_tokens"}),
        )
    assert model.id is not None
    return model.id


def test_named_library_lifecycle_uses_override_and_preserves_applied_text(tmp_path: Path) -> None:
    db = tmp_path / "job.sqlite"
    model_id = seed_model(db)
    library = PromptLibraryService(db, app_version=VERSION)
    preset = current_preset()
    prompt = library.copy_preset("First copy")
    assert prompt.template_text == preset.template_text
    edited = library.update(
        prompt.template_id, name="Renamed", template_text=preset.template_text + "Keep names.\n"
    )
    library.apply(model_id, edited.template_id)
    saved = library.model_prompt(model_id)
    assert saved is not None and saved.template_text == edited.template_text
    assert saved.parent_template_version == preset.version
    library.delete(edited.template_id)
    assert PromptLibraryService(db, app_version=VERSION).list_templates() == []
    assert library.model_prompt(model_id) == saved
    assert current_preset() == preset
    library.apply(model_id, None)
    assert library.model_prompt(model_id) is None


def test_invalid_stale_corrupt_and_failed_write_preserve_existing_prompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "job.sqlite"
    model_id = seed_model(db)
    library = PromptLibraryService(db, app_version=VERSION)
    prompt = library.copy_preset("Valid")
    library.apply(model_id, prompt.template_id)
    original = library.path.read_bytes()
    with pytest.raises(PromptOverrideError):
        library.update(prompt.template_id, name="Invalid", template_text="$execute_this")
    assert library.path.read_bytes() == original
    with monkeypatch.context() as context:

        def fail_replace(*_args: object) -> None:
            raise OSError("simulated disk failure")

        context.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError):
            library.copy_preset("Cannot save")
    assert library.path.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))
    payload = json.loads(original)
    payload["templates"][0]["parent_template_version"] = "0.0.0"
    library.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PromptOverrideError, match="older preset"):
        library.apply(model_id, prompt.template_id)
    override = library.model_prompt(model_id)
    assert override is not None and override.parent_template_version == current_preset().version
    library.path.write_bytes(b"broken private settings")
    with pytest.raises(PromptOverrideError, match="could not be read"):
        library.copy_preset("Must not erase")
    assert library.path.read_bytes() == b"broken private settings"


def test_library_instances_do_not_lose_parallel_copies(tmp_path: Path) -> None:
    db = tmp_path / "job.sqlite"

    def copy(index: int) -> str:
        prompt = PromptLibraryService(db, app_version=VERSION).copy_preset(f"Copy {index}")
        return prompt.template_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(copy, range(12)))
    prompts = PromptLibraryService(db, app_version=VERSION).list_templates()
    assert {item.template_id for item in prompts} == set(ids)


def make_window(qtbot: Any, tmp_path: Path) -> MainWindow:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("language", "en")
    window = MainWindow(tmp_path / "job.sqlite", app_version=VERSION, settings=settings)
    qtbot.addWidget(window)
    if os.environ.get("QT_QPA_PLATFORM") == "windows":
        window.show()
        qtbot.waitExposed(window)
    return window


def test_prompt_ui_copy_edit_rename_select_delete_and_legacy_model_editor(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    db = tmp_path / "job.sqlite"
    model_id = seed_model(db)
    with TranslationFacade(db, app_version=VERSION) as facade:
        job = facade.create_job(name="Legacy job", source_language="en", target_language="zh")
        assert job.id is not None
        facade.select_active_profile(job.id, model_id)
    window = make_window(qtbot, tmp_path)
    try:
        page = window._prompts
        qtbot.waitUntil(lambda: page._list.count() == 1)
        assert page._editor.isReadOnly()
        window._translation._manage_prompts.click()
        assert window._tabs.currentIndex() == 2
        page._copy.click()
        page._name.setText("Custom")
        text = current_preset().template_text + "Use natural language.\n"
        page._editor.setPlainText(text)
        page._save.click()
        qtbot.waitUntil(lambda: page._list.count() == 2)
        page._list.setCurrentRow(1)
        page._name.setText("Renamed prompt")
        page._editor.setPlainText(text + "Preserve names.\n")
        edited = page._editor.toPlainText()
        page.refresh()
        assert page._editor.toPlainText() == edited  # Navigation cannot discard the draft.
        page._save.click()
        qtbot.waitUntil(lambda: page._list.item(1).text() == "Renamed prompt")
        window._tabs.setCurrentIndex(0)
        translation = window._translation
        qtbot.waitUntil(lambda: translation._prompt_combo.count() == 2)
        translation._prompt_combo.setCurrentIndex(1)
        translation._on_prompt_selected(1)
        library = PromptLibraryService(db, app_version=VERSION)
        qtbot.waitUntil(lambda: library.model_prompt(model_id) is not None)
        assert library.model_prompt(model_id).template_text == edited  # type: ignore[union-attr]
        window._tabs.setCurrentIndex(2)
        qtbot.waitUntil(lambda: page._model_editor is not None)
        model_section = next(
            section
            for section in page.findChildren(QGroupBox)
            if section.title() == "Current model prompt"
        )
        model_section.setChecked(True)
        page._list.setCurrentRow(1)
        page._delete.click()
        qtbot.waitUntil(lambda: page._list.count() == 1)
        assert library.model_prompt(model_id).template_text == edited  # type: ignore[union-attr]
        qtbot.waitUntil(
            lambda: page._model_editor is not None
            and page._model_host.isEnabled()
            and page._model_editor._clear.isEnabled()
            and page._model_editor.text() == edited
        )
        assert page._model_editor is not None
        page._model_editor._clear.click()
        qtbot.waitUntil(lambda: library.model_prompt(model_id) is None)
        qtbot.waitUntil(lambda: page._model_host.isEnabled())
        page._model_editor._editor.setPlainText(text)
        page._model_editor._save.click()
        qtbot.waitUntil(lambda: library.model_prompt(model_id) is not None)
    finally:
        window.shutdown()
    reopened = make_window(qtbot, tmp_path)
    try:
        qtbot.waitUntil(lambda: reopened._translation._active_profile_id == model_id)
        qtbot.waitUntil(lambda: reopened._translation._prompt_combo.currentData() == "current")
        assert PromptLibraryService(db, app_version=VERSION).model_prompt(model_id) is not None
    finally:
        reopened.shutdown()


@pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "windows",
    reason="Native Windows GUI evidence run.",
)
def test_native_three_pages_languages_credentials_and_dpi(
    qtbot: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "t05-runtime-secret-never-rendered"
    monkeypatch.setenv("TRANSREALM_T05_TEST_KEY", secret)
    seed_model(tmp_path / "job.sqlite")
    window = make_window(qtbot, tmp_path)
    evidence = Path(os.environ["TRANSREALM_GUI_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        qtbot.waitUntil(lambda: window._providers._connections_list.count() == 1)
        window._providers._connections_list.setCurrentRow(0)
        assert window._providers._conn_credential.text() == "env:TRANSREALM_T05_TEST_KEY"
        window._providers._conn_credential.setText(secret)
        window._providers._save_connection.click()
        assert window._providers._conn_credential.text() == ""
        assert secret not in window._providers._status.text()
        for language, labels in (
            ("en", ["Translation", "Providers", "Prompts"]),
            ("zh_CN", ["翻译", "模型提供商", "提示词"]),
        ):
            window._i18n.set_language(language)
            assert [window._tabs.tabText(index) for index in range(3)] == labels
            for index in range(3):
                window._tabs.setCurrentIndex(index)
                qtbot.wait(100)
                assert window.grab().save(str(evidence / f"page-{index}-{language}.png"))
                for button in window.findChildren(QAbstractButton):
                    if button.isVisible() and button.text():
                        assert secret not in button.text()
                        assert button.width() >= button.fontMetrics().horizontalAdvance(
                            button.text()
                        )
            window._tabs.setCurrentIndex(1)
            window._providers._sections.setCurrentIndex(1)
            qtbot.wait(100)
            assert window.grab().save(str(evidence / f"models-{language}.png"))
            assert window._providers.findChild(QGroupBox, "profiles-section") is not None
        (evidence / "t05-platform.json").write_text(
            json.dumps(
                {
                    "platform": QGuiApplication.platformName(),
                    "device_pixel_ratio": window.devicePixelRatio(),
                    "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
                    "languages": ["en", "zh_CN"],
                    "pages": 3,
                }
            ),
            encoding="utf-8",
        )
    finally:
        window.shutdown()
