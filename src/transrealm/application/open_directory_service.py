"""Open-directory Project lifecycle: create and reopen a container.

An open-directory Project is a directory holding ``manifest.json`` +
``project.sqlite`` (see ``03`` §3 and ``04`` §7). Creating one initializes the
SQLite database through the existing ``ProjectService``/``MigrationRunner``
seam (including the P0-T03-M00 pre-upgrade backup) and then writes the
manifest. Opening one is fail-closed: the manifest and every declared entry
are validated before the database is opened, and exactly one Project identity
is required.

The open directory is not a second database or a watcher-synced workspace; the
manifest is authoritative and only declared entries are part of the container.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from transrealm.application.project_service import ProjectService
from transrealm.domain.project import Project
from transrealm.infrastructure.open_directory import (
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    ManifestError,
    ManifestInfo,
    OpenDirectoryError,
    check_container_identity,
    cleanup_after_container_migration,
    compute_entry,
    load_manifest,
    remove_pre_upgrade_backups,
    validate_manifest,
    verify_entries,
    write_manifest,
)

__all__ = [
    "OpenDirectoryProject",
    "create_open_directory_project",
    "open_open_directory_project",
]


class OpenDirectoryProject:
    """An opened open-directory Project container (context manager)."""

    def __init__(
        self,
        directory: Path,
        service: ProjectService,
        manifest: ManifestInfo,
    ) -> None:
        self._directory = directory
        self._service = service
        self._manifest = manifest
        self._project: Project | None = None

    @property
    def directory(self) -> Path:
        """The container directory."""
        return self._directory

    @property
    def db_path(self) -> Path:
        """Path to the container's SQLite database."""
        return self._directory / DATABASE_FILENAME

    @property
    def manifest(self) -> ManifestInfo:
        """The validated manifest of the container."""
        return self._manifest

    @property
    def project(self) -> Project:
        """The single Project identity held by the container."""
        if self._project is None:
            project = self._service.open_project()
            if project is None:
                raise OpenDirectoryError("Container contains no Project.")
            self._project = project
        return self._project

    def close(self) -> None:
        """Close the underlying database and release resources."""
        self._service.close()

    def __enter__(self) -> OpenDirectoryProject:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def create_open_directory_project(
    directory: Path,
    *,
    name: str,
    source_language: str,
    target_language: str,
    app_version: str,
) -> OpenDirectoryProject:
    """Create a new open-directory Project at ``directory``.

    The directory must not already contain a project; creating into a
    non-empty directory is refused so existing files are never overwritten.
    """
    directory = Path(directory)
    created_dir = _prepare_directory(directory)
    db_path = directory / DATABASE_FILENAME
    try:
        _initialize_database(
            db_path,
            name=name,
            source_language=source_language,
            target_language=target_language,
            app_version=app_version,
        )
        _finalize_database_file(db_path)
        entry = compute_entry(DATABASE_FILENAME, db_path, entry_type=CRITICAL_ENTRY_TYPE)
        manifest = ManifestInfo(
            format_version=1,
            schema_version=1,
            software=app_version,
            entries=(entry,),
        )
        validate_manifest(manifest)
        write_manifest(directory, manifest)
    except Exception:
        _cleanup_failed_create(directory, created_dir=created_dir)
        raise
    return open_open_directory_project(directory, app_version=app_version)


def open_open_directory_project(directory: Path, *, app_version: str) -> OpenDirectoryProject:
    """Validate and open an open-directory Project.

    An old-schema container (a forward migration is pending) is migrated in
    place through the ``ProjectService``/``MigrationRunner`` seam — which first
    creates the P0-T03-M00 pre-upgrade backup — then cleaned (sidecars and the
    transient backup removed) and its manifest regenerated for the migrated
    database, so the container stays to its declared entries and reopens
    correctly.

    Raises:
        OpenDirectoryError: If the directory is missing or not a directory.
        ManifestError: If the manifest is invalid, unsupported, or the database
            schema does not match.
        PathValidationError: If an entry escapes the root, is a link, or
            collides after normalization.
        FileIntegrityError: If a declared entry is missing or fails size/hash
            verification.
        MigrationBackupError / MigrationExecutionError / MigrationChecksumError:
            If a pending migration's backup or execution fails; the container
            is left with its recovery backup for the recovery action.
    """
    directory = Path(directory)
    if not directory.exists():
        raise OpenDirectoryError(f"Project directory does not exist: {directory}")
    if not directory.is_dir():
        raise OpenDirectoryError(f"Project path is not a directory: {directory}")
    manifest = load_manifest(directory)
    validate_manifest(manifest)
    verify_entries(directory, manifest)
    db_path = directory / DATABASE_FILENAME
    check_container_identity(db_path, manifest)
    # The first connection runs pending migrations (creating the pre-upgrade
    # backup) and is closed so its WAL is checkpointed into the main database
    # file before any cleanup.
    service = ProjectService(db_path, app_version=app_version)
    try:
        projects = service.list_projects()
        applied = bool(service.applied_migrations)
        schema_version = projects[0].schema_version if projects else manifest.schema_version
    finally:
        service.close()
    if not projects:
        raise OpenDirectoryError("Container database contains no Project.")
    if len(projects) != 1:
        raise OpenDirectoryError(
            f"Container must hold exactly one Project; found {len(projects)}.",
        )
    if applied:
        manifest = cleanup_after_container_migration(
            directory,
            schema_version=schema_version,
        )
        validate_manifest(manifest)
        verify_entries(directory, manifest)
    service = ProjectService(db_path, app_version=app_version)
    try:
        projects = service.list_projects()
        if not projects:
            raise OpenDirectoryError("Container database contains no Project.")
        if len(projects) != 1:
            raise OpenDirectoryError(
                f"Container must hold exactly one Project; found {len(projects)}.",
            )
        if projects[0].schema_version != manifest.schema_version:
            raise ManifestError(
                f"Manifest schema_version {manifest.schema_version} does not match "
                f"the database schema_version {projects[0].schema_version}.",
            )
    except Exception:
        service.close()
        raise
    return OpenDirectoryProject(directory, service, manifest)


def _prepare_directory(directory: Path) -> bool:
    """Ensure ``directory`` exists and is empty; return whether we created it."""
    if directory.exists():
        if not directory.is_dir():
            raise OpenDirectoryError(f"Project path is not a directory: {directory}")
        try:
            has_entries = any(directory.iterdir())
        except OSError as exc:
            raise OpenDirectoryError(
                f"Cannot inspect project directory: {exc}",
            ) from exc
        if has_entries:
            raise OpenDirectoryError(
                f"Project directory is not empty; refusing to overwrite: {directory}",
            )
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OpenDirectoryError(f"Cannot create project directory: {exc}") from exc
    return True


def _initialize_database(
    db_path: Path,
    *,
    name: str,
    source_language: str,
    target_language: str,
    app_version: str,
) -> None:
    with ProjectService(db_path, app_version=app_version) as service:
        service.create_project(
            name=name,
            source_language=source_language,
            target_language=target_language,
        )
    _remove_pre_upgrade_backup(db_path)


def _remove_pre_upgrade_backup(db_path: Path) -> None:
    """Remove the fresh-empty pre-upgrade backup from initializing a new DB.

    ``ProjectService`` creates a P0-T03-M00 pre-upgrade backup before the first
    migration. For a newly initialized container that backup only protects an
    empty pre-migration database, so it is removed to keep the container to the
    declared entries (manifest.json + project.sqlite).
    """
    remove_pre_upgrade_backups(db_path.parent)


def _finalize_database_file(db_path: Path) -> None:
    """Fold any WAL content into the main database file and remove sidecars.

    Sidecars are only removed after a successful checkpoint; if the checkpoint
    fails, the WAL is left untouched so committed rows are never lost.
    """
    checkpointed = False
    try:
        raw = sqlite3.connect(str(db_path))
        try:
            raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            checkpointed = True
        finally:
            raw.close()
    except sqlite3.Error:
        pass
    if not checkpointed:
        return
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{db_path}{suffix}")
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass


def _cleanup_failed_create(directory: Path, *, created_dir: bool) -> None:
    """Best-effort removal of artifacts created by a failed create.

    The directory was empty before create, so every entry present is an
    artifact of this operation. The directory itself is only removed when this
    create made it.
    """
    try:
        for entry in list(directory.iterdir()):
            try:
                entry.unlink()
            except OSError:
                pass
        if created_dir:
            directory.rmdir()
    except OSError:
        pass
