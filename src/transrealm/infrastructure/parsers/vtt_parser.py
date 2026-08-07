"""VTT parser producing stable cue Segments with byte fidelity.

Each WebVTT cue's text block becomes one translatable Segment whose
``source_text`` is the cue's payload (its non-blank text lines joined by the
exact line break characters of the file). The WEBVTT signature line, any NOTE /
STYLE / REGION blocks, the cue identifier, the timing line, and the optional
settings are structural: they are never translated and their bytes are
preserved. The parser validates the WebVTT file signature (so an SRT or other
non-WebVTT file is refused rather than silently downgraded), validates the
timing syntax, rejects duplicate cue timings, and records each cue's position,
identifier, timing strings, settings, and the byte span of its text block in
the versioned format metadata envelope. The exporter re-parses the raw bytes
with the same ``extract_cues`` and verifies every stored cue against the
re-derived cues, so a tampered or misaligned envelope is refused.

This is the VTT-specific locator required by DEC-P1-T01-FOUNDATION (plan 2):
it does not reuse TXT's flat byte-span, JSON's path, or SRT's index semantics,
but lives inside the shared versioned envelope with its own ``locator.type``.
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
    build_vtt_envelope,
    detect_bom,
    detect_newline,
    resolve_encodings,
)

# A WebVTT timestamp is either the full ``hours:minutes:seconds.milliseconds``
# form (hours one or more digits, minutes/seconds two, milliseconds exactly
# three) or the ``minutes:seconds.milliseconds`` form with the hours omitted.
# The separator is a full stop (``.``), never the comma SRT uses.
_VTT_TIMESTAMP = r"(?:\d{1,}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
_VTT_TIMING_RE = re.compile(
    rf"^({_VTT_TIMESTAMP})\s*-->\s*({_VTT_TIMESTAMP})(.*)$",
)
_FULL_TS_RE = re.compile(r"^(\d{1,}):(\d{2}):(\d{2})\.(\d{3})$")
_PARTIAL_TS_RE = re.compile(r"^(\d{2}):(\d{2})\.(\d{3})$")


class VTTParseError(ValueError):
    """The input is not a well-formed WebVTT document."""


@dataclass(frozen=True)
class VttCue:
    """One WebVTT cue.

    ``byte_start``/``byte_end`` cover the cue's text block inside the raw file
    bytes (BOM length included). ``id`` is the cue identifier when the cue has
    one (an identifier-less cue has ``id=None``). ``start``/``end`` are the
    exact timing strings as written; ``settings`` is the stripped tail after
    the end time (``align:start`` etc.). ``text`` is the decoded text block
    with its exact internal line breaks.
    """

    sequence: int
    id: str | None
    start: str
    end: str
    settings: str
    byte_start: int
    byte_end: int
    text: str


class VTTParser:
    """Parser for the ``vtt`` format.

    Segments are one per cue, in document order. ``source_text`` is the cue
    text block (multi-line text lines joined by the file's line breaks);
    ``stable_key`` is a hash of the cue position, timing, identifier, and text,
    so keys are stable across imports of the same bytes and never collide.
    """

    format = "vtt"
    version = "1.0.0"

    def parse(
        self,
        file_path: Path,
        *,
        project_id: int,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Parse a WebVTT file into a SourceDocument and Segments.

        Args:
            file_path: Path to the VTT file.
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
            VTTParseError: If the file is not valid WebVTT (missing signature,
                bad timing, duplicate cue timings, or structural damage).
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
                "id": cue.id,
                "start": cue.start,
                "end": cue.end,
                "settings": cue.settings,
                "byte_start": cue.byte_start,
                "byte_end": cue.byte_end,
            }
            for cue in cues
        ]
        envelope = build_vtt_envelope(
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
    def _to_segment(cue: VttCue) -> Segment:
        return Segment.create(
            source_document_id=0,
            stable_key=_stable_key(
                cue.sequence,
                cue.start,
                cue.end,
                cue.id,
                cue.text,
            ),
            source_text=cue.text,
            sequence=cue.sequence,
        )


def extract_cues(
    text: str,
    *,
    content_encoding: str,
    bom_len: int = 0,
) -> list[VttCue]:
    """Validate ``text`` as a WebVTT document and return its cues.

    The returned cues are in document order and carry the byte span of their
    text block inside the raw file. A WebVTT file must start with the
    ``WEBVTT`` signature (a space-separated title is allowed after it). The
    header is followed by optional NOTE / STYLE / REGION blocks (each consumed
    up to a blank line) and then cues. A cue is an optional identifier line
    (text that does not contain ``-->``) and a timing line, followed by one or
    more non-blank text lines; a blank line or a line containing ``-->`` ends
    the cue text (the latter starts a new cue, as WebVTT cue text cannot
    contain ``-->``).

    Missing or malformed signatures, malformed timestamps, duplicate cue
    timings, cues with no text, identifier-less bare text lines in the body,
    and a text line containing ``-->`` that is not a valid timing line raise
    :class:`VTTParseError`. A non-WebVTT file (for example an SRT document) is
    refused rather than silently downgraded.

    Args:
        text: The decoded file text (BOM already stripped by the codec).
        content_encoding: Plain codec used to compute byte offsets.
        bom_len: Byte length of the file's BOM, added to every offset.
    """
    lines = _scan_lines(text, content_encoding, bom_len)
    if not lines or not lines[0][0].startswith("WEBVTT"):
        raise VTTParseError("Not a WebVTT file: missing the 'WEBVTT' signature.")
    signature_rest = lines[0][0][6:]
    if signature_rest and not signature_rest.startswith(" "):
        raise VTTParseError(
            "WebVTT signature must be followed by a space or the end of the line.",
        )

    cues: list[VttCue] = []
    sequence = 0
    seen_timings: set[tuple[int, int, int, int, int, int, int, int]] = set()
    index = 1
    n = len(lines)
    while index < n:
        content, _terminator, _byte_start, _byte_end = lines[index]
        if not content.strip():
            index += 1
            continue
        if content == "STYLE" or content == "REGION":
            index = _consume_block(lines, index)
            continue
        if _is_note_line(content):
            index = _consume_block(lines, index)
            continue

        cue_id: str | None = None
        timing = _parse_timing(content)
        if timing is None:
            if "-->" in content:
                raise VTTParseError(
                    f"Expected a WebVTT timing line but got {content!r}.",
                )
            cue_id = content.strip()
            index += 1
            if index >= n:
                raise VTTParseError(
                    f"Cue identifier {cue_id!r} is not followed by a timing line.",
                )
            content, _terminator, _byte_start, _byte_end = lines[index]
            timing = _parse_timing(content)
            if timing is None:
                raise VTTParseError(
                    f"Expected a WebVTT timing line after cue identifier "
                    f"{cue_id!r} but got {content!r}.",
                )
        start, end, settings, timing_key = timing
        if timing_key in seen_timings:
            raise VTTParseError(
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
            if "-->" in text_content:
                break
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
            raise VTTParseError(
                f"Cue {start} --> {end} has no text; nothing to translate.",
            )

        sequence += 1
        cues.append(
            VttCue(
                sequence=sequence,
                id=cue_id,
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


def _consume_block(lines: list[tuple[str, str, int, int]], index: int) -> int:
    """Skip a STYLE/REGION/NOTE block and its terminating blank line."""
    index += 1
    while index < len(lines) and lines[index][0].strip():
        index += 1
    return index + 1


def _is_note_line(content: str) -> bool:
    """Return whether a line starts a NOTE block (``NOTE`` + space or EOL)."""
    return content == "NOTE" or content.startswith("NOTE ")


def _parse_timing(
    content: str,
) -> tuple[str, str, str, tuple[int, int, int, int, int, int, int, int]] | None:
    """Parse a timing line; return (start, end, settings, normalized key)."""
    match = _VTT_TIMING_RE.match(content.strip())
    if match is None:
        return None
    start, end, settings = match.group(1), match.group(2), match.group(3).strip()
    start_key = _split_timestamp(start)
    end_key = _split_timestamp(end)
    if start_key is None or end_key is None:
        return None
    return start, end, settings, (*start_key, *end_key)


def _split_timestamp(timestamp: str) -> tuple[int, int, int, int] | None:
    """Validate and normalize one WebVTT timestamp string.

    Minutes and seconds must be in 00-59 (matching the W3C grammar and the
    SRT precedent); milliseconds are limited to three digits by the regexes.
    Hours may be any number of digits, as the spec allows.
    """
    full = _FULL_TS_RE.fullmatch(timestamp)
    if full is not None:
        hours, minutes, seconds, milliseconds = (
            int(group) for group in full.groups()
        )
    else:
        partial = _PARTIAL_TS_RE.fullmatch(timestamp)
        if partial is None:
            return None
        minutes, seconds, milliseconds = (int(group) for group in partial.groups())
        hours = 0
    if minutes > 59 or seconds > 59:
        return None
    return hours, minutes, seconds, milliseconds


def _stable_key(sequence: int, start: str, end: str, id: str | None, text: str) -> str:
    """Return a stable key from the cue position, timing, identifier, and text."""
    content = f"{sequence}\x00{start}\x00{end}\x00{id or ''}\x00{text}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


PARSER_VERSION = VTTParser.version


def parse_vtt(
    file_path: Path,
    *,
    project_id: int,
    name: str | None = None,
    encoding: str = "utf-8",
) -> tuple[SourceDocument, list[Segment]]:
    """Convenience function that parses a WebVTT file using the default VTT parser."""
    return VTTParser().parse(
        file_path,
        project_id=project_id,
        name=name,
        encoding=encoding,
    )


__all__ = [
    "PARSER_VERSION",
    "VTTParseError",
    "VTTParser",
    "VttCue",
    "extract_cues",
    "parse_vtt",
]
