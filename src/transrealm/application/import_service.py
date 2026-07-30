"""Import application service."""

from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.parsers.parser import ParserRegistry, default_registry
from transrealm.infrastructure.repositories.project_repository import ProjectRepository
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository


class ImportService:
    """Application service for importing source documents into a Project."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(
        self,
        db_path: Path,
        *,
        app_version: str,
        parser_registry: ParserRegistry | None = None,
    ) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._parser_registry = (
            parser_registry if parser_registry is not None else default_registry()
        )
        self._db = create_database(db_path)
        self._project_repository = ProjectRepository(self._db)
        self._segment_repository = SegmentRepository(self._db)
        self._run_migrations()

    def _run_migrations(self) -> None:
        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

    def import_file(
        self,
        project_id: int,
        file_path: Path,
        *,
        format: str | None = None,  # noqa: A002
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Import a source file into a Project using the registered parser.

        If a source document with the same hash already exists for the project,
        the existing document is returned and no new segments are created.
        """
        file_format = format or file_path.suffix.lstrip(".").lower()
        parser = self._parser_registry.get(file_format)
        document, segments = parser.parse(
            file_path,
            project_id=project_id,
            name=name,
            encoding=encoding,
        )

        return self._segment_repository.import_document(document, segments)

    def import_txt(
        self,
        project_id: int,
        file_path: Path,
        *,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Convenience method to import a TXT file."""
        return self.import_file(
            project_id,
            file_path,
            format="txt",
            name=name,
            encoding=encoding,
        )

    def close(self) -> None:
        """Close the service and release resources."""
        self._segment_repository.close()

    def __enter__(self) -> "ImportService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
