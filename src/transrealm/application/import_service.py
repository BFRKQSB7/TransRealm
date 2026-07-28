"""Import application service."""

from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.parsers.txt_parser import parse_txt
from transrealm.infrastructure.repositories.project_repository import ProjectRepository
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository


class ImportService:
    """Application service for importing source documents into a Project."""

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._db = create_database(db_path)
        self._project_repository = ProjectRepository(self._db)
        self._segment_repository = SegmentRepository(self._db)
        self._run_migrations()

    def _run_migrations(self) -> None:
        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

    def import_txt(
        self,
        project_id: int,
        file_path: Path,
        *,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Import a TXT file into a Project.

        If a source document with the same hash already exists for the project,
        the existing document is returned and no new segments are created.
        """
        document, segments = parse_txt(
            file_path,
            project_id=project_id,
            name=name,
            encoding=encoding,
        )

        existing = self._segment_repository.find_source_document_by_hash(
            project_id,
            document.source_hash,
        )
        if existing is not None:
            assert existing.id is not None
            existing_segments = self._segment_repository.list_segments_by_document(existing.id)
            return existing, existing_segments

        saved_document = self._segment_repository.save_source_document(document)
        assert saved_document.id is not None
        segments_with_id = [
            Segment(
                id=segment.id,
                source_document_id=saved_document.id,
                stable_key=segment.stable_key,
                source_text=segment.source_text,
                sequence=segment.sequence,
                status=segment.status,
                current_revision_id=segment.current_revision_id,
                version=segment.version,
                lease_owner=segment.lease_owner,
                lease_expires_at=segment.lease_expires_at,
                created_at=segment.created_at,
                updated_at=segment.updated_at,
            )
            for segment in segments
        ]
        saved_segments = self._segment_repository.save_segments(segments_with_id)
        return saved_document, saved_segments

    def close(self) -> None:
        """Close the service and release resources."""
        self._segment_repository.close()

    def __enter__(self) -> "ImportService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
