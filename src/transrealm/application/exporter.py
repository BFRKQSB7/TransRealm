"""TXT export driven by translation revisions.

The exporter reads a source document's segments in original sequence order and
writes each segment's translation from its current revision, or from an
explicitly validated revision override. A missing or mis-owning revision never
falls back to the source text. Writes are atomic (a temp file in the target
directory renamed over the target), so an encoding failure or unwritable
target leaves the target untouched and never a partial file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from transrealm.domain.segment import Segment
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)


class ExportError(RuntimeError):
    """TXT export failed: missing/invalid revision, encoding, or target."""


class TxtExporter:
    """Export one source document's translated text as TXT.

    The exporter owns a read connection (running migrations on open, like the
    other application services) and validates every revision it uses: a
    revision must exist and belong to the segment it is used for. Output is
    written atomically, so a failed export never leaves a half file.
    """

    MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._app_version = app_version
        self._db = create_database(db_path)
        self._segment_repository = SegmentRepository(self._db)
        self._revision_repository = TranslationRevisionRepository(self._db)
        self._run_migrations()

    def _run_migrations(self) -> None:
        from transrealm.infrastructure.migrations.discovery import discover_migrations
        from transrealm.infrastructure.migrations.runner import MigrationRunner

        migrations = discover_migrations(self.MIGRATIONS_DIR)
        runner = MigrationRunner(self._db)
        runner.apply(migrations, app_version=self._app_version)

    def export_document(
        self,
        *,
        source_document_id: int,
        target_path: Path,
        revision_overrides: dict[int, int] | None = None,
        encoding: str = "utf-8",
    ) -> None:
        """Write the document's translated text to ``target_path``.

        Each segment contributes the text of its current revision, or of an
        explicitly supplied revision (``revision_overrides`` maps segment id
        to revision id). Overrides are validated: the revision must exist and
        belong to that segment, and override keys must reference segments in
        the document. A segment with no usable revision fails the export.

        Raises:
            ExportError: For a missing document, a segment with no revision,
                an invalid or cross-segment revision, an encoding failure, or
                an unwritable target.
        """
        overrides = revision_overrides or {}
        document = self._segment_repository.get_source_document_by_id(
            source_document_id,
        )
        if document is None:
            raise ExportError(
                f"SourceDocument with id {source_document_id} does not exist.",
            )
        segments = self._segment_repository.list_segments_by_document(
            source_document_id,
        )
        segment_ids = {
            segment_id
            for segment_id in (segment.id for segment in segments)
            if segment_id is not None
        }
        unknown = set(overrides) - segment_ids
        if unknown:
            raise ExportError(
                "Revision overrides reference segments not in this document: "
                f"{sorted(unknown)}.",
            )

        lines = self._resolve_lines(segments, overrides)
        content = "\n".join(lines)
        if lines:
            content += "\n"
        self._write_atomic(target_path, content, encoding)

    def _resolve_lines(
        self,
        segments: list[Segment],
        overrides: dict[int, int],
    ) -> list[str]:
        lines: list[str] = []
        for segment in segments:
            assert segment.id is not None
            revision_id = overrides.get(segment.id, segment.current_revision_id)
            if revision_id is None:
                raise ExportError(
                    f"Segment {segment.id} has no current revision; nothing to export.",
                )
            revision = self._revision_repository.get_by_id(revision_id)
            if revision is None:
                raise ExportError(
                    f"Revision {revision_id} referenced by segment "
                    f"{segment.id} does not exist.",
                )
            if revision.segment_id != segment.id:
                raise ExportError(
                    f"Revision {revision_id} belongs to segment "
                    f"{revision.segment_id}, not {segment.id}.",
                )
            lines.append(revision.text)
        return lines

    def _write_atomic(self, target_path: Path, content: str, encoding: str) -> None:
        target_path = Path(target_path)
        parent = target_path.parent
        if not parent.exists():
            raise ExportError(f"Target directory does not exist: {parent}.")
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{target_path.name}.",
                suffix=".tmp",
                dir=parent,
            )
        except OSError as exc:
            raise ExportError(f"Cannot create temp file in {parent}: {exc}") from exc
        temp_path = Path(temp_name)
        try:
            data = content.encode(encoding)
        except (UnicodeEncodeError, LookupError) as exc:
            os.close(fd)
            temp_path.unlink(missing_ok=True)
            raise ExportError(f"Failed to encode export content: {exc}") from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temp_path, target_path)
        except OSError as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ExportError(f"Failed to write export file: {exc}") from exc

    def close(self) -> None:
        """Close the read connection."""
        self._db.close()

    def __enter__(self) -> TxtExporter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
