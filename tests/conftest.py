"""Keep Qt test preferences beside each isolated, project-local test database."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(autouse=True)
def isolated_qt_preferences(tmp_path: Path) -> None:
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(tmp_path / "qt-settings"))
