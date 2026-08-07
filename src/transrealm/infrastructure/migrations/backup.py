"""Pre-upgrade SQLite backup using the SQLite backup API."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from transrealm.infrastructure.migrations.errors import MigrationBackupError


def _normalize_path(path: Path) -> Path:
    """Resolve and, on Windows, prefix long paths with \\?\\ when needed."""
    absolute = path.resolve()
    if os.name == "nt" and not absolute.drive.startswith("\\\\"):
        str_path = str(absolute)
        if len(str_path) > 260 and not str_path.startswith("\\\\?\\"):
            return Path("\\\\?\\" + str_path)
    return absolute


def _generate_backup_path(db_path: Path) -> Path:
    """Return a discoverable backup path next to the source database.

    The path includes an ISO-8601 UTC timestamp. If a collision occurs (e.g.
    two backups in the same second), a numeric suffix is appended.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parent = db_path.parent
    stem = db_path.stem
    candidate = parent / f"{stem}.pre-upgrade-{timestamp}.db.bak"
    if not candidate.exists():
        return candidate

    suffix = 1
    while True:
        candidate = parent / f"{stem}.pre-upgrade-{timestamp}-{suffix}.db.bak"
        if not candidate.exists():
            return candidate
        suffix += 1


def create_pre_upgrade_backup(
    source_connection: sqlite3.Connection,
    db_path: Path,
) -> Path:
    """Create a consistent, openable backup of ``db_path`` before migration.

    Uses ``sqlite3.Connection.backup``, which is safe while WAL is active and
    does not require direct file copying. The backup is reopened and queried to
    verify it is a valid SQLite database before returning.

    Args:
        source_connection: Open connection to the database being upgraded.
        db_path: Path to the database being upgraded (used for error context
            and backup naming).

    Returns:
        Path to the created backup file.

    Raises:
        MigrationBackupError: If the backup cannot be created, written, or
            verified as a valid SQLite database.
    """
    backup_path = _generate_backup_path(db_path)

    try:
        backup_path.touch(exist_ok=False)
    except OSError as exc:
        raise MigrationBackupError(
            f"Cannot create backup file: {exc}",
            path=backup_path,
        ) from exc

    normalized_backup = _normalize_path(backup_path)

    try:
        dest = sqlite3.connect(str(normalized_backup))
    except sqlite3.Error as exc:
        raise MigrationBackupError(
            f"Cannot open backup database: {exc}",
            path=backup_path,
        ) from exc

    backup_ok = False
    try:
        with dest:
            source_connection.backup(dest)
        _verify_openable_sqlite(
            backup_path,
            open_message="Backup is not a valid SQLite database: {exc}",
            verify_message="Backup verification failed: {exc}",
        )
        backup_ok = True
    except MigrationBackupError:
        raise
    except sqlite3.Error as exc:
        raise MigrationBackupError(
            f"SQLite backup failed: {exc}",
            path=backup_path,
        ) from exc
    except OSError as exc:
        raise MigrationBackupError(
            f"Backup I/O failed: {exc}",
            path=backup_path,
        ) from exc
    finally:
        dest.close()
        if not backup_ok and backup_path.exists():
            try:
                backup_path.unlink()
            except OSError:
                pass

    return backup_path


def _verify_openable_sqlite(
    path: Path,
    *,
    open_message: str,
    verify_message: str,
) -> None:
    """Reopen ``path`` and assert it is a valid SQLite database.

    ``open_message`` / ``verify_message`` are ``str.format`` templates receiving
    ``exc`` (the open failure / query failure respectively), so callers control
    the user-facing error wording.
    """
    normalized = _normalize_path(path)
    try:
        verify = sqlite3.connect(str(normalized))
    except sqlite3.Error as exc:
        raise MigrationBackupError(open_message.format(exc=exc), path=path) from exc
    try:
        verify.execute("PRAGMA schema_version")
        verify.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise MigrationBackupError(verify_message.format(exc=exc), path=path) from exc
    finally:
        verify.close()


def create_consistent_snapshot(db_path: Path, target_path: Path) -> Path:
    """Create a consistent, openable snapshot of ``db_path`` at ``target_path``.

    Uses the SQLite backup API (the same mechanism as
    ``create_pre_upgrade_backup``), so the snapshot is consistent even while WAL
    is active; ``db_path`` is never copied as a raw file. The snapshot is
    reopened and verified before returning. ``target_path``'s parent must
    already exist; an existing file at ``target_path`` is removed first.

    Args:
        db_path: Source database path.
        target_path: Where to write the snapshot.

    Returns:
        The snapshot path.

    Raises:
        MigrationBackupError: If the snapshot cannot be created or verified.
    """
    db_path = Path(db_path)
    target_path = Path(target_path)
    if not db_path.is_file():
        raise MigrationBackupError(
            f"Source database does not exist: {db_path}",
            path=db_path,
        )
    target_path.unlink(missing_ok=True)
    source: sqlite3.Connection | None = None
    dest: sqlite3.Connection | None = None
    backup_ok = False
    try:
        source = sqlite3.connect(str(_normalize_path(db_path)))
        dest = sqlite3.connect(str(_normalize_path(target_path)))
        with dest:
            source.backup(dest)
        _verify_openable_sqlite(
            target_path,
            open_message="Snapshot is not a valid SQLite database: {exc}",
            verify_message="Snapshot verification failed: {exc}",
        )
        backup_ok = True
    except sqlite3.Error as exc:
        raise MigrationBackupError(
            f"SQLite snapshot failed: {exc}",
            path=target_path,
        ) from exc
    except OSError as exc:
        raise MigrationBackupError(
            f"Snapshot I/O failed: {exc}",
            path=target_path,
        ) from exc
    finally:
        if dest is not None:
            dest.close()
        if source is not None:
            source.close()
        if not backup_ok:
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                pass
    return target_path
