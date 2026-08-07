"""ASS/SSA parser producing stable Dialogue Segments with byte fidelity.

ASS (ScriptType ``v4.00+``) and SSA (``v4.00``) share one SubStation event
model, so they share a single parsing engine: each ``Dialogue:`` event's Text
field becomes one translatable Segment whose ``source_text`` is the raw Text
field (commas, inline override tags and escapes such as ``\\N`` included), while
every section, the Format line, ``Comment:`` and other event types, all
non-Text fields (Layer/Marked, Start, End, Style, Name, margins, Effect) and the
line endings are structural and preserved byte-for-byte. The parser validates
the file signature (must start with ``[Script Info]`` and declare a
``ScriptType`` matching the format, so an ASS file is not silently read as SSA
or vice versa), requires the standard ``[Events] Format:`` line so the Text
field is split on the correct number of commas without guessing, validates the
Start/End timestamps, and records each Dialogue event's position, timing
strings, and the byte span of its Text field in the versioned format metadata
envelope. The exporter re-parses the raw bytes with the same ``extract_events``
and verifies every stored event against the re-derived events, so a tampered or
misaligned envelope is refused.

This is the ASS/SSA-specific locator required by DEC-P1-T01-FOUNDATION
(plan 2): ``ass.events`` / ``ssa.events`` live inside the shared versioned
envelope with their own ``locator.type`` and do not reuse TXT's flat byte-span,
JSON's path, or SRT/VTT cue semantics.
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
    build_ass_envelope,
    build_ssa_envelope,
    detect_bom,
    detect_newline,
    resolve_encodings,
)

# ASS/SSA timestamps are ``h:mm:ss.cc``: hours one or more digits, minutes and
# seconds exactly two digits (00-59), centiseconds exactly two digits. ASS/SSA
# use centiseconds (two digits), unlike SRT/VTT milliseconds (three digits).
_TIMING_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})\.(\d{2})$")

# The standard [Events] Format field lists (lower-cased), one per format. The
# Text field is always the last field and may itself contain commas, so the
# Text is split after exactly this many fields without guessing.
_STANDARD_EVENTS_FORMAT: dict[str, list[str]] = {
    "ass": [
        "layer",
        "start",
        "end",
        "style",
        "name",
        "marginl",
        "marginr",
        "marginv",
        "effect",
        "text",
    ],
    "ssa": [
        "marked",
        "start",
        "end",
        "style",
        "name",
        "marginl",
        "marginr",
        "marginv",
        "effect",
        "text",
    ],
}

_SCRIPT_TYPES: dict[str, str] = {
    "ass": "v4.00+",
    "ssa": "v4.00",
}

# A line's leading keyword (``Dialogue``, ``Format``, ``ScriptType``, ...)
# optionally followed by whitespace before the colon. Matching on the stripped
# line so trailing spaces, indentation, or ``Key :`` variants are parsed rather
# than silently swallowed as structural lines.
_KEY_RE = re.compile(r"^([a-z][a-z0-9]*)\s*:", re.IGNORECASE)


class AssSsaParseError(ValueError):
    """The input is not a well-formed ASS/SSA document."""


@dataclass(frozen=True)
class AssSsaEvent:
    """One ASS/SSA Dialogue event.

    ``byte_start``/``byte_end`` cover the event's Text field inside the raw
    file bytes (BOM length included). ``start``/``end`` are the exact Start/End
    field strings as written. ``text`` is the decoded Text field verbatim
    (commas, leading/trailing spaces, tags and escapes included).
    """

    sequence: int
    start: str
    end: str
    byte_start: int
    byte_end: int
    text: str


class _AssSsaParserBase:
    """Shared ASS/SSA parsing logic; subclasses fix format and ScriptType."""

    format = ""
    version = "1.0.0"
    expected_script_type = ""

    def parse(
        self,
        file_path: Path,
        *,
        project_id: int,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Parse an ASS/SSA file into a SourceDocument and Segments.

        Args:
            file_path: Path to the ASS or SSA file.
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
            AssSsaParseError: If the file is not valid ASS/SSA (missing
                signature, wrong ScriptType, missing or unsupported Events
                Format, malformed Dialogue, or structural damage).
        """
        raw_bytes = file_path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()

        bom = detect_bom(raw_bytes)
        content_encoding, decode_encoding = resolve_encodings(encoding, bom)
        text = raw_bytes.decode(decode_encoding)
        newline = detect_newline(text)

        events = extract_events(
            text,
            format=self.format,
            content_encoding=content_encoding,
            bom_len=bom_length(bom),
        )

        segments = [self._to_segment(event) for event in events]
        locator_segments: list[dict[str, object]] = [
            {
                "sequence": event.sequence,
                "start": event.start,
                "end": event.end,
                "byte_start": event.byte_start,
                "byte_end": event.byte_end,
            }
            for event in events
        ]
        builder = build_ass_envelope if self.format == "ass" else build_ssa_envelope
        envelope = builder(
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
    def _to_segment(event: AssSsaEvent) -> Segment:
        return Segment.create(
            source_document_id=0,
            stable_key=_stable_key(
                event.sequence,
                event.start,
                event.end,
                event.text,
            ),
            source_text=event.text,
            sequence=event.sequence,
        )


class AssParser(_AssSsaParserBase):
    """Parser for the ``ass`` format (ScriptType ``v4.00+``)."""

    format = "ass"
    expected_script_type = _SCRIPT_TYPES["ass"]


class SsaParser(_AssSsaParserBase):
    """Parser for the ``ssa`` format (ScriptType ``v4.00``)."""

    format = "ssa"
    expected_script_type = _SCRIPT_TYPES["ssa"]


def extract_events(
    text: str,
    *,
    format: str,  # noqa: A002
    content_encoding: str,
    bom_len: int = 0,
) -> list[AssSsaEvent]:
    """Validate ``text`` as an ASS/SSA document and return its Dialogue events.

    The returned events are in document order and carry the byte span of their
    Text field inside the raw file. A SubStation file must start with the
    ``[Script Info]`` section and declare a ``ScriptType`` that matches the
    expected format (``v4.00+`` for ASS, ``v4.00`` for SSA); a mismatched
    ScriptType is refused rather than silently downgraded. Sections are the
    ``[name]`` headers; every non-Events section (``[Script Info]``, the style
    sections, ``[Fonts]`` etc.), comments (lines starting with ``;``), the
    ``[Events] Format:`` line, ``Comment:`` events and any other event types
    are structural bytes that never produce a Segment. Line classification is
    whitespace-tolerant (trailing spaces on section headers, indented lines,
    and ``Key :`` variants are still recognized) so such input is parsed
    rather than silently swallowed as structural lines.

    ``[Events]`` must declare the standard ``Format:`` field list for its
    ScriptType (a missing, duplicate or reordered Format line is refused) so
    the Text field is split on exactly the right number of commas without
    guessing. Each ``Dialogue:`` line must have that many fields, its Start/End
    fields (positions 1 and 2) must be valid ``h:mm:ss.cc`` timestamps, and its
    Text field (the last, comma-tolerant field) must be non-empty. Unlike
    SRT/VTT, duplicate timings are allowed (multiple simultaneous Dialogue
    events differing by style are valid); the stable key includes the event
    sequence so keys never collide.

    Args:
        text: The decoded file text (BOM already stripped by the codec).
        format: ``"ass"`` or ``"ssa"``, selecting the expected ScriptType and
            Events Format.
        content_encoding: Plain codec used to compute byte offsets.
        bom_len: Byte length of the file's BOM, added to every offset.
    """
    if not text.startswith("[Script Info]"):
        raise AssSsaParseError(
            "Not a SubStation file: missing the '[Script Info]' section.",
        )
    lines = _scan_lines(text, content_encoding, bom_len)
    expected_fields = _STANDARD_EVENTS_FORMAT[format]

    events: list[AssSsaEvent] = []
    section = ""
    script_type_found = False
    events_format: list[str] | None = None
    sequence = 0
    index = 0
    n = len(lines)
    while index < n:
        content, _terminator, _byte_start, _byte_end = lines[index]
        stripped = content.strip()
        if not stripped or stripped.startswith(";"):
            index += 1
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            index += 1
            continue
        key = _match_key(content)
        if section == "script info":
            if key == "scripttype":
                value = content.split(":", 1)[1].strip().lower()
                if value != _SCRIPT_TYPES[format]:
                    raise AssSsaParseError(
                        f"ScriptType {content.split(':', 1)[1].strip()!r} does not "
                        f"match the {format} format "
                        f"({_SCRIPT_TYPES[format]!r}).",
                    )
                script_type_found = True
            index += 1
            continue
        if section == "events":
            if key == "format":
                if events_format is not None:
                    raise AssSsaParseError("Duplicate Format line in [Events].")
                fields = [
                    field.strip().lower()
                    for field in content.split(":", 1)[1].split(",")
                ]
                if fields != expected_fields:
                    raise AssSsaParseError(
                        f"Unsupported [Events] Format: {content!r}.",
                    )
                events_format = fields
                index += 1
                continue
            if key == "dialogue":
                if events_format is None:
                    raise AssSsaParseError(
                        "Dialogue line appears before the [Events] Format line.",
                    )
                start, end, text_field, byte_start, byte_end = _dialogue_event(
                    content,
                    field_count=len(events_format),
                    line_byte_start=_byte_start,
                    content_encoding=content_encoding,
                )
                sequence += 1
                events.append(
                    AssSsaEvent(
                        sequence=sequence,
                        start=start,
                        end=end,
                        byte_start=byte_start,
                        byte_end=byte_end,
                        text=text_field,
                    ),
                )
                index += 1
                continue
            # Comment: and other event types are structural: preserved
            # byte-for-byte and never translated.
            index += 1
            continue
        index += 1

    if not script_type_found:
        raise AssSsaParseError(
            "Missing 'ScriptType:' line in [Script Info].",
        )
    return events


def _match_key(content: str) -> str | None:
    """Return the lower-cased leading keyword of ``content`` before ``:``.

    Matching uses the stripped line and allows optional whitespace around the
    colon (``Dialogue:``, ``Dialogue :``, ``  Format :``), so whitespace
    variants are parsed rather than silently swallowed as structural lines.
    Returns ``None`` for blank, comment, section-header, or keyword-less lines.
    """
    match = _KEY_RE.match(content.strip())
    return match.group(1).lower() if match is not None else None


def _dialogue_event(
    content: str,
    *,
    field_count: int,
    line_byte_start: int,
    content_encoding: str,
) -> tuple[str, str, str, int, int]:
    """Parse one Dialogue line; return (start, end, text, byte_start, byte_end).

    The Text field is everything after the ``field_count - 1``-th comma, so
    commas inside Text are preserved. ``byte_start``/``byte_end`` frame the
    Text field inside the raw file bytes.
    """
    head, _colon, tail = content.partition(":")
    parts = tail.split(",", maxsplit=field_count - 1)
    if len(parts) != field_count:
        raise AssSsaParseError(
            f"Dialogue line has {len(parts)} fields, expected {field_count}.",
        )
    start = parts[1]
    end = parts[2]
    if not _valid_timing(start) or not _valid_timing(end):
        raise AssSsaParseError(
            f"Dialogue has invalid timing {start.strip()!r} --> {end.strip()!r}.",
        )
    text = parts[-1]
    if not text.strip():
        raise AssSsaParseError(
            "Dialogue has an empty Text field; nothing to translate.",
        )
    # The Text field starts after the (field_count - 1)-th comma in ``tail``.
    text_char_start = len("".join(parts[:-1])) + (field_count - 1)
    absolute_char = len(head) + 1 + text_char_start
    byte_start = line_byte_start + len(
        content[:absolute_char].encode(content_encoding),
    )
    byte_end = line_byte_start + len(content.encode(content_encoding))
    return start, end, text, byte_start, byte_end


def _valid_timing(value: str) -> bool:
    """Return whether ``value`` is a valid ``h:mm:ss.cc`` ASS/SSA timestamp."""
    match = _TIMING_RE.fullmatch(value.strip())
    if match is None:
        return False
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    return minutes <= 59 and seconds <= 59


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


def _stable_key(sequence: int, start: str, end: str, text: str) -> str:
    """Return a stable key from the event position, timing, and text."""
    content = f"{sequence}\x00{start}\x00{end}\x00{text}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_ass(
    file_path: Path,
    *,
    project_id: int,
    name: str | None = None,
    encoding: str = "utf-8",
) -> tuple[SourceDocument, list[Segment]]:
    """Convenience function that parses an ASS file using the default ASS parser."""
    return AssParser().parse(
        file_path,
        project_id=project_id,
        name=name,
        encoding=encoding,
    )


def parse_ssa(
    file_path: Path,
    *,
    project_id: int,
    name: str | None = None,
    encoding: str = "utf-8",
) -> tuple[SourceDocument, list[Segment]]:
    """Convenience function that parses an SSA file using the default SSA parser."""
    return SsaParser().parse(
        file_path,
        project_id=project_id,
        name=name,
        encoding=encoding,
    )


__all__ = [
    "AssParser",
    "AssSsaEvent",
    "AssSsaParseError",
    "SsaParser",
    "extract_events",
    "parse_ass",
    "parse_ssa",
]
