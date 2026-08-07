"""P1-T04-M05: persistence / dual-form / GUI Gate.

The Gate verifies that the P1-T04 additions — ``projects.active_profile_id``
(``009`` migration) and the ``glossary_entries`` table (``010`` migration) —
persist across restarts and survive both Project forms end to end:

- restart persistence: a container re-opened in place keeps the active Profile
  selection and the Glossary entries;
- dual-form round trip: open directory -> ``.aiproject`` -> an isolated
  "second Windows" -> install -> re-open preserves ``active_profile_id`` and
  the glossary rows (source/target/scope/priority/is_locked), keeps the
  credential as a reference only, and the locked entries remain injectable via
  ``list_locked_entries``;
- the existing P1-T02-M05 state (profile / connection reference / segments /
  attachments) still survives the same chain, re-verified here with the
  P1-T04 data present.

Budget and UI regressions are covered by the M03 and M04 suites; this file only
adds the double-form + restart evidence that the ``009``/``010`` data flows
through the shared SQLite carrier.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from transrealm.application.archive_service import (
    export_open_directory_archive,
    import_archive_to_staging,
)
from transrealm.application.glossary_service import GlossaryService
from transrealm.application.import_service import ImportService
from transrealm.application.install_service import install_staging_to_target
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.domain.glossary_entry import GlossaryEntry
from transrealm.domain.model_profile import ModelCapability
from transrealm.infrastructure.open_directory import (
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_FORMAT_VERSION,
    ManifestInfo,
    compute_entry,
    write_manifest,
)

APP_VERSION = "0.1.0"
_CRED_ENV = "TRANSLATOR_M05_P1T04_KEY"


def _checkpoint_clean(db_path: Path) -> None:
    """Flush WAL and drop the sidecar files so the container is tidy."""
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        raw.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _refresh_manifest(directory: Path) -> None:
    """Rewrite the manifest from the current database contents."""
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


def _db_rows(db_path: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _build_container(
    directory: Path,
    tmp_path: Path,
) -> tuple[int, str, str, list[int], int]:
    """Create a container with active Profile + Glossary + segments.

    Returns ``(project_id, connection_name, profile_name, entry_ids,
    profile_id)``.
    """
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
        connection_id = connection.id
        connection_name = connection.name

    with ModelProfileService(db_path, app_version=APP_VERSION) as svc:
        profile = svc.create_profile(
            name="default",
            provider_connection_id=connection_id,
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
        profile_name = profile.name

    with ProjectService(db_path, app_version=APP_VERSION) as svc:
        svc.select_active_profile(project_id, profile_id)

    entry_ids: list[int] = []
    with GlossaryService(db_path, app_version=APP_VERSION) as svc:
        for gloss_source, target, scope, priority, locked in (
            ("Apple", "苹果", "noun", 90, True),
            ("Banana", "香蕉", "noun", 10, False),
            ("Paris", "巴黎", "place", 70, True),
        ):
            entry = svc.create_entry(
                project_id=project_id,
                source_term=gloss_source,
                target_term=target,
                scope=scope,
                priority=priority,
                is_locked=locked,
            )
            assert entry.id is not None
            entry_ids.append(entry.id)

    source = tmp_path / "src.txt"
    source.write_text("Hello world.\nSecond line.", encoding="utf-8")
    with ImportService(db_path, app_version=APP_VERSION) as svc:
        svc.import_txt(project_id, source, name="src.txt")

    _checkpoint_clean(db_path)
    _refresh_manifest(directory)
    return project_id, connection_name, profile_name, entry_ids, profile_id


def _cross_machine_round_trip(directory: Path, tmp_path: Path) -> Path:
    """Export ``directory`` and import/install it on a simulated second machine."""
    machine_a = tmp_path / "machine_a"
    machine_b = tmp_path / "machine_b"
    machine_a.mkdir(parents=True, exist_ok=True)
    machine_b.mkdir(parents=True, exist_ok=True)
    archive = machine_a / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    staging = machine_b / "staging"
    import_archive_to_staging(archive, staging)
    target = machine_b / "project"
    install_staging_to_target(staging, target, app_version=APP_VERSION)
    return target


def _assert_selection_and_glossary(
    db_path: Path,
    *,
    project_id: int,
    profile_id: int,
    profile_name: str,
    entry_ids: list[int],
    connection_name: str,
) -> None:
    """Assert the P1-T04 data survived at ``db_path``."""
    with ProjectService(db_path, app_version=APP_VERSION) as svc:
        project = svc.open_project()
        assert project is not None
        assert project.id == project_id
        assert project.active_profile_id == profile_id
        # The profile row itself survived the round trip.
        (stored_profile,) = _db_rows(
            db_path,
            "SELECT name FROM model_profiles WHERE id=?",
            profile_id,
        )
        assert stored_profile[0] == profile_name

    with GlossaryService(db_path, app_version=APP_VERSION) as svc:
        entries = svc.list_entries(project_id)
        assert {entry.id for entry in entries} == set(entry_ids)
        # Deterministic priority DESC, id order survives the round trip.
        assert [entry.source_term for entry in entries] == [
            "Apple",
            "Paris",
            "Banana",
        ]
        by_source = {entry.source_term: entry for entry in entries}
        apple = by_source["Apple"]
        assert isinstance(apple, GlossaryEntry)
        assert apple.target_term == "苹果"
        assert apple.scope == "noun"
        assert apple.priority == 90
        assert apple.is_locked is True
        assert by_source["Banana"].is_locked is False
        assert by_source["Paris"].priority == 70
        locked = svc.list_locked_entries(project_id)
        assert {entry.source_term for entry in locked} == {"Apple", "Paris"}

    (cred_ref,) = _db_rows(
        db_path,
        "SELECT credential_reference FROM provider_connections WHERE name=?",
        connection_name,
    )[0]
    assert cred_ref == f"env:{_CRED_ENV}"


def test_dual_form_round_trip_preserves_selection_and_glossary(
    tmp_path: Path,
) -> None:
    """Open dir -> archive -> second machine -> open dir keeps P1-T04 data."""
    directory = tmp_path / "machine_a" / "project"
    project_id, connection_name, profile_name, entry_ids, profile_id = (
        _build_container(directory, tmp_path)
    )

    target = _cross_machine_round_trip(directory, tmp_path)

    with open_open_directory_project(target, app_version=APP_VERSION) as opened:
        assert opened.project.name == "Alpha"
        assert opened.project.id == project_id
        # segments survive alongside the P1-T04 data.
        assert _db_rows(
            target / DATABASE_FILENAME,
            "SELECT source_text, sequence FROM segments ORDER BY sequence",
        ) == [("Hello world.", 1), ("Second line.", 2)]

    _assert_selection_and_glossary(
        target / DATABASE_FILENAME,
        project_id=project_id,
        profile_id=profile_id,
        profile_name=profile_name,
        entry_ids=entry_ids,
        connection_name=connection_name,
    )


def test_open_directory_reopen_preserves_selection_and_glossary(
    tmp_path: Path,
) -> None:
    """Reopening the open-directory form restores active Profile + Glossary."""
    directory = tmp_path / "project"
    project_id, connection_name, profile_name, entry_ids, profile_id = (
        _build_container(directory, tmp_path)
    )

    with open_open_directory_project(directory, app_version=APP_VERSION) as opened:
        assert opened.project.id == project_id

    _assert_selection_and_glossary(
        directory / DATABASE_FILENAME,
        project_id=project_id,
        profile_id=profile_id,
        profile_name=profile_name,
        entry_ids=entry_ids,
        connection_name=connection_name,
    )
