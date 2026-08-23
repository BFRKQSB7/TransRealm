"""Compatibility facade for the split desktop page modules.

New code should import each page from its responsibility module. The legacy
``transrealm.ui.pages`` imports remain stable for existing callers and tests.
"""

from transrealm.ui.page_base import WorkerPage
from transrealm.ui.project_page import ProjectPage
from transrealm.ui.settings_page import SettingsPage
from transrealm.ui.translation_page import TranslationPage

__all__ = [
    "ProjectPage",
    "SettingsPage",
    "TranslationPage",
    "WorkerPage",
]
