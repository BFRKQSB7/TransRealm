"""SRT parser producing stable cue Segments with byte fidelity.

Each subtitle cue becomes one translatable Segment whose ``source_text`` is the
cue's text block (its non-blank text lines joined by the exact line break
characters of the file). The cue index, timing line, and optional settings are
structural: they are never translated and their bytes are preserved. The parser
validates the timing syntax (rejecting malformed timestamps), rejects duplicate
cue timings (which would make cue identity ambiguous), and records each cue's
position, index, timing strings, settings, and the byte span of its text block
in the versioned format metadata envelope. The exporter re-parses the raw bytes
with the same ``extract_cues`` and verifies every stored cue against the
re-derived cues, so a tampered or misaligned envelope is refused.

This is the SRT-specific locator required by DEC-P1-T01-FOUNDATION (plan 2):
it does not reuse TXT's flat byte-span or JSON's path semantics, but lives
inside the shared versioned envelope with its own ``locator.type``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument
from transrealm.infrastructure.fidelity import (
    bom_length,
    build_srt_envelope,
    detect_bom,
    detect_newline,
    resolve_encodings,
)

_TIMING_RE = re.compile(
    r"^(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})(.*)$",
)
_TIMESTAMP_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})$")
_INDEX_RE = re.compile(r"^\s*\d+\s*$")


class SRTParseError(ValueError):
    """The input is not a well-formed SRT document."""


@dataclass(frozen=True)
class Cue:
    """One subtitle cue.

    ``byte_start``/``byte_end`` cover the cue's text block inside the raw file
    bytes (BOM length included). ``index`` is the printed cue number when the
    cue has one (an index-less cue has ``index=None``). ``start``/``end`` are
    the exact timing strings as written (comma or dot separator preserved);
    ``settings`` is the stripped tail after the end time (``X1:...`` etc.).
    ``text`` is the decoded text block with its exact internal line breaks.
    """

    sequence: int
    index: str | None
    start: str
    end: str
    settings: str
    byte_start: int
    byte_end: int
    text: str


class SRTParser:
    """Parser for the ``srt`` format.

    Segments are one per cue, in document order. ``source_text`` is the cue
    text block (multi-line text lines joined by the file's line breaks);
    ``stable_key`` is a hash of the cue position, timing, and text, so keys are
    stable across imports of the same bytes and never collide.
    """

    format = "srt"
    version = "1.0.0"

    def parse(
        self,
        file_path: Path,
        *,
        project_id: int,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Parse an SRT file into a SourceDocument and Segments.

        Args:
            file_path: Path to the SRT file.
            project_id: Project that owns the source document.
            name: Optional display name for the source document. Defaults to
                the file name.
            encoding: Text encoding to use when reading the file. A BOM-capable
                codec (``utf-8``/``utf-8-sig`` for a UTF-8 BOM, ``utf-16`` for a
                UTF-16 BOM) strips the BOM and records it in the envelope.

        Returns:
            A tuple of (SourceDocument, list of Segments).

        Raises:
            FileNotFoundError: If the file does not exist.
            UnicodeDecodeError: If the file cannot be decoded with the given
                encoding.
            SRTParseError: If the file is not valid SRT (bad timing, duplicate
                cue timings, or structural damage).
        """
        raw_bytes = file_path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()

        bom = detect_bom(raw_bytes)
        content_encoding, decode_encoding = resolve_encodings(encoding, bom)
        text = raw_bytes.decode(decode_encoding)
        newline = detect_newline(text)

        cues = extract_cues(
            text,
            content_encoding=content_encoding,
            bom_len=bom_length(bom),
        )

        segments = [self._to_segment(cue) for cue in cues]
        locator_segments: list[dict[str, object]] = [
            {
                "sequence": cue.sequence,
                "index": cue.index,
                "start": cue.start,
                "end": cue.end,
                "settings": cue.settings,
                "byte_start": cue.byte_start,
                "byte_end": cue.byte_end,
            }
            for cue in cues
        ]
        envelope = build_srt_envelope(
            encoding=content_encoding,
            bom=bom,
            newline=newline,
            parser_version=self.version,
            source_hash=source_hash,
            segments=locator_segments,
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

    @staticmethod
    def _to_segment(cue: Cue) -> Segment:
        return Segment.create(
            source_document_id=0,
            stable_key=_stable_key(cue.sequence, cue.start, cue.end, cue.text),
            source_text=cue.text,
            sequence=cue.sequence,
        )


def extract_cues(
    text: str,
    *,
    content_encoding: str,
    bom_len: int = 0,
) -> list[Cue]:
    """Validate ``text`` as an SRT document and return its cues.

    The returned cues are in document order and carry the byte span of their
    text block inside the raw file. A cue is an optional index line, a timing
    line, and one or more non-blank text lines; a blank line ends the cue.
    After the timing line everything until a blank line (or EOF) is text, so a
    text line that itself looks like a timestamp is preserved as text.
    Malformed timestamps, duplicate cue timings, index-less structural damage,
    cues with no text, and a text line that is an index followed by a timing
    line (a missing blank-line separator between two cues) raise
    :class:`SRTParseError`.

    Args:
        text: The decoded file text (BOM already stripped by the codec).
        content_encoding: Plain codec used to compute byte offsets.
        bom_len: Byte length of the file's BOM, added to every offset.
    """
    lines = _scan_lines(text, content_encoding, bom_len)
    cues: list[Cue] = []
    sequence = 0
    seen_timings: set[tuple[int, int, int, int, int, int, int, int]] = set()
    index = 0
    n = len(lines)
    while index < n:
        content, _terminator, _byte_start, _byte_end = lines[index]
        if not content.strip():
            index += 1
            continue
        cue_index: str | None = None
        if _INDEX_RE.fullmatch(content):
            cue_index = content.strip()
            index += 1
            if index >= n:
                raise SRTParseError(
                    f"Cue index {cue_index!r} is not followed by a timing line.",
                )
            content, _terminator, _byte_start, _byte_end = lines[index]
        timing = _parse_timing(content)
        if timing is None:
            raise SRTParseError(
                f"Expected an SRT timing line but got {content!r}.",
            )
        start, end, settings, timing_key = timing
        if timing_key in seen_timings:
            raise SRTParseError(
                f"Duplicate cue timing {start} --> {end}.",
            )
        seen_timings.add(timing_key)
        index += 1

        parts: list[str] = []
        prev_term = ""
        first = True
        block_byte_start: int | None = None
        block_byte_end: int | None = None
        while index < n:
            text_content, text_term, text_byte_start, _text_byte_end = lines[index]
            if not text_content.strip():
                break
            if _INDEX_RE.fullmatch(text_content) and index + 1 < n:
                next_content, _next_term, _next_byte_start, _next_byte_end = lines[index + 1]
                if _parse_timing(next_content) is not None:
                    raise SRTParseError(
                        "Missing blank line between cues: a text line looks like "
                        "the next cue's index.",
                    )
            if first:
                block_byte_start = text_byte_start
                first = False
            else:
                parts.append(prev_term)
            parts.append(text_content)
            block_byte_end = text_byte_start + len(
                text_content.encode(content_encoding),
            )
            prev_term = text_term
            index += 1
        if block_byte_start is None or block_byte_end is None:
            raise SRTParseError(
                f"Cue {start} --> {end} has no text; nothing to translate.",
            )

        sequence += 1
        cues.append(
            Cue(
                sequence=sequence,
                index=cue_index,
                start=start,
                end=end,
                settings=settings,
                byte_start=block_byte_start,
                byte_end=block_byte_end,
                text="".join(parts),
            ),
        )
    return cues


def _scan_lines(
    text: str,
    content_encoding: str,
    bom_len: int,
) -> list[tuple[str, str, int, int]]:
    """Split ``text`` into physical lines with byte offsets.

    Returns ``(content, terminator, byte_start, byte_end)`` per line where
    ``byte_start``/``byte_end`` frame the content plus its terminator and are
    offset by ``bom_len`` into the raw file bytes.
    """
    lines: list[tuple[str, str, int, int]] = []
    index = 0
    n = len(text)
    byte = bom_len
    while index < n:
        line_start = index
        while index < n and text[index] not in "\r\n":
            index += 1
        content = text[line_start:index]
        terminator = ""
        if index < n:
            if text[index] == "\r":
                if index + 1 < n and text[index + 1] == "\n":
                    terminator = "\r\n"
                else:
                    terminator = "\r"
            else:
                terminator = "\n"
            index += len(terminator)
        byte_start = byte
        byte += len(content.encode(content_encoding)) + len(
            terminator.encode(content_encoding),
        )
        lines.append((content, terminator, byte_start, byte))
    return lines


def _parse_timing(
    content: str,
) -> tuple[str, str, str, tuple[int, int, int, int, int, int, int, int]] | None:
    """Parse a timing line; return (start, end, settings, normalized key)."""
    match = _TIMING_RE.match(content.strip())
    if match is None:
        return None
    start, end, settings = match.group(1), match.group(2), match.group(3).strip()
    start_key = _split_timestamp(start)
    end_key = _split_timestamp(end)
    if start_key is None or end_key is None:
        return None
    return start, end, settings, (*start_key, *end_key)


def _split_timestamp(timestamp: str) -> tuple[int, int, int, int] | None:
    """Validate and normalize one timestamp string."""
    match = _TIMESTAMP_RE.fullmatch(timestamp)
    if match is None:
        return None
    hours, minutes, seconds, milliseconds = (int(group) for group in match.groups())
    if minutes > 59 or seconds > 59 or milliseconds > 999:
        return None
    return hours, minutes, seconds, milliseconds


def _stable_key(sequence: int, start: str, end: str, text: str) -> str:
    """Return a stable key from the cue position, timing, and text."""
    content = f"{sequence}\x00{start}\x00{end}\x00{text}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


PARSER_VERSION = SRTParser.version


def parse_srt(
    file_path: Path,
    *,
    project_id: int,
    name: str | None = None,
    encoding: str = "utf-8",
) -> tuple[SourceDocument, list[Segment]]:
    """Convenience function that parses an SRT file using the default SRT parser."""
    return SRTParser().parse(
        file_path,
        project_id=project_id,
        name=name,
        encoding=encoding,
    )


__all__ = [
    "Cue",
    "PARSER_VERSION",
    "SRTParser",
    "SRTParseError",
    "extract_cues",
    "parse_srt",
]
