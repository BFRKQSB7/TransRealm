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

    def _verify_backup(path: Path) -> None:
        normalized = _normalize_path(path)
        try:
            verify = sqlite3.connect(str(normalized))
        except sqlite3.Error as exc:
            raise MigrationBackupError(
                f"Backup is not a valid SQLite database: {exc}",
                path=path,
            ) from exc
        try:
            verify.execute("PRAGMA schema_version")
            verify.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise MigrationBackupError(
                f"Backup verification failed: {exc}",
                path=path,
            ) from exc
        finally:
            verify.close()

    backup_ok = False
    try:
        with dest:
            source_connection.backup(dest)
        _verify_backup(backup_path)
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
