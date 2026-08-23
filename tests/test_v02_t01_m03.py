"""M03 acceptance for Qt i18n, language persistence, and package resources."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox, QLabel, QTabWidget

from transrealm.ui.i18n import LanguageManager
from transrealm.ui.main_window import MainWindow


def _settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


def test_language_manager_persists_and_falls_back_safely(
    qtbot: object,
    tmp_path: Path,
) -> None:
    del qtbot
    settings = _settings(tmp_path)
    manager = LanguageManager(settings=settings)

    assert manager.current_language == "en"
    assert manager.set_language("zh_CN") == "zh_CN"
    assert manager.current_language == "zh_CN"
    assert manager.tr("Settings") == "设置"
    assert settings.value("language") == "zh_CN"

    assert manager.set_language("unsupported") == "en"
    assert manager.current_language == "en"
    assert manager.tr("Settings") == "Settings"
    assert settings.value("language") == "en"


def test_main_window_retranslates_shell_and_persists_language(
    qtbot: object,
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    window = MainWindow(
        tmp_path / "project.sqlite",
        app_version="0.0.0-test",
        settings=settings,
    )
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    try:
        tabs = window.findChild(QTabWidget, "main-tabs")
        title = window.findChild(QLabel, "app-title")
        language = window.findChild(QComboBox, "language-selector")
        assert tabs is not None
        assert title is not None
        assert language is not None
        assert title.text() == "TransRealm"
        assert [tabs.tabText(index) for index in range(tabs.count())] == [
            "Settings",
            "Project",
            "Translation",
        ]

        language.setCurrentIndex(language.findData("zh_CN"))
        assert window._i18n.current_language == "zh_CN"
        assert title.text() == "译境"
        assert [tabs.tabText(index) for index in range(tabs.count())] == [
            "设置",
            "项目",
            "翻译",
        ]
        assert settings.value("language") == "zh_CN"

        window._i18n.set_language("en")
        assert title.text() == "TransRealm"
        assert settings.value("language") == "en"
    finally:
        window.shutdown()


def test_translation_resources_are_packaged_by_release_script() -> None:
    resource_dir = Path(__file__).parents[1] / "src" / "transrealm" / "ui" / "i18n"
    assert (resource_dir / "transrealm_en.ts").is_file()
    assert (resource_dir / "transrealm_en.qm").is_file()
    assert (resource_dir / "transrealm_zh_CN.ts").is_file()
    assert (resource_dir / "transrealm_zh_CN.qm").is_file()

    build_script = (resource_dir.parents[3] / "scripts" / "build_release.py").read_text(
        encoding="utf-8",
    )
    assert "transrealm/ui/i18n" in build_script
    assert "translation_files" in build_script
    assert "frozen_translation_names" in build_script
