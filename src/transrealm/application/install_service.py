"""Forward migration and atomic install of Project containers (P1-T02-M04).

A Project container — an open directory or the M03 isolated staging snapshot —
is validated, backed up by the P0-T03-M00 seam, forward-migrated, and validated
again before it is opened in place or atomically installed as a new target
(``03`` §3, ``04`` §7). On failure the original target is preserved and the
recovery artifacts (a pre-upgrade backup for an in-place migration, the source
archive for an install) remain available.

Two entry points:

- ``migrate_container`` prepares an open-directory container in place: manifest
  and entry validation, forward migration through
  ``ProjectService``/``MigrationRunner`` (which creates the pre-upgrade backup),
  then sidecar/backup cleanup and manifest regeneration so the container stays
  to its declared entries. The container's Project identity is unchanged.
- ``install_staging_to_target`` migrates an M03 staging container and atomically
  installs it as the open-directory Project at ``target_dir``. A target that
  already holds a Project is never overwritten without explicit confirmation;
  a same-name conflict suggests a deterministic-suffix name, and a confirmed
  overwrite preserves the replaced container in a ``.pre-replace`` recovery
  backup. The installed manifest records the source/origin Project id
  (``source_id``) so the local identity remains traceable to its origin.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from transrealm.application.open_directory_service import open_open_directory_project
from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.open_directory import (
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    OpenDirectoryError,
    check_container_identity,
    cleanup_after_container_migration,
    load_manifest,
    purge_sqlite_sidecars,
    regenerate_manifest,
    validate_manifest,
    verify_entries,
)

__all__ = [
    "InstallError",
    "TargetConflictError",
    "install_staging_to_target",
    "migrate_container",
]


class InstallError(OpenDirectoryError):
    """Project container migration or install failed."""


class TargetConflictError(InstallError):
    """The install target already holds a Project that would be overwritten.

    ``suggested_name`` carries a deterministic-suffix name for the imported
    Project when the conflict is a same-name collision; it is ``None`` when the
    existing Project has a different name (replacement still requires explicit
    confirmation).
    """

    def __init__(self, message: str, *, suggested_name: str | None = None) -> None:
        super().__init__(message)
        self.suggested_name = suggested_name


def migrate_container(directory: Path, *, app_version: str) -> Path:
    """Forward-migrate an open-directory container in place and return it.

    Validates the container, applies pending migrations through the
    ``ProjectService``/``MigrationRunner`` seam (which creates the P0-T03-M00
    pre-upgrade backup before the first pending migration), then removes the
    transient sidecars/backup and regenerates the manifest for the migrated
    database so the container holds only its declared entries and reopens
    correctly. When no migration is pending the container is left untouched.
    On migration failure the error propagates and the container keeps its
    pre-upgrade backup for the recovery action.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise InstallError(f"Container is not a directory: {directory}")
    manifest = load_manifest(directory)
    validate_manifest(manifest)
    verify_entries(directory, manifest)
    db_path = directory / DATABASE_FILENAME
    check_container_identity(db_path, manifest)
    with ProjectService(db_path, app_version=app_version) as service:
        projects = service.list_projects()
        if len(projects) != 1:
            raise InstallError(
                f"Container must hold exactly one Project; found {len(projects)}.",
            )
        applied = service.applied_migrations
        schema_version = projects[0].schema_version
    if applied:
        cleanup_after_container_migration(directory, schema_version=schema_version)
        manifest = load_manifest(directory)
        validate_manifest(manifest)
        verify_entries(directory, manifest)
    return directory


def install_staging_to_target(
    staging_dir: Path,
    target_dir: Path,
    *,
    app_version: str,
    confirm_overwrite: bool = False,
) -> Path:
    """Forward-migrate a staging container and atomically install it as ``target_dir``.

    ``staging_dir`` must be a validated open-directory container (the M03
    isolated staging snapshot). It is migrated (backup + forward migration +
    cleanup + manifest regeneration), its Project id is recorded as the manifest
    ``source_id`` for origin tracking, and the resulting container is atomically
    installed at ``target_dir`` (built in a sibling temp directory, validated,
    then renamed into place). An empty/new target is installed into directly. A
    target already holding a Project is refused unless ``confirm_overwrite`` is
    true: a same-name conflict raises ``TargetConflictError`` with a suggested
    deterministic-suffix name; a different-name container also requires
    confirmation. A confirmed overwrite moves the existing target aside to a
    ``.pre-replace`` recovery backup before installing. Any failure leaves the
    target untouched (or restores it) and removes the temp artifacts.

    Returns ``target_dir``.
    """
    staging_dir = Path(staging_dir)
    target_dir = Path(target_dir)
    if not staging_dir.is_dir():
        raise InstallError(f"Staging is not a directory: {staging_dir}")
    migrate_container(staging_dir, app_version=app_version)
    source_name, source_id = _read_source_identity(staging_dir / DATABASE_FILENAME)
    manifest = load_manifest(staging_dir)
    if manifest.source_id != source_id:
        regenerate_manifest(
            staging_dir,
            schema_version=manifest.schema_version,
            source_id=source_id,
        )
    state, existing_name = _target_state(target_dir)
    if state == "other":
        raise InstallError(
            f"Target directory is not empty and is not a project container; "
            f"refusing to overwrite: {target_dir}",
        )
    if state == "container" and not confirm_overwrite:
        if existing_name == source_name:
            raise TargetConflictError(
                f"Target already contains a Project named {existing_name!r}; "
                f"refusing to overwrite without explicit confirmation.",
                suggested_name=f"{existing_name} (2)",
            )
        raise TargetConflictError(
            f"Target contains a different Project named {existing_name!r}; "
            f"refusing to overwrite without explicit confirmation.",
            suggested_name=None,
        )
    try:
        temp = Path(
            tempfile.mkdtemp(prefix=f".{target_dir.name}.install-", dir=target_dir.parent),
        )
    except OSError as exc:
        raise InstallError(f"Cannot create install staging area: {exc}") from exc
    try:
        shutil.copytree(staging_dir, temp, dirs_exist_ok=True)
        _validate_container(temp, app_version=app_version)
        if state in ("new", "empty"):
            if state == "empty":
                target_dir.rmdir()
            os.rename(temp, target_dir)
        else:
            recovery = _recovery_backup_path(target_dir)
            shutil.move(str(target_dir), str(recovery))
            try:
                os.rename(temp, target_dir)
            except Exception as exc:
                try:
                    shutil.move(str(recovery), str(target_dir))
                except Exception as restore_exc:
                    raise InstallError(
                        f"Install failed ({exc}) and the previous container could not "
                        f"be restored; recover it from {recovery}.",
                    ) from restore_exc
                raise
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return target_dir


def _read_source_identity(db_path: Path) -> tuple[str, int]:
    """Return (name, id) of the single Project in the staging container."""
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        raise InstallError(f"Cannot read source project identity: {exc}") from exc
    try:
        conn.execute("PRAGMA query_only = ON")
        row = conn.execute("SELECT name, id FROM projects LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise InstallError(f"Cannot read source project identity: {exc}") from exc
    finally:
        conn.close()
    if row is None:
        raise InstallError("Staging container holds no Project.")
    return str(row[0]), int(row[1])


def _target_state(target_dir: Path) -> tuple[str, str | None]:
    """Classify the install target: ``new``, ``empty``, ``container``, or ``other``."""
    if not target_dir.exists():
        return ("new", None)
    if not target_dir.is_dir():
        raise InstallError(f"Target path is not a directory: {target_dir}")
    try:
        has_entries = any(target_dir.iterdir())
    except OSError as exc:
        raise InstallError(f"Cannot inspect target directory: {exc}") from exc
    if not has_entries:
        return ("empty", None)
    name = _read_container_project_name(target_dir)
    if name is None:
        return ("other", None)
    return ("container", name)


def _read_container_project_name(directory: Path) -> str | None:
    """Return the Project name of a valid container, or None if not one.

    Read-only: the container is validated structurally and the name read without
    running migrations or mutating the target.
    """
    if not (directory / MANIFEST_FILENAME).is_file():
        return None
    try:
        manifest = load_manifest(directory)
        validate_manifest(manifest)
        verify_entries(directory, manifest)
    except OpenDirectoryError:
        return None
    try:
        conn = sqlite3.connect(str(directory / DATABASE_FILENAME))
    except sqlite3.Error:
        return None
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute("SELECT name FROM projects ORDER BY id").fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if len(rows) != 1:
        return None
    return str(rows[0][0])


def _validate_container(directory: Path, *, app_version: str) -> None:
    """Run the full open-directory validation on a staged install container."""
    with open_open_directory_project(directory, app_version=app_version):
        pass
    purge_sqlite_sidecars(directory / DATABASE_FILENAME)


def _recovery_backup_path(target_dir: Path) -> Path:
    """Return a unique ``.``-prefixed recovery backup path next to ``target_dir``."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = target_dir.parent / f".{target_dir.name}.pre-replace-{timestamp}.bak"
    suffix = 1
    while candidate.exists():
        candidate = target_dir.parent / (
            f".{target_dir.name}.pre-replace-{timestamp}-{suffix}.bak"
        )
        suffix += 1
    return candidate
