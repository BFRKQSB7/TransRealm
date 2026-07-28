"""Segment and source document domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SourceDocument:
    """A source file imported into a Project."""

    id: int | None
    project_id: int
    name: str
    format: str
    encoding: str
    source_hash: str
    parser_version: str
    created_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        project_id: int,
        name: str,
        format: str,
        encoding: str,
        source_hash: str,
        parser_version: str,
    ) -> "SourceDocument":
        """Create a new, unsaved SourceDocument instance."""
        return cls(
            id=None,
            project_id=project_id,
            name=name,
            format=format,
            encoding=encoding,
            source_hash=source_hash,
            parser_version=parser_version,
            created_at=None,
        )


@dataclass
class Segment:
    """A single translatable unit."""

    id: int | None
    source_document_id: int
    stable_key: str
    source_text: str
    sequence: int
    status: str
    current_revision_id: int | None
    version: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        source_document_id: int,
        stable_key: str,
        source_text: str,
        sequence: int,
        status: str = "pending",
    ) -> "Segment":
        """Create a new, unsaved Segment instance."""
        return cls(
            id=None,
            source_document_id=source_document_id,
            stable_key=stable_key,
            source_text=source_text,
            sequence=sequence,
            status=status,
            current_revision_id=None,
            version=1,
            lease_owner=None,
            lease_expires_at=None,
            created_at=None,
            updated_at=None,
        )
