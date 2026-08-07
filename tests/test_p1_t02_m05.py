"""P1-T02-M05: cross-machine and dual-form Gate (``04`` §7, ``03`` §3).

The full chain — open directory -> ``.aiproject`` -> an isolated "second
Windows" -> open directory — is exercised end to end. "Another Windows" is
simulated by a fresh, separate directory root; only the ``.aiproject`` archive
crosses the machine boundary, and no remote or paid service is involved. The
gate verifies:

- a cross-machine round trip preserves core state (project identity, segments,
  source documents with their fidelity carrier, provider connections with
  credential *references* only, profiles, translation runs, attachments);
- an old-schema (001-007) archive is forward-migrated on the target machine;
- credential-less recovery: a referenced ``env:``/``wincred:`` credential that
  is absent on the target machine is reported with an actionable hint and never
  leaks its value;
- a tamper/secret matrix across both forms (tampered container, tampered /
  truncated / traversal / bomb archives, tampered installed target, resource
  limits, target conflicts) fails before the target is touched.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from transrealm.adapters.credential_resolvers import (
    EnvironmentResolver,
    WindowsCredentialResolver,
    credential_reference_is_available,
)
from transrealm.adapters.errors import AdapterAuthenticationError
from transrealm.application.archive_service import (
    export_open_directory_archive,
    import_archive_to_staging,
)
from transrealm.application.credential_status import report_credential_availability
from transrealm.application.import_service import ImportService
from transrealm.application.install_service import (
    TargetConflictError,
    install_staging_to_target,
)
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.domain.model_profile import ModelCapability
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.open_directory import (
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_FORMAT_VERSION,
    ArchiveError,
    ArchiveLimitError,
    ArchiveLimits,
    FileIntegrityError,
    ManifestInfo,
    PathValidationError,
    compute_entry,
    remove_pre_upgrade_backups,
    write_archive,
    write_manifest,
)
from transrealm.infrastructure.repositories.translation_workflow_repository import (
    WorkflowDefinitionRepository,
)

APP_VERSION = "0.1.0"
_MIGRATION_008 = "008_add_format_fidelity"
_CRED_ENV = "TRANSLATOR_M05_MISSING_KEY"
_SECRET = "sk-m05-live-secret-value"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _apply_old_migrations(db_path: Path) -> None:
    """Apply migrations 001-007 only, simulating an older app version."""
    migs = discover_migrations(Path(__file__).parent.parent / "src"
                               / "transrealm" / "migrations")
    old = [m for m in migs if m.migration_id != _MIGRATION_008]
    db = create_database(db_path)
    try:
        MigrationRunner(db).apply(old, app_version=APP_VERSION)
    finally:
        db.close()


def _checkpoint_clean(db_path: Path) -> None:
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        raw.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _make_old_schema_db(db_path: Path, *, name: str, with_data: bool = False) -> int:
    """Create a database with only 001-007 applied plus one Project."""
    _apply_old_migrations(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.execute(
            "INSERT INTO projects "
            "(name, source_language, target_language, schema_version) "
            "VALUES (?, 'zh', 'en', 1)",
            (name,),
        )
        if cur.lastrowid is None:
            raise AssertionError("inserted project id was not assigned")
        project_id = int(cur.lastrowid)
        if with_data:
            doc = conn.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 'src.txt', 'txt', 'utf-8', 'hash', '1.0.0')",
                (project_id,),
            )
            conn.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence, status) "
                "VALUES (?, 'key-1', 'Hello', 0, 'pending')",
                (doc.lastrowid,),
            )
        conn.commit()
    finally:
        conn.close()
    _checkpoint_clean(db_path)
    return project_id


def _refresh_manifest(directory: Path) -> None:
    """Rewrite the manifest from the current database and declared attachments."""
    db_path = directory / DATABASE_FILENAME
    entries = [compute_entry(DATABASE_FILENAME, db_path, entry_type=CRITICAL_ENTRY_TYPE)]
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


def _add_attachment(
    directory: Path,
    *,
    relpath: str = "attachments/notes.txt",
    content: bytes = b"roundtrip attachment",
) -> None:
    source = directory / relpath
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    _refresh_manifest(directory)


def _db_rows(db_path: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _archive_names(archive_path: Path) -> list[str]:
    with zipfile.ZipFile(archive_path) as archive:
        return sorted(archive.namelist())


def _archive_bytes(archive_path: Path) -> bytes:
    with zipfile.ZipFile(archive_path) as archive:
        return b"".join(archive.read(name) for name in archive.namelist())


def _extract(archive_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(dest)


def _build_full_container(directory: Path, tmp_path: Path) -> tuple[int, str, str]:
    """Create a container with connection/profile/segments/run/attachment.

    Returns ``(project_id, connection_name, profile_name)``.
    """
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
        connection_name = connection.name
        assert connection.id is not None
        connection_id = connection.id
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
        profile_name = profile.name
    source = tmp_path / "src.txt"
    source.write_text("Hello world.\nSecond line.", encoding="utf-8")
    with ImportService(db_path, app_version=APP_VERSION) as svc:
        svc.import_txt(project_id, source, name="src.txt")
    seed = TranslationRunService(db_path, app_version=APP_VERSION)
    seed.close()
    workflow_repo = WorkflowDefinitionRepository.open(db_path)
    try:
        workflows = workflow_repo.list_all()
    finally:
        workflow_repo.close()
    assert workflows, "builtin workflow should be seeded"
    assert workflows[0].id is not None
    workflow_id = workflows[0].id
    run_service = TranslationRunService(db_path, app_version=APP_VERSION)
    try:
        run_service.create_run(project_id=project_id, workflow_id=workflow_id)
    finally:
        run_service.close()
    _checkpoint_clean(db_path)
    _add_attachment(directory)
    return project_id, connection_name, profile_name


def _rewrite_zip(
    src: Path,
    dst: Path,
    *,
    replace: dict[str, bytes] | None = None,
    drop: list[str] | None = None,
    extra: dict[str, bytes] | None = None,
) -> None:
    """Rebuild ``src`` as ``dst`` with members replaced, dropped, or added."""
    replace_map = replace or {}
    drop_set = set(drop or [])
    extra_map = extra or {}
    with zipfile.ZipFile(src) as reader:
        names = [name for name in reader.namelist() if name not in drop_set]
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as writer:
            for name in names:
                writer.writestr(name, replace_map.get(name, reader.read(name)))
            for name, data in extra_map.items():
                writer.writestr(name, data)


def _craft_archive(
    path: Path,
    *,
    files: dict[str, dict[str, object]],
    members: dict[str, bytes],
) -> None:
    """Write a hand-built archive with the given inner manifest ``files``."""
    manifest = {
        "format_version": 1,
        "schema_version": 1,
        "software": APP_VERSION,
        "files": files,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            MANIFEST_FILENAME,
            json.dumps(manifest, separators=(",", ":")).encode(),
        )
        for name, data in members.items():
            archive.writestr(name, data)


def _cross_machine_round_trip(
    tmp_path: Path,
    directory: Path,
) -> Path:
    """Export ``directory`` and import/install it on a simulated second machine.

    Returns the installed target container path.
    """
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


# ---------------------------------------------------------------------------
# cross-machine round trip — core state
# ---------------------------------------------------------------------------


def test_cross_machine_round_trip_preserves_core_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open dir -> archive -> second machine -> open dir keeps project state."""
    monkeypatch.delenv(_CRED_ENV, raising=False)
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    project_id, connection_name, profile_name = _build_full_container(
        directory,
        tmp_path,
    )
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    machine_b = tmp_path / "machine_b"
    machine_b.mkdir()
    staging = machine_b / "staging"
    import_archive_to_staging(archive, staging)
    target = machine_b / "project"
    install_staging_to_target(staging, target, app_version=APP_VERSION)

    with open_open_directory_project(target, app_version=APP_VERSION) as opened:
        assert opened.project.name == "Alpha"
        assert opened.project.source_language == "zh"
        assert opened.project.target_language == "en"
        assert opened.manifest.source_id == project_id
        db = target / DATABASE_FILENAME
        # segments and their fidelity carrier (008) survive
        segments = _db_rows(db, "SELECT source_text, sequence FROM segments "
                                "ORDER BY sequence")
        assert segments == [("Hello world.", 1), ("Second line.", 2)]
        assert all(
            row is not None
            for row in _db_rows(
                db,
                "SELECT raw_bytes, format_metadata FROM source_documents",
            )
        )
        # connections keep only references; profile and run state survive
        (cred_ref,) = _db_rows(
            db,
            "SELECT credential_reference FROM provider_connections "
            "WHERE name=?",
            connection_name,
        )[0]
        assert cred_ref == f"env:{_CRED_ENV}"
        assert _db_rows(db, "SELECT COUNT(*) FROM model_profiles WHERE name=?", profile_name)
        assert _db_rows(db, "SELECT COUNT(*) FROM translation_runs") == [(1,)]
        # attachment bytes match
        assert (target / "attachments" / "notes.txt").read_bytes() == (
            b"roundtrip attachment"
        )
        # the referenced credential is absent on this machine -> actionable hint
        with ProviderConnectionService(db, app_version=APP_VERSION) as svc:
            statuses = report_credential_availability(svc.list_connections())
        assert len(statuses) == 1
        assert statuses[0].available is False
        assert f"env:{_CRED_ENV}" in statuses[0].credential_reference
        assert "TRANSLATOR_M05_MISSING_KEY" in (statuses[0].hint or "")
        assert _SECRET not in (statuses[0].hint or "")


def test_cross_machine_reimport_from_installed_target(tmp_path: Path) -> None:
    """An installed target can itself be re-exported and re-imported."""
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    project_id, _, _ = _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    machine_b = tmp_path / "machine_b"
    machine_b.mkdir()
    staging = machine_b / "staging"
    import_archive_to_staging(archive, staging)
    target_b = machine_b / "project"
    install_staging_to_target(staging, target_b, app_version=APP_VERSION)

    machine_c = tmp_path / "machine_c"
    machine_c.mkdir()
    archive_c = machine_c / "alpha2.aiproject"
    export_open_directory_archive(target_b, archive_c, app_version=APP_VERSION)
    staging_c = machine_c / "staging"
    import_archive_to_staging(archive_c, staging_c)
    target_c = machine_c / "project"
    install_staging_to_target(staging_c, target_c, app_version=APP_VERSION)
    with open_open_directory_project(target_c, app_version=APP_VERSION) as opened:
        assert opened.project.name == "Alpha"
        assert _db_rows(
            target_c / DATABASE_FILENAME,
            "SELECT COUNT(*) FROM segments",
        ) == [(2,)]
        assert (target_c / "attachments" / "notes.txt").read_bytes() == (
            b"roundtrip attachment"
        )


def test_old_schema_archive_migrates_on_cross_machine_install(tmp_path: Path) -> None:
    """A 001-007 archive is forward-migrated (with backup) on the target machine."""
    container = tmp_path / "old_container"
    container.mkdir()
    db_path = container / DATABASE_FILENAME
    _make_old_schema_db(db_path, name="Legacy", with_data=True)
    # the fresh-empty pre-upgrade backup of the old migration run is a transient
    # artifact, not part of a clean container
    remove_pre_upgrade_backups(container)
    write_manifest(
        container,
        ManifestInfo(
            MANIFEST_FORMAT_VERSION,
            1,
            APP_VERSION,
            (compute_entry(DATABASE_FILENAME, db_path, entry_type=CRITICAL_ENTRY_TYPE),),
        ),
    )
    archive = tmp_path / "legacy.aiproject"
    write_archive(container, archive)

    machine_b = tmp_path / "machine_b"
    machine_b.mkdir()
    staging = machine_b / "staging"
    import_archive_to_staging(archive, staging)
    target = machine_b / "project"
    install_staging_to_target(staging, target, app_version=APP_VERSION)
    with open_open_directory_project(target, app_version=APP_VERSION) as opened:
        assert opened.project.name == "Legacy"
        db = target / DATABASE_FILENAME
        assert _db_rows(db, "SELECT migration_id FROM schema_migrations "
                            "WHERE migration_id=?", _MIGRATION_008)
        assert _db_rows(db, "SELECT COUNT(*) FROM source_documents") == [(1,)]
        assert _db_rows(db, "SELECT COUNT(*) FROM segments") == [(1,)]
    # the migrated container holds only its declared entries
    assert not list(target.glob("*.pre-upgrade-*.db.bak"))
    assert not list(target.glob("project.sqlite-wal"))
    assert not list(target.glob("project.sqlite-shm"))


# ---------------------------------------------------------------------------
# credential-less recovery (04 §7 actionable hint)
# ---------------------------------------------------------------------------


def test_report_flags_missing_env_credential_with_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_CRED_ENV, raising=False)
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    target = _cross_machine_round_trip(tmp_path, directory)
    with ProviderConnectionService(
        target / DATABASE_FILENAME,
        app_version=APP_VERSION,
    ) as svc:
        statuses = report_credential_availability(svc.list_connections())
    assert len(statuses) == 1
    assert statuses[0].connection_name == "openai"
    assert statuses[0].credential_reference == f"env:{_CRED_ENV}"
    assert statuses[0].available is False
    assert "environment variable 'TRANSLATOR_M05_MISSING_KEY'" in (
        statuses[0].hint or ""
    )


def test_report_available_when_env_credential_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_CRED_ENV, _SECRET)
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    target = _cross_machine_round_trip(tmp_path, directory)
    with ProviderConnectionService(
        target / DATABASE_FILENAME,
        app_version=APP_VERSION,
    ) as svc:
        statuses = report_credential_availability(svc.list_connections())
    assert statuses[0].available is True
    assert statuses[0].hint is None
    assert _SECRET not in statuses[0].credential_reference


def test_report_skips_connections_without_credential() -> None:
    from transrealm.domain.provider_connection import ProviderConnection

    plain = ProviderConnection(
        id=1,
        name="local",
        provider_type="openai-compatible",
        endpoint="https://example.invalid/v1",
        timeout_seconds=30,
        max_retries=0,
        retry_delay_seconds=0.0,
        credential_reference=None,
        created_at=None,
        updated_at=None,
    )
    assert report_credential_availability([plain]) == []


def test_report_wincred_missing_flags_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        WindowsCredentialResolver,
        "_credential_exists",
        lambda self, target: False,
    )
    assert credential_reference_is_available("wincred:App/TransRealm") is False
    from transrealm.domain.provider_connection import ProviderConnection

    connection = ProviderConnection(
        id=1,
        name="w",
        provider_type="openai-compatible",
        endpoint="https://example.invalid/v1",
        timeout_seconds=30,
        max_retries=0,
        retry_delay_seconds=0.0,
        credential_reference="wincred:App/TransRealm",
        created_at=None,
        updated_at=None,
    )
    statuses = report_credential_availability([connection])
    assert len(statuses) == 1
    assert statuses[0].available is False
    assert "App/TransRealm" in (statuses[0].hint or "")


def test_report_wincred_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        WindowsCredentialResolver,
        "_credential_exists",
        lambda self, target: True,
    )
    assert credential_reference_is_available("wincred:App/TransRealm") is True
    from transrealm.domain.provider_connection import ProviderConnection

    connection = ProviderConnection(
        id=1,
        name="w",
        provider_type="openai-compatible",
        endpoint="https://example.invalid/v1",
        timeout_seconds=30,
        max_retries=0,
        retry_delay_seconds=0.0,
        credential_reference="wincred:App/TransRealm",
        created_at=None,
        updated_at=None,
    )
    status = report_credential_availability([connection])[0]
    assert status.available is True
    assert status.hint is None
    assert _SECRET not in status.credential_reference


def test_empty_credential_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty secret is treated as missing so the target gets a hint, not a 401."""
    monkeypatch.setenv(_CRED_ENV, "")
    assert credential_reference_is_available(f"env:{_CRED_ENV}") is False


def test_none_and_unknown_reference_availability() -> None:
    assert credential_reference_is_available(None) is True
    assert credential_reference_is_available("other:thing") is False


def test_report_never_leaks_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_CRED_ENV, _SECRET)
    from transrealm.domain.provider_connection import ProviderConnection

    connection = ProviderConnection(
        id=1,
        name="openai",
        provider_type="openai-compatible",
        endpoint="https://example.invalid/v1",
        timeout_seconds=30,
        max_retries=0,
        retry_delay_seconds=0.0,
        credential_reference=f"env:{_CRED_ENV}",
        created_at=None,
        updated_at=None,
    )
    status = report_credential_availability([connection])[0]
    assert status.available is True
    assert _SECRET not in status.credential_reference
    assert status.hint is None


def test_resolver_error_is_actionable_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_CRED_ENV, raising=False)
    with pytest.raises(AdapterAuthenticationError) as excinfo:
        asyncio.run(EnvironmentResolver().resolve(f"env:{_CRED_ENV}"))
    message = str(excinfo.value)
    assert "TRANSLATOR_M05_MISSING_KEY" in message
    assert _SECRET not in message


# ---------------------------------------------------------------------------
# secret matrix
# ---------------------------------------------------------------------------


def test_round_trip_archive_and_target_hold_only_credential_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_CRED_ENV, _SECRET)
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    assert _SECRET.encode() not in _archive_bytes(archive)
    target = _cross_machine_round_trip(tmp_path, directory)
    assert _SECRET.encode() not in _archive_bytes(archive)
    (cred_ref,) = _db_rows(
        target / DATABASE_FILENAME,
        "SELECT credential_reference FROM provider_connections",
    )[0]
    assert cred_ref == f"env:{_CRED_ENV}"


def test_undeclared_secret_files_never_cross_machine(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    (directory / "credentials.json").write_text(
        json.dumps({"api_key": _SECRET}),
        encoding="utf-8",
    )
    (directory / "app.log").write_text("debug noise", encoding="utf-8")
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    assert _SECRET.encode() not in _archive_bytes(archive)
    assert "app.log" not in _archive_names(archive)
    target = _cross_machine_round_trip(tmp_path, directory)
    names = [p.name for p in target.iterdir()]
    assert "credentials.json" not in names
    assert "app.log" not in names


# ---------------------------------------------------------------------------
# tamper matrix
# ---------------------------------------------------------------------------


def test_tampered_open_directory_refuses_export(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    (directory / "attachments" / "notes.txt").write_bytes(b"tampered")
    archive = directory.parent / "out.aiproject"
    with pytest.raises(FileIntegrityError):
        export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    assert not archive.exists()


def test_tampered_attachment_archive_refuses_import(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    tampered = tmp_path / "tampered.aiproject"
    _rewrite_zip(archive, tampered, replace={"attachments/notes.txt": b"EVIL"})
    staging = tmp_path / "staging"
    with pytest.raises(FileIntegrityError):
        import_archive_to_staging(tampered, staging)
    assert not staging.exists() or not any(staging.iterdir())


def test_missing_attachment_member_refuses_import(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    missing = tmp_path / "missing.aiproject"
    _rewrite_zip(archive, missing, drop=["attachments/notes.txt"])
    staging = tmp_path / "staging"
    with pytest.raises(FileIntegrityError):
        import_archive_to_staging(missing, staging)
    assert not staging.exists() or not any(staging.iterdir())


def test_manifest_hash_tamper_refuses_import(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    with zipfile.ZipFile(archive) as reader:
        manifest = json.loads(reader.read(MANIFEST_FILENAME).decode("utf-8"))
    manifest["files"]["attachments/notes.txt"]["hash"] = "sha256:" + "0" * 64
    forged = tmp_path / "forged.aiproject"
    _rewrite_zip(
        archive,
        forged,
        replace={
            MANIFEST_FILENAME: json.dumps(
                manifest,
                separators=(",", ":"),
            ).encode(),
        },
    )
    staging = tmp_path / "staging"
    with pytest.raises(FileIntegrityError):
        import_archive_to_staging(forged, staging)
    assert not staging.exists() or not any(staging.iterdir())


def test_truncated_archive_refuses_import(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    data = archive.read_bytes()
    truncated = tmp_path / "truncated.aiproject"
    truncated.write_bytes(data[: len(data) // 2])
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveError):
        import_archive_to_staging(truncated, staging)
    assert not staging.exists() or not any(staging.iterdir())


def test_undeclared_member_archive_refuses_import(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    smuggled = tmp_path / "smuggled.aiproject"
    _rewrite_zip(archive, smuggled, extra={"extra.txt": b"not declared"})
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveError):
        import_archive_to_staging(smuggled, staging)
    assert not staging.exists() or not any(staging.iterdir())


def test_traversal_archive_refuses_import(tmp_path: Path) -> None:
    evil = tmp_path / "evil.aiproject"
    _craft_archive(
        evil,
        files={
            DATABASE_FILENAME: {
                "type": "database",
                "size": 0,
                "hash": "sha256:" + "0" * 64,
            },
            "../escape.txt": {
                "type": "attachment",
                "size": 1,
                "hash": "sha256:" + "0" * 64,
            },
        },
        members={"../escape.txt": b"x"},
    )
    staging = tmp_path / "staging"
    with pytest.raises(PathValidationError):
        import_archive_to_staging(evil, staging)
    assert not staging.exists() or not any(staging.iterdir())


def test_overlimit_archive_refuses_import(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    staging = tmp_path / "staging"
    limits = ArchiveLimits(max_total_size=1)
    with pytest.raises(ArchiveLimitError):
        import_archive_to_staging(archive, staging, limits=limits)
    assert not staging.exists() or not any(staging.iterdir())


def test_tampered_installed_target_fails_open(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    target = _cross_machine_round_trip(tmp_path, directory)
    (target / "attachments" / "notes.txt").write_bytes(b"tampered")
    with pytest.raises(FileIntegrityError):
        open_open_directory_project(target, app_version=APP_VERSION)


# ---------------------------------------------------------------------------
# target conflicts and WAL consistency
# ---------------------------------------------------------------------------


def test_same_name_target_conflict_suggests_name_and_preserves_target(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    _build_full_container(directory, tmp_path)
    _cross_machine_round_trip(tmp_path, directory)
    # a second container with the same name exists where the user wants to install
    other = tmp_path / "machine_b" / "other_alpha"
    with create_open_directory_project(
        other,
        name="Alpha",
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ):
        pass
    staging = tmp_path / "machine_b" / "staging2"
    import_archive_to_staging(tmp_path / "machine_a" / "alpha.aiproject", staging)
    with pytest.raises(TargetConflictError) as excinfo:
        install_staging_to_target(staging, other, app_version=APP_VERSION)
    assert excinfo.value.suggested_name == "Alpha (2)"
    # the existing target is preserved untouched
    with open_open_directory_project(other, app_version=APP_VERSION) as opened:
        assert opened.project.name == "Alpha"
    assert _db_rows(other / DATABASE_FILENAME, "SELECT COUNT(*) FROM segments") == [(0,)]


def test_confirmed_overwrite_replaces_target_with_recovery_backup(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    project_id, _, _ = _build_full_container(directory, tmp_path)
    archive = directory.parent / "alpha.aiproject"
    export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    other = tmp_path / "machine_b" / "existing"
    with create_open_directory_project(
        other,
        name="Alpha",
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ):
        pass
    staging = tmp_path / "machine_b" / "staging"
    import_archive_to_staging(archive, staging)
    install_staging_to_target(
        staging,
        other,
        app_version=APP_VERSION,
        confirm_overwrite=True,
    )
    with open_open_directory_project(other, app_version=APP_VERSION) as opened:
        assert opened.project.name == "Alpha"
        assert opened.manifest.source_id == project_id
        assert _db_rows(other / DATABASE_FILENAME, "SELECT COUNT(*) FROM segments") == [(2,)]
    backups = list((tmp_path / "machine_b").glob(".existing.pre-replace-*.bak"))
    assert len(backups) == 1
    assert backups[0].is_dir()


def test_pending_wal_write_does_not_cross_machine(tmp_path: Path) -> None:
    directory = tmp_path / "machine_a" / "project"
    directory.parent.mkdir()
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ):
        pass
    raw = sqlite3.connect(str(directory / DATABASE_FILENAME))
    try:
        raw.execute(
            "INSERT INTO projects (name, source_language, target_language) "
            "VALUES ('Draft', 'x', 'y')",
        )  # deliberately not committed
        archive = directory.parent / "alpha.aiproject"
        export_open_directory_archive(directory, archive, app_version=APP_VERSION)
    finally:
        raw.rollback()
        raw.close()
    target = _cross_machine_round_trip(tmp_path, directory)
    assert _db_rows(
        target / DATABASE_FILENAME,
        "SELECT name FROM projects ORDER BY id",
    ) == [("Alpha",)]
