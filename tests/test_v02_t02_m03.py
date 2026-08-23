"""V02-T02-M03 acceptance for the Project deletion UI."""

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QSettings

from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.database import create_database, transaction
from transrealm.ui.main_window import MainWindow

APP_VERSION = "0.0.0-test"


@pytest.fixture
def window_factory(qtbot: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a MainWindow with isolated settings and a temporary database."""
    settings_path = tmp_path / "settings.ini"
    created: list[MainWindow] = []

    def make() -> MainWindow:
        settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
        window = MainWindow(
            tmp_path / "project.sqlite",
            app_version=APP_VERSION,
            settings=settings,
        )
        qtbot.addWidget(window)
        created.append(window)
        return window

    yield make
    for window in created:
        window.shutdown()


def _create_project(qtbot: Any, window: MainWindow, name: str = "Demo") -> None:
    project = window._project
    project._project_name.setText(name)
    project._create_project.click()
    qtbot.waitUntil(lambda: project._project_id is not None, timeout=5000)
    qtbot.waitUntil(
        lambda: name in project._delete_summary_label.text(),
        timeout=5000,
    )


def _add_running_run(db_path: Path, project_id: int) -> None:
    db = create_database(db_path)
    try:
        with transaction(db):
            workflow = db.execute(
                "INSERT INTO workflow_definitions "
                "(name, origin, version, definition_json, definition_hash) "
                "VALUES (?, 'builtin', '1.0', '{}', ?)",
                (f"ui-workflow-{project_id}", f"ui-hash-{project_id}"),
            )
            assert workflow.lastrowid is not None
            db.execute(
                "INSERT INTO translation_runs "
                "(project_id, workflow_id, workflow_version, workflow_definition_hash, status) "
                "VALUES (?, ?, '1.0', ?, 'running')",
                (project_id, workflow.lastrowid, f"ui-hash-{project_id}"),
            )
    finally:
        db.close()


def test_delete_requires_exact_name_and_clears_translation_context(
    qtbot: Any,
    window_factory: Any,
    tmp_path: Path,
) -> None:
    window = window_factory()
    _create_project(qtbot, window)
    project = window._project
    assert project._project_id is not None
    project_id = project._project_id

    assert "0 source document(s)" in project._delete_summary_label.text()
    project.delete_project("wrong")
    qtbot.waitUntil(
        lambda: "exact Project name" in project._status.text(),
        timeout=5000,
    )
    with ProjectService(tmp_path / "project.sqlite", app_version=APP_VERSION) as service:
        assert service.get_project(project_id) is not None

    project.delete_project("Demo")
    qtbot.waitUntil(
        lambda: "Project deleted" in project._status.text(),
        timeout=5000,
    )
    qtbot.waitUntil(lambda: project._project_id is None, timeout=5000)
    qtbot.waitUntil(lambda: window._translation._project_id is None, timeout=5000)
    with ProjectService(tmp_path / "project.sqlite", app_version=APP_VERSION) as service:
        assert service.get_project(project_id) is None


def test_delete_running_project_shows_actionable_worker_error(
    qtbot: Any,
    window_factory: Any,
    tmp_path: Path,
) -> None:
    window = window_factory()
    _create_project(qtbot, window, name="Busy")
    project = window._project
    assert project._project_id is not None
    _add_running_run(tmp_path / "project.sqlite", project._project_id)
    project.refresh()
    qtbot.waitUntil(
        lambda: "1 running Run(s)" in project._delete_summary_label.text(),
        timeout=5000,
    )

    project.delete_project("Busy")
    qtbot.waitUntil(
        lambda: "cannot be deleted" in project._status.text(),
        timeout=5000,
    )
    assert project._project_id is not None
    assert list((tmp_path).glob("*.project-delete-*.db.bak")) == []


def test_delete_controls_retranslate_between_english_and_chinese(
    qtbot: Any,
    window_factory: Any,
) -> None:
    window = window_factory()
    project = window._project
    assert project._delete_project.text() == "Delete Project"
    window._i18n.set_language("zh_CN")
    qtbot.waitUntil(lambda: project._delete_project.text() == "删除项目", timeout=5000)
    qtbot.waitUntil(
        lambda: project._delete_confirmation.placeholderText() == "输入项目名称以确认",
        timeout=5000,
    )
    assert project._delete_summary_label is not None
    window._i18n.set_language("en")
    qtbot.waitUntil(lambda: project._delete_project.text() == "Delete Project", timeout=5000)
    qtbot.waitUntil(
        lambda: project._delete_confirmation.placeholderText() == "Type Project name to confirm",
        timeout=5000,
    )
