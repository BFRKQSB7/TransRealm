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

    def backfill_fidelity(
        self,
        source_document_id: int,
        file_path: Path,
        *,
        encoding: str = "utf-8",
    ) -> SourceDocument:
        """Explicitly add the fidelity carrier to a document that lacks it.

        Old TXT projects migrated before fidelity existed have no preserved
        original bytes, and the original bytes must never be guessed from
        ``source_text``. This path is the only way to fill the carrier: the
        user provides the original file, which is re-parsed; the source hash
        and the existing segment mapping (count, stable_key, source_text,
        sequence) must match before the raw bytes and envelope are persisted
        in a single transaction.

        Raises:
            ValueError: If the document does not exist, the file's hash does
                not match, or the re-parsed segment mapping differs.
        """
        document = self._segment_repository.get_source_document_by_id(
            source_document_id,
        )
        if document is None:
            raise ValueError(
                f"SourceDocument with id {source_document_id} does not exist.",
            )
        parser = self._parser_registry.get(document.format)
        parsed_document, parsed_segments = parser.parse(
            file_path,
            project_id=document.project_id,
            name=document.name,
            encoding=encoding,
        )
        if parsed_document.source_hash != document.source_hash:
            raise ValueError(
                "Provided file does not match the source document hash; "
                "refusing to backfill fidelity data.",
            )
        existing = self._segment_repository.list_segments_by_document(
            source_document_id,
        )
        if len(existing) != len(parsed_segments):
            raise ValueError(
                "Provided file's segment mapping does not match the document; "
                "refusing to backfill fidelity data.",
            )
        for old, new in zip(existing, parsed_segments):
            if (
                old.stable_key != new.stable_key
                or old.source_text != new.source_text
                or old.sequence != new.sequence
            ):
                raise ValueError(
                    "Provided file's segment mapping does not match the document; "
                    "refusing to backfill fidelity data.",
                )
        return self._segment_repository.save_fidelity_carrier(
            source_document_id,
            raw_bytes=parsed_document.raw_bytes,
            format_metadata=parsed_document.format_metadata,
        )

    def close(self) -> None:
        """Close the service and release resources."""
        self._segment_repository.close()

    def __enter__(self) -> "ImportService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
