"""Migration discovery and metadata."""

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    """A discovered SQL migration."""

    migration_id: str
    path: Path
    sql: str
    checksum: str

    @classmethod
    def from_file(cls, path: Path) -> "Migration":
        """Load a migration from a SQL file.

        The migration_id is derived from the file stem.
        """
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        return cls(
            migration_id=path.stem,
            path=path,
            sql=sql,
            checksum=checksum,
        )


def discover_migrations(directory: Path) -> list[Migration]:
    """Discover and sort SQL migrations from a directory.

    Files are sorted lexicographically by filename. A consistent naming scheme
    (e.g., 001_init.sql) keeps migrations ordered.
    """
    if not directory.exists():
        return []
    migrations = [
        Migration.from_file(path)
        for path in directory.glob("*.sql")
        if path.is_file()
    ]
    return sorted(migrations, key=lambda m: m.path.name)
