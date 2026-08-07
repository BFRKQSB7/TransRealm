"""TXT parser producing stable Segments with byte-accurate fidelity spans."""

import hashlib
import json
from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument
from transrealm.infrastructure.fidelity import (
    bom_length,
    build_txt_envelope,
    detect_bom,
    detect_newline,
    resolve_encodings,
)

# str.splitlines() line boundaries beyond CR/LF; the legacy parser split on all
# of these, so the fidelity parser must too or re-import/backfill would change
# the segment mapping for such files.
_LINE_BREAK_CHARS = frozenset(
    [chr(cp) for cp in (0x0A, 0x0D, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029)]
)


class TxtParser:
    """Line-based TXT parser.

    Segments are one per non-empty line; ``source_text`` and ``stable_key`` are
    the stripped line text and a sequence-based hash, unchanged from earlier
    versions. Line boundaries match ``str.splitlines()`` so the segment mapping
    stays identical across the fidelity rework. In addition the parser computes
    the byte span of each segment's target text inside the original raw bytes
    and persists them in a versioned format metadata envelope (the fidelity
    carrier), so an exporter can replace only the translated spans without
    touching whitespace, empty lines, line endings, BOM, or the original
    encoding.
    """

    format = "txt"
    version = "1.0.0"

    def parse(
        self,
        file_path: Path,
        *,
        project_id: int,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Parse a TXT file into a SourceDocument and Segments.

        Args:
            file_path: Path to the TXT file.
            project_id: Project that owns the source document.
            name: Optional display name for the source document. Defaults to the
                file name.
            encoding: Text encoding to use when reading the file. A BOM-capable
                codec (``utf-8``/``utf-8-sig`` for a UTF-8 BOM, ``utf-16`` for a
                UTF-16 BOM) strips the BOM and records it in the envelope.

        Returns:
            A tuple of (SourceDocument, list of Segments).

        Raises:
            FileNotFoundError: If the file does not exist.
            UnicodeDecodeError: If the file cannot be decoded with the given encoding.
        """
        raw_bytes = file_path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()

        bom = detect_bom(raw_bytes)
        content_encoding, decode_encoding = resolve_encodings(encoding, bom)
        text = raw_bytes.decode(decode_encoding)
        newline = detect_newline(text)

        segments, spans = _extract_segments(text, content_encoding, bom_length(bom))

        envelope = build_txt_envelope(
            encoding=content_encoding,
            bom=bom,
            newline=newline,
            parser_version=self.version,
            source_hash=source_hash,
            spans=spans,
        )

        document = SourceDocument.create(
            project_id=project_id,
            name=name or file_path.name,
            format=self.format,
            encoding=encoding,
            source_hash=source_hash,
            parser_version=self.version,
            raw_bytes=raw_bytes,
            format_metadata=json.dumps(envelope, ensure_ascii=False),
        )
        return document, segments


def _extract_segments(
    text: str,
    content_encoding: str,
    bom_len: int,
) -> tuple[list[Segment], list[dict[str, int]]]:
    """Build segments and their byte spans in a single pass.

    ``byte_cursor`` tracks the byte offset of the current line start inside the
    raw file (the decoded, BOM-stripped text plus the BOM length), so target
    spans are computed without materializing a per-character offset list.
    """
    segments: list[Segment] = []
    spans: list[dict[str, int]] = []
    sequence = 0
    length = len(text)
    line_start = 0
    byte_cursor = bom_len
    index = 0
    while index < length:
        char = text[index]
        if char not in _LINE_BREAK_CHARS:
            index += 1
            continue
        line_end = index
        if char == "\r" and index + 1 < length and text[index + 1] == "\n":
            terminator = 2
        else:
            terminator = 1
        line_bytes = _byte_length(text[line_start:line_end], content_encoding)
        terminator_bytes = _byte_length(text[index : index + terminator], content_encoding)
        source_text, target_start, target_end = _stripped(text, line_start, line_end)
        if target_start < target_end:
            sequence += 1
            byte_start = byte_cursor + _byte_length(
                text[line_start:target_start],
                content_encoding,
            )
            byte_end = byte_cursor + _byte_length(
                text[line_start:target_end],
                content_encoding,
            )
            segments.append(
                Segment.create(
                    source_document_id=0,
                    stable_key=_stable_key(source_text, sequence),
                    source_text=source_text,
                    sequence=sequence,
                ),
            )
            spans.append(
                {
                    "sequence": sequence,
                    "byte_start": byte_start,
                    "byte_end": byte_end,
                },
            )
        byte_cursor += line_bytes + terminator_bytes
        index += terminator
        line_start = index

    if line_start < length:
        source_text, target_start, target_end = _stripped(text, line_start, length)
        if target_start < target_end:
            sequence += 1
            byte_start = byte_cursor + _byte_length(
                text[line_start:target_start],
                content_encoding,
            )
            byte_end = byte_cursor + _byte_length(
                text[line_start:target_end],
                content_encoding,
            )
            segments.append(
                Segment.create(
                    source_document_id=0,
                    stable_key=_stable_key(source_text, sequence),
                    source_text=source_text,
                    sequence=sequence,
                ),
            )
            spans.append(
                {
                    "sequence": sequence,
                    "byte_start": byte_start,
                    "byte_end": byte_end,
                },
            )
    return segments, spans


def _stripped(text: str, line_start: int, line_end: int) -> tuple[str, int, int]:
    """Return (stripped text, target char start, target char end) for a line."""
    content = text[line_start:line_end]
    leading = len(content) - len(content.lstrip())
    trailing = len(content) - len(content.rstrip())
    return content.strip(), line_start + leading, line_end - trailing


def _byte_length(text: str, content_encoding: str) -> int:
    """Return the number of bytes ``text`` occupies in the content encoding."""
    return len(text.encode(content_encoding))


def _stable_key(source_text: str, sequence: int) -> str:
    """Return a stable key for a segment based on its text and sequence."""
    content = f"{sequence}:{source_text}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


PARSER_VERSION = TxtParser.version


def parse_txt(
    file_path: Path,
    *,
    project_id: int,
    name: str | None = None,
    encoding: str = "utf-8",
) -> tuple[SourceDocument, list[Segment]]:
    """Convenience function that parses a TXT file using the default TXT parser."""
    return TxtParser().parse(
        file_path,
        project_id=project_id,
        name=name,
        encoding=encoding,
    )
