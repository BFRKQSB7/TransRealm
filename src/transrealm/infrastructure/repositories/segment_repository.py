"""Segment repository implementation."""

from datetime import datetime
from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction


class SegmentRepository:
    """SQLite-backed repository for SourceDocument and Segment entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> "SegmentRepository":
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def import_document(
        self,
        document: SourceDocument,
        segments: list[Segment],
    ) -> tuple[SourceDocument, list[Segment]]:
        """Persist one immutable source version and its segments atomically."""
        now = datetime.now().isoformat()
        with transaction(self._db):
            cursor = self._db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, source_hash) DO NOTHING",
                (
                    document.project_id,
                    document.name,
                    document.format,
                    document.encoding,
                    document.source_hash,
                    document.parser_version,
                    now,
                ),
            )
            new_id = cursor.lastrowid if cursor.rowcount == 1 else None
            if new_id is None:
                existing = self.find_source_document_by_hash(
                    document.project_id,
                    document.source_hash,
                )
                if existing is None or existing.id is None:
                    raise RuntimeError("Conflicting source document could not be loaded")
                return existing, self.list_segments_by_document(existing.id)

            saved_document = SourceDocument(
                id=new_id,
                project_id=document.project_id,
                name=document.name,
                format=document.format,
                encoding=document.encoding,
                source_hash=document.source_hash,
                parser_version=document.parser_version,
                created_at=datetime.fromisoformat(now),
            )
            saved_segments = self._insert_segments(new_id, segments, now)
        return saved_document, saved_segments

    def save_source_document(self, document: SourceDocument) -> SourceDocument:
        """Insert a source document and return the persisted entity."""
        now = datetime.now().isoformat()
        with transaction(self._db):
            cursor = self._db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    document.project_id,
                    document.name,
                    document.format,
                    document.encoding,
                    document.source_hash,
                    document.parser_version,
                    now,
                ),
            )
            new_id = cursor.lastrowid
        return SourceDocument(
            id=new_id,
            project_id=document.project_id,
            name=document.name,
            format=document.format,
            encoding=document.encoding,
            source_hash=document.source_hash,
            parser_version=document.parser_version,
            created_at=datetime.fromisoformat(now),
        )

    def find_source_document_by_hash(
        self,
        project_id: int,
        source_hash: str,
    ) -> SourceDocument | None:
        """Find a source document by project and content hash."""
        cursor = self._db.execute(
            "SELECT id, project_id, name, format, encoding, source_hash, "
            "parser_version, created_at "
            "FROM source_documents WHERE project_id = ? AND source_hash = ?",
            (project_id, source_hash),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_source_document(row)

    def get_source_document_by_id(self, source_document_id: int) -> SourceDocument | None:
        """Fetch a source document by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, project_id, name, format, encoding, source_hash, "
            "parser_version, created_at "
            "FROM source_documents WHERE id = ?",
            (source_document_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_source_document(row)

    def list_source_documents_by_project(self, project_id: int) -> list[SourceDocument]:
        """Return all source documents for a project ordered by id."""
        cursor = self._db.execute(
            "SELECT id, project_id, name, format, encoding, source_hash, "
            "parser_version, created_at "
            "FROM source_documents WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
        return [self._row_to_source_document(row) for row in cursor.fetchall()]

    def save_segments(self, segments: list[Segment]) -> list[Segment]:
        """Insert segments and return them with ids assigned."""
        now = datetime.now().isoformat()
        with transaction(self._db):
            return self._insert_segments(None, segments, now)

    def _insert_segments(
        self,
        source_document_id: int | None,
        segments: list[Segment],
        now: str,
    ) -> list[Segment]:
        saved: list[Segment] = []
        for segment in segments:
            document_id = (
                source_document_id
                if source_document_id is not None
                else segment.source_document_id
            )
            cursor = self._db.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence, status, "
                "current_revision_id, version, lease_owner, lease_expires_at, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    segment.stable_key,
                    segment.source_text,
                    segment.sequence,
                    segment.status,
                    segment.current_revision_id,
                    segment.version,
                    segment.lease_owner,
                    segment.lease_expires_at.isoformat() if segment.lease_expires_at else None,
                    now,
                    now,
                ),
            )
            saved.append(
                Segment(
                    id=cursor.lastrowid,
                    source_document_id=document_id,
                    stable_key=segment.stable_key,
                    source_text=segment.source_text,
                    sequence=segment.sequence,
                    status=segment.status,
                    current_revision_id=segment.current_revision_id,
                    version=segment.version,
                    lease_owner=segment.lease_owner,
                    lease_expires_at=segment.lease_expires_at,
                    created_at=datetime.fromisoformat(now),
                    updated_at=datetime.fromisoformat(now),
                ),
            )
        return saved

    def list_segments_by_document(self, source_document_id: int) -> list[Segment]:
        """Return all segments for a source document ordered by sequence."""
        cursor = self._db.execute(
            "SELECT id, source_document_id, stable_key, source_text, sequence, status, "
            "current_revision_id, version, lease_owner, lease_expires_at, created_at, updated_at "
            "FROM segments WHERE source_document_id = ? ORDER BY sequence",
            (source_document_id,),
        )
        return [self._row_to_segment(row) for row in cursor.fetchall()]

    def get_by_id(self, segment_id: int) -> Segment | None:
        """Fetch a segment by id, or None if not found."""
        cursor = self._db.execute(
            "SELECT id, source_document_id, stable_key, source_text, sequence, status, "
            "current_revision_id, version, lease_owner, lease_expires_at, created_at, updated_at "
            "FROM segments WHERE id = ?",
            (segment_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_segment(row)

    def find_segment_by_stable_key(
        self,
        source_document_id: int,
        stable_key: str,
    ) -> Segment | None:
        """Find a segment by its source document and stable key."""
        cursor = self._db.execute(
            "SELECT id, source_document_id, stable_key, source_text, sequence, status, "
            "current_revision_id, version, lease_owner, lease_expires_at, created_at, updated_at "
            "FROM segments WHERE source_document_id = ? AND stable_key = ?",
            (source_document_id, stable_key),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_segment(row)

    @staticmethod
    def _row_to_source_document(row: tuple[object, ...]) -> SourceDocument:
        return SourceDocument(
            id=int(str(row[0])),
            project_id=int(str(row[1])),
            name=str(row[2]),
            format=str(row[3]),
            encoding=str(row[4]),
            source_hash=str(row[5]),
            parser_version=str(row[6]),
            created_at=datetime.fromisoformat(str(row[7])),
        )

    @staticmethod
    def _row_to_segment(row: tuple[object, ...]) -> Segment:
        return Segment(
            id=int(str(row[0])),
            source_document_id=int(str(row[1])),
            stable_key=str(row[2]),
            source_text=str(row[3]),
            sequence=int(str(row[4])),
            status=str(row[5]),
            current_revision_id=int(str(row[6])) if row[6] is not None else None,
            version=int(str(row[7])),
            lease_owner=str(row[8]) if row[8] is not None else None,
            lease_expires_at=datetime.fromisoformat(str(row[9])) if row[9] is not None else None,
            created_at=datetime.fromisoformat(str(row[10])),
            updated_at=datetime.fromisoformat(str(row[11])),
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
