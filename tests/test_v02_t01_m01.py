"""M01 structural acceptance for the UI page split."""

from __future__ import annotations

from pathlib import Path

from transrealm.ui.page_base import WorkerPage
from transrealm.ui.pages import ProjectPage, SettingsPage, TranslationPage
from transrealm.ui.project_page import ProjectPage as ProjectPageModule
from transrealm.ui.settings_page import SettingsPage as SettingsPageModule
from transrealm.ui.translation_page import TranslationPage as TranslationPageModule


def test_page_classes_have_separate_responsibility_modules() -> None:
    assert WorkerPage.__module__ == "transrealm.ui.page_base"
    assert SettingsPageModule.__module__ == "transrealm.ui.settings_page"
    assert ProjectPageModule.__module__ == "transrealm.ui.project_page"
    assert TranslationPageModule.__module__ == "transrealm.ui.translation_page"


def test_pages_module_preserves_compatibility_reexports() -> None:
    assert SettingsPage is SettingsPageModule
    assert ProjectPage is ProjectPageModule
    assert TranslationPage is TranslationPageModule


def test_legacy_pages_facade_contains_no_page_class_definitions() -> None:
    source = (Path(__file__).parents[1] / "src" / "transrealm" / "ui" / "pages.py").read_text(
        encoding="utf-8",
    )
    assert "class SettingsPage" not in source
    assert "class ProjectPage" not in source
    assert "class TranslationPage" not in source
