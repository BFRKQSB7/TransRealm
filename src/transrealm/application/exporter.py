"""Fidelity export driven by translation revisions.

Exporters read a source document's persisted raw bytes and versioned format
metadata envelope, verify the carrier against the raw bytes (hash, encoding,
BOM, newline, and format-specific locator), then replace only the translated
target spans with revision text. A no-op export (``apply_revisions=False``)
reproduces the original bytes byte-for-byte. A missing or mismatched fidelity
carrier fails safely, and writes are atomic (a temp file in the target
directory renamed over the target), so a failure never leaves a partial file
or corrupts the existing target.

``FidelityExporter`` is the shared seam (DEC-P1-T01-FOUNDATION): carrier
loading, envelope verification, revision resolution and atomic writes are
common; each format subclass implements ``_build_replacement_plan`` with its
own locator semantics. TXT locates segments by byte span; JSON locates string
values by structural path plus the value token's byte span, verified by
re-parsing the raw bytes with the shared JSON tokenizer; SRT and VTT locate
each cue's text block by cue position, timing and byte span, verified by
re-parsing with the shared cue extractor for their format; ASS/SSA locate each
Dialogue event's Text field by event position, timing and byte span, verified
by re-parsing with the shared ASS/SSA event extractor.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.fidelity import (
    FidelityError,
    bom_length,
    detect_bom,
    detect_newline,
    load_envelope,
    resolve_encodings,
)
from transrealm.infrastructure.parsers.ass_ssa_parser import (
    AssSsaParseError,
)
from transrealm.infrastructure.parsers.ass_ssa_parser import (
    extract_events as extract_ass_ssa_events,
)
from transrealm.infrastructure.parsers.json_parser import (
    JSONParseError,
    extract_string_leaves,
)
from transrealm.infrastructure.parsers.srt_parser import (
    SRTParseError,
    extract_cues,
)
from transrealm.infrastructure.parsers.vtt_parser import (
    VTTParseError,
)
from transrealm.infrastructure.parsers.vtt_parser import (
    extract_cues as extract_vtt_cues,
)
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)


class ExportError(RuntimeError):
    """Fidelity export failed: missing carrier, invalid revision, or target."""


def _json_string(text: str) -> str:
    """Encode a translation as a JSON string literal (with its quotes)."""
    return json.dumps(text, ensure_ascii=False)


class FidelityExporter:
    """Shared fidelity export seam.

    Owns a read connection (running migrations on open, like the other
    application services) and validates every revision it uses: a revision must
    exist and belong to the segment it is used for. Output is written
    atomically, so a failed export never leaves a half file. Subclasses provide
    ``format`` and a format-specific ``_build_replacement_plan``.
    """

    format = ""
    parser_version = ""

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
        encoding: str | None = None,
        apply_revisions: bool = True,
    ) -> None:
        """Write the document's translated text to ``target_path``.

        Each segment contributes the text of its current revision, or of an
        explicitly supplied revision (``revision_overrides`` maps segment id
        to revision id). Overrides are validated: the revision must exist and
        belong to that segment, and override keys must reference segments in
        the document. A segment with no usable revision fails the export.

        With ``apply_revisions=False`` the original bytes are emitted verbatim
        (byte-identical no-op). ``encoding``, when given, must match the
        source document's content encoding; a differing override is refused so
        fidelity output is never silently rewritten in another encoding.

        Raises:
            ExportError: For a missing document, a missing or mismatched
                fidelity carrier, an invalid locator, a segment with no
                revision, an invalid or cross-segment revision, an encoding
                conflict, or an unwritable target.
        """
        overrides = revision_overrides or {}
        document = self._segment_repository.get_source_document_by_id(
            source_document_id,
        )
        if document is None:
            raise ExportError(
                f"SourceDocument with id {source_document_id} does not exist.",
            )
        raw_bytes, envelope = self._load_carrier(document)
        self._verify_envelope(document, raw_bytes, envelope)
        if encoding is not None:
            self._validate_encoding_override(encoding, envelope)
        segments = self._segment_repository.list_segments_by_document(
            source_document_id,
        )

        if not apply_revisions:
            output = raw_bytes
        else:
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
            plan = self._build_replacement_plan(envelope, raw_bytes, segments, overrides)
            output = self._apply_replacements(raw_bytes, plan)
        self._write_atomic(target_path, output)

    def _load_carrier(self, document: SourceDocument) -> tuple[bytes, dict[str, object]]:
        """Load the raw bytes and validated envelope, failing safely when missing."""
        if document.raw_bytes is None:
            raise ExportError(
                "This document has no preserved original bytes. Provide the "
                "original file to backfill fidelity data before exporting "
                "byte-identically.",
            )
        try:
            envelope = load_envelope(document.format_metadata, expected_format=self.format)
        except FidelityError as exc:
            raise ExportError(str(exc)) from exc
        return document.raw_bytes, envelope

    def _verify_envelope(
        self,
        document: SourceDocument,
        raw_bytes: bytes,
        envelope: dict[str, object],
    ) -> None:
        """Verify hash, encoding, BOM, and newline consistency of the carrier."""
        if envelope.get("source_hash") != document.source_hash:
            raise ExportError(
                "Fidelity metadata source hash does not match the document.",
            )
        if hashlib.sha256(raw_bytes).hexdigest() != document.source_hash:
            raise ExportError(
                "Stored raw bytes hash does not match the source document hash.",
            )
        content_encoding = str(envelope.get("encoding"))
        bom_value = envelope.get("bom")
        bom = bom_value if isinstance(bom_value, str) else None
        detected_bom = detect_bom(raw_bytes)
        if detected_bom != bom:
            raise ExportError(
                f"Fidelity metadata declares BOM {bom!r} but the raw bytes "
                f"start with {detected_bom!r}.",
            )
        try:
            text = raw_bytes.decode(self._decode_codec(envelope))
        except (UnicodeDecodeError, LookupError) as exc:
            raise ExportError(
                f"Raw bytes do not decode with the declared encoding: {exc}",
            ) from exc
        if detect_newline(text) != envelope.get("newline"):
            raise ExportError(
                "Fidelity metadata newline style does not match the raw bytes.",
            )
        # Sanity-check the content encoding name is usable.
        try:
            "".encode(content_encoding)
        except LookupError as exc:
            raise ExportError(
                f"Fidelity metadata declares unknown encoding {content_encoding!r}.",
            ) from exc

    @staticmethod
    def _decode_codec(envelope: dict[str, object]) -> str:
        content = str(envelope.get("encoding"))
        bom_value = envelope.get("bom")
        bom = bom_value if isinstance(bom_value, str) else None
        return resolve_encodings(content, bom)[1]

    def _validate_encoding_override(self, encoding: str, envelope: dict[str, object]) -> None:
        declared = encoding.strip().lower().replace("_", "-")
        if declared in {"utf8", "utf-8-sig"}:
            declared = "utf-8"
        source_encoding = str(envelope.get("encoding"))
        if declared != source_encoding:
            raise ExportError(
                f"Export encoding '{encoding}' cannot encode fidelity output in "
                f"the source encoding '{source_encoding}'.",
            )

    def _build_replacement_plan(
        self,
        envelope: dict[str, object],
        raw_bytes: bytes,
        segments: list[Segment],
        overrides: dict[int, int],
    ) -> list[tuple[int, int, bytes]]:
        raise NotImplementedError

    @staticmethod
    def _apply_replacements(
        raw_bytes: bytes,
        plan: list[tuple[int, int, bytes]],
    ) -> bytes:
        output = raw_bytes
        for start, end, new_bytes in sorted(plan, key=lambda item: item[0], reverse=True):
            output = output[:start] + new_bytes + output[end:]
        return output

    def _write_atomic(self, target_path: Path, data: bytes) -> None:
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

    def __enter__(self) -> FidelityExporter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class TxtExporter(FidelityExporter):
    """Export one source document's translated text as fidelity TXT."""

    format = "txt"

    def _build_replacement_plan(
        self,
        envelope: dict[str, object],
        raw_bytes: bytes,
        segments: list[Segment],
        overrides: dict[int, int],
    ) -> list[tuple[int, int, bytes]]:
        locator = envelope.get("locator")
        spans = locator.get("segments") if isinstance(locator, dict) else None
        if not isinstance(spans, list):
            raise ExportError("Fidelity metadata has no segment locator.")
        if len(spans) != len(segments):
            raise ExportError(
                f"Fidelity metadata has {len(spans)} spans but the document has "
                f"{len(segments)} segments.",
            )
        content_encoding = str(envelope.get("encoding"))
        plan: list[tuple[int, int, bytes]] = []
        previous_end = 0
        for segment, span in zip(segments, spans):
            if not isinstance(span, dict):
                raise ExportError("Fidelity metadata contains a malformed span.")
            if span.get("sequence") != segment.sequence:
                raise ExportError(
                    f"Fidelity span sequence {span.get('sequence')} does not match "
                    f"segment sequence {segment.sequence}.",
                )
            start = span.get("byte_start")
            end = span.get("byte_end")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end < start
                or end > len(raw_bytes)
            ):
                raise ExportError(
                    f"Segment {segment.sequence} span is out of bounds.",
                )
            if start < previous_end:
                raise ExportError(
                    f"Segment {segment.sequence} span overlaps the previous span.",
                )
            previous_end = end
            try:
                decoded = raw_bytes[start:end].decode(content_encoding)
            except (UnicodeDecodeError, LookupError) as exc:
                raise ExportError(
                    f"Segment {segment.sequence} span does not decode: {exc}",
                ) from exc
            if decoded != segment.source_text:
                raise ExportError(
                    f"Segment {segment.sequence} span decodes to a different "
                    "source text.",
                )

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
            try:
                new_bytes = revision.text.encode(content_encoding)
            except (UnicodeEncodeError, LookupError) as exc:
                raise ExportError(
                    f"Failed to encode translation '{revision.text}' in "
                    f"{content_encoding}: {exc}",
                ) from exc
            plan.append((start, end, new_bytes))
        return plan


class JsonExporter(FidelityExporter):
    """Export one source document's translated string values as fidelity JSON.

    Only string values in value position are ever replaced; keys, numbers,
    booleans, nulls, containers, whitespace, escaping and ordering are
    preserved byte-for-byte outside the replaced tokens. The locator is
    JSON-specific: each segment stores a structural path and the byte span of
    its string value token. Before replacing, the raw bytes are re-parsed with
    the shared JSON tokenizer and every stored path/span/value is verified
    against the re-derived leaves, so a tampered or misaligned envelope is
    refused.
    """

    format = "json"
    parser_version = "1.0.0"

    def _build_replacement_plan(
        self,
        envelope: dict[str, object],
        raw_bytes: bytes,
        segments: list[Segment],
        overrides: dict[int, int],
    ) -> list[tuple[int, int, bytes]]:
        if envelope.get("parser_version") != self.parser_version:
            raise ExportError(
                f"Fidelity metadata parser version {envelope.get('parser_version')!r} "
                f"does not match {self.parser_version!r}.",
            )
        content_encoding = str(envelope.get("encoding"))
        bom_value = envelope.get("bom")
        bom = bom_value if isinstance(bom_value, str) else None
        try:
            text = raw_bytes.decode(self._decode_codec(envelope))
        except (UnicodeDecodeError, LookupError) as exc:
            raise ExportError(
                f"Raw bytes do not decode with the declared encoding: {exc}",
            ) from exc
        try:
            leaves = extract_string_leaves(
                text,
                content_encoding=content_encoding,
                bom_len=bom_length(bom),
            )
        except JSONParseError as exc:
            raise ExportError(f"Stored raw bytes are not valid JSON: {exc}") from exc

        locator = envelope.get("locator")
        entries = locator.get("segments") if isinstance(locator, dict) else None
        if not isinstance(entries, list):
            raise ExportError("Fidelity metadata has no JSON segment locator.")
        if len(entries) != len(segments) or len(leaves) != len(segments):
            raise ExportError(
                "Fidelity metadata segment count does not match the document.",
            )

        plan: list[tuple[int, int, bytes]] = []
        for segment, entry, leaf in zip(segments, entries, leaves):
            if not isinstance(entry, dict):
                raise ExportError(
                    "Fidelity metadata contains a malformed JSON locator entry.",
                )
            if entry.get("sequence") != segment.sequence or leaf.sequence != segment.sequence:
                raise ExportError(
                    f"Fidelity locator sequence does not match segment "
                    f"{segment.sequence}.",
                )
            if entry.get("path") != leaf.path:
                raise ExportError(
                    f"Segment {segment.sequence} structural path "
                    f"{entry.get('path')!r} does not match the raw bytes "
                    f"({leaf.path!r}).",
                )
            if entry.get("byte_start") != leaf.byte_start or entry.get("byte_end") != leaf.byte_end:
                raise ExportError(
                    f"Segment {segment.sequence} byte span does not match the "
                    "raw bytes.",
                )
            if leaf.value != segment.source_text:
                raise ExportError(
                    f"Segment {segment.sequence} value does not match its "
                    "source text.",
                )

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
            try:
                new_bytes = _json_string(revision.text).encode(content_encoding)
            except (UnicodeEncodeError, LookupError) as exc:
                raise ExportError(
                    f"Failed to encode translation '{revision.text}' in "
                    f"{content_encoding}: {exc}",
                ) from exc
            plan.append((leaf.byte_start, leaf.byte_end, new_bytes))
        return plan


class SrtExporter(FidelityExporter):
    """Export one source document's translated cue text as fidelity SRT.

    Each cue's text block is the only replaced span; the cue index, timing
    line, optional settings, blank separators and line endings are preserved
    byte-for-byte outside the replaced block. The locator is SRT-specific:
    each segment stores its cue position, index, timing strings, settings, and
    the text block's byte span. Before replacing, the raw bytes are re-parsed
    with the shared ``extract_cues`` and every stored cue is verified against
    the re-derived cues, so a tampered or misaligned envelope is refused.
    """

    format = "srt"
    parser_version = "1.0.0"

    def _build_replacement_plan(
        self,
        envelope: dict[str, object],
        raw_bytes: bytes,
        segments: list[Segment],
        overrides: dict[int, int],
    ) -> list[tuple[int, int, bytes]]:
        if envelope.get("parser_version") != self.parser_version:
            raise ExportError(
                f"Fidelity metadata parser version {envelope.get('parser_version')!r} "
                f"does not match {self.parser_version!r}.",
            )
        content_encoding = str(envelope.get("encoding"))
        bom_value = envelope.get("bom")
        bom = bom_value if isinstance(bom_value, str) else None
        try:
            text = raw_bytes.decode(self._decode_codec(envelope))
        except (UnicodeDecodeError, LookupError) as exc:
            raise ExportError(
                f"Raw bytes do not decode with the declared encoding: {exc}",
            ) from exc
        try:
            cues = extract_cues(
                text,
                content_encoding=content_encoding,
                bom_len=bom_length(bom),
            )
        except SRTParseError as exc:
            raise ExportError(f"Stored raw bytes are not valid SRT: {exc}") from exc

        locator = envelope.get("locator")
        entries = locator.get("segments") if isinstance(locator, dict) else None
        if not isinstance(entries, list):
            raise ExportError("Fidelity metadata has no SRT segment locator.")
        if len(entries) != len(segments) or len(cues) != len(segments):
            raise ExportError(
                "Fidelity metadata segment count does not match the document.",
            )

        plan: list[tuple[int, int, bytes]] = []
        for segment, entry, cue in zip(segments, entries, cues):
            if not isinstance(entry, dict):
                raise ExportError(
                    "Fidelity metadata contains a malformed SRT locator entry.",
                )
            if entry.get("sequence") != segment.sequence or cue.sequence != segment.sequence:
                raise ExportError(
                    f"Fidelity locator sequence does not match segment "
                    f"{segment.sequence}.",
                )
            if entry.get("index") != cue.index:
                raise ExportError(
                    f"Segment {segment.sequence} cue index does not match the "
                    "raw bytes.",
                )
            if entry.get("start") != cue.start or entry.get("end") != cue.end:
                raise ExportError(
                    f"Segment {segment.sequence} timing does not match the "
                    "raw bytes.",
                )
            if entry.get("settings") != cue.settings:
                raise ExportError(
                    f"Segment {segment.sequence} timing settings do not match "
                    "the raw bytes.",
                )
            if entry.get("byte_start") != cue.byte_start or entry.get("byte_end") != cue.byte_end:
                raise ExportError(
                    f"Segment {segment.sequence} text block span does not match "
                    "the raw bytes.",
                )
            if cue.text != segment.source_text:
                raise ExportError(
                    f"Segment {segment.sequence} text does not match its "
                    "source text.",
                )

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
            try:
                new_bytes = revision.text.encode(content_encoding)
            except (UnicodeEncodeError, LookupError) as exc:
                raise ExportError(
                    f"Failed to encode translation '{revision.text}' in "
                    f"{content_encoding}: {exc}",
                ) from exc
            plan.append((cue.byte_start, cue.byte_end, new_bytes))
        return plan


class VttExporter(FidelityExporter):
    """Export one source document's translated cue text as fidelity VTT.

    Each cue's text block is the only replaced span; the WEBVTT signature,
    NOTE/STYLE/REGION blocks, cue identifier, timing line, optional settings,
    blank separators and line endings are preserved byte-for-byte outside the
    replaced block. The locator is VTT-specific: each segment stores its cue
    position, identifier, timing strings, settings, and the text block's byte
    span. Before replacing, the raw bytes are re-parsed with the shared
    ``extract_cues`` (the VTT one) and every stored cue is verified against the
    re-derived cues, so a tampered or misaligned envelope is refused.
    """

    format = "vtt"
    parser_version = "1.0.0"

    def _build_replacement_plan(
        self,
        envelope: dict[str, object],
        raw_bytes: bytes,
        segments: list[Segment],
        overrides: dict[int, int],
    ) -> list[tuple[int, int, bytes]]:
        if envelope.get("parser_version") != self.parser_version:
            raise ExportError(
                f"Fidelity metadata parser version {envelope.get('parser_version')!r} "
                f"does not match {self.parser_version!r}.",
            )
        content_encoding = str(envelope.get("encoding"))
        bom_value = envelope.get("bom")
        bom = bom_value if isinstance(bom_value, str) else None
        try:
            text = raw_bytes.decode(self._decode_codec(envelope))
        except (UnicodeDecodeError, LookupError) as exc:
            raise ExportError(
                f"Raw bytes do not decode with the declared encoding: {exc}",
            ) from exc
        try:
            cues = extract_vtt_cues(
                text,
                content_encoding=content_encoding,
                bom_len=bom_length(bom),
            )
        except VTTParseError as exc:
            raise ExportError(f"Stored raw bytes are not valid WebVTT: {exc}") from exc

        locator = envelope.get("locator")
        entries = locator.get("segments") if isinstance(locator, dict) else None
        if not isinstance(entries, list):
            raise ExportError("Fidelity metadata has no VTT segment locator.")
        if len(entries) != len(segments) or len(cues) != len(segments):
            raise ExportError(
                "Fidelity metadata segment count does not match the document.",
            )

        plan: list[tuple[int, int, bytes]] = []
        for segment, entry, cue in zip(segments, entries, cues):
            if not isinstance(entry, dict):
                raise ExportError(
                    "Fidelity metadata contains a malformed VTT locator entry.",
                )
            if entry.get("sequence") != segment.sequence or cue.sequence != segment.sequence:
                raise ExportError(
                    f"Fidelity locator sequence does not match segment "
                    f"{segment.sequence}.",
                )
            if entry.get("id") != cue.id:
                raise ExportError(
                    f"Segment {segment.sequence} cue identifier does not match "
                    "the raw bytes.",
                )
            if entry.get("start") != cue.start or entry.get("end") != cue.end:
                raise ExportError(
                    f"Segment {segment.sequence} timing does not match the "
                    "raw bytes.",
                )
            if entry.get("settings") != cue.settings:
                raise ExportError(
                    f"Segment {segment.sequence} timing settings do not match "
                    "the raw bytes.",
                )
            if entry.get("byte_start") != cue.byte_start or entry.get("byte_end") != cue.byte_end:
                raise ExportError(
                    f"Segment {segment.sequence} text block span does not match "
                    "the raw bytes.",
                )
            if cue.text != segment.source_text:
                raise ExportError(
                    f"Segment {segment.sequence} text does not match its "
                    "source text.",
                )

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
            try:
                new_bytes = revision.text.encode(content_encoding)
            except (UnicodeEncodeError, LookupError) as exc:
                raise ExportError(
                    f"Failed to encode translation '{revision.text}' in "
                    f"{content_encoding}: {exc}",
                ) from exc
            plan.append((cue.byte_start, cue.byte_end, new_bytes))
        return plan


class _AssSsaExporter(FidelityExporter):
    """Shared fidelity export for ASS/SSA Dialogue Text.

    Only the Text field of each Dialogue event is ever replaced; every section,
    the ``[Events] Format:`` line, ``Comment:`` events, all non-Text fields,
    inline override tags, escapes and line endings are preserved byte-for-byte
    outside the replaced Text span. The locator is event-based: each segment
    stores its event position, timing strings, and the Text field's byte span.
    Before replacing, the raw bytes are re-parsed with the shared
    ``extract_events`` and every stored event is verified against the
    re-derived events, so a tampered or misaligned envelope is refused.
    """

    parser_version = "1.0.0"

    def _build_replacement_plan(
        self,
        envelope: dict[str, object],
        raw_bytes: bytes,
        segments: list[Segment],
        overrides: dict[int, int],
    ) -> list[tuple[int, int, bytes]]:
        if envelope.get("parser_version") != self.parser_version:
            raise ExportError(
                f"Fidelity metadata parser version {envelope.get('parser_version')!r} "
                f"does not match {self.parser_version!r}.",
            )
        content_encoding = str(envelope.get("encoding"))
        bom_value = envelope.get("bom")
        bom = bom_value if isinstance(bom_value, str) else None
        try:
            text = raw_bytes.decode(self._decode_codec(envelope))
        except (UnicodeDecodeError, LookupError) as exc:
            raise ExportError(
                f"Raw bytes do not decode with the declared encoding: {exc}",
            ) from exc
        try:
            events = extract_ass_ssa_events(
                text,
                format=self.format,
                content_encoding=content_encoding,
                bom_len=bom_length(bom),
            )
        except AssSsaParseError as exc:
            raise ExportError(
                f"Stored raw bytes are not valid {self.format.upper()}: {exc}",
            ) from exc

        locator = envelope.get("locator")
        entries = locator.get("segments") if isinstance(locator, dict) else None
        if not isinstance(entries, list):
            raise ExportError("Fidelity metadata has no ASS/SSA segment locator.")
        if len(entries) != len(segments) or len(events) != len(segments):
            raise ExportError(
                "Fidelity metadata segment count does not match the document.",
            )

        plan: list[tuple[int, int, bytes]] = []
        for segment, entry, event in zip(segments, entries, events):
            if not isinstance(entry, dict):
                raise ExportError(
                    "Fidelity metadata contains a malformed ASS/SSA locator entry.",
                )
            if entry.get("sequence") != segment.sequence or event.sequence != segment.sequence:
                raise ExportError(
                    f"Fidelity locator sequence does not match segment "
                    f"{segment.sequence}.",
                )
            if entry.get("start") != event.start or entry.get("end") != event.end:
                raise ExportError(
                    f"Segment {segment.sequence} timing does not match the "
                    "raw bytes.",
                )
            if (
                entry.get("byte_start") != event.byte_start
                or entry.get("byte_end") != event.byte_end
            ):
                raise ExportError(
                    f"Segment {segment.sequence} Text span does not match the "
                    "raw bytes.",
                )
            if event.text != segment.source_text:
                raise ExportError(
                    f"Segment {segment.sequence} text does not match its "
                    "source text.",
                )

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
            try:
                new_bytes = revision.text.encode(content_encoding)
            except (UnicodeEncodeError, LookupError) as exc:
                raise ExportError(
                    f"Failed to encode translation '{revision.text}' in "
                    f"{content_encoding}: {exc}",
                ) from exc
            plan.append((event.byte_start, event.byte_end, new_bytes))
        return plan


class AssExporter(_AssSsaExporter):
    """Export one source document's translated Dialogue Text as fidelity ASS."""

    format = "ass"


class SsaExporter(_AssSsaExporter):
    """Export one source document's translated Dialogue Text as fidelity SSA."""

    format = "ssa"


__all__ = [
    "ExportError",
    "FidelityExporter",
    "AssExporter",
    "JsonExporter",
    "SrtExporter",
    "SsaExporter",
    "TxtExporter",
    "VttExporter",
]
