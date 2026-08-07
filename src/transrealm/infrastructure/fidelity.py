"""Shared fidelity carrier: format metadata envelope and encoding/BOM helpers.

The fidelity carrier (DEC-P1-T01-FOUNDATION, plan 2) persists a source
document's raw bytes plus a versioned ``format_metadata`` envelope holding
encoding, BOM, newline style, parser/metadata version, the source hash, and
format-specific locator information. Parsers generate the envelope; exporters
verify it against the raw bytes before replacing only the target spans. This
module is shared so the parser and exporter stay consistent on the envelope
schema and encoding/BOM rules.
"""

from __future__ import annotations

import json

FIDELITY_SCHEMA_VERSION = 1
LOCATOR_TYPE_TXT_BYTE_SPANS = "txt.byte_spans"
LOCATOR_TYPE_JSON_PATHS = "json.paths"
LOCATOR_TYPE_SRT_CUES = "srt.cues"
LOCATOR_TYPE_VTT_CUES = "vtt.cues"
LOCATOR_TYPE_ASS_EVENTS = "ass.events"
LOCATOR_TYPE_SSA_EVENTS = "ssa.events"

_BOMS = {
    "utf-8": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
}

_BOM_LENGTHS = {"utf-8": 3, "utf-16-le": 2, "utf-16-be": 2}


class FidelityError(ValueError):
    """The fidelity carrier is missing, malformed, or failed validation."""


def detect_bom(raw: bytes) -> str | None:
    """Return the BOM kind present at the start of ``raw``, or None."""
    for kind, prefix in _BOMS.items():
        if raw.startswith(prefix):
            return kind
    return None


def bom_bytes(bom: str | None) -> bytes:
    """Return the byte prefix for a BOM kind (empty when None)."""
    if bom is None:
        return b""
    return _BOMS[bom]


def bom_length(bom: str | None) -> int:
    """Return the number of bytes a BOM occupies at the start of a file."""
    if bom is None:
        return 0
    return _BOM_LENGTHS[bom]


def _normalize_encoding(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def resolve_encodings(declared: str, bom: str | None) -> tuple[str, str]:
    """Return ``(content_encoding, decode_encoding)``.

    ``content_encoding`` is the plain codec for target-span text (no BOM).
    ``decode_encoding`` strips the BOM when one is present (``utf-8-sig`` /
    ``utf-16``). A declared plain encoding is authoritative: if a file starts
    with a BOM the declared codec cannot handle, decoding fails rather than
    silently switching encodings.
    """
    declared = _normalize_encoding(declared)
    if declared in {"utf8", "utf-8-sig"}:
        declared = "utf-8"
    if declared == "utf-8":
        if bom == "utf-8":
            return "utf-8", "utf-8-sig"
        return "utf-8", "utf-8"
    if declared == "utf-16":
        if bom in {"utf-16-le", "utf-16-be"}:
            return bom, "utf-16"
        return "utf-16-le", "utf-16"
    if declared == "utf-16-le":
        return "utf-16-le", "utf-16" if bom == "utf-16-le" else "utf-16-le"
    if declared == "utf-16-be":
        return "utf-16-be", "utf-16" if bom == "utf-16-be" else "utf-16-be"
    return declared, declared


def detect_newline(text: str) -> str:
    """Return the newline style used in ``text`` (crlf/lf/cr/none)."""
    if "\r\n" in text:
        return "crlf"
    if "\n" in text:
        return "lf"
    if "\r" in text:
        return "cr"
    return "none"


def build_txt_envelope(
    *,
    encoding: str,
    bom: str | None,
    newline: str,
    parser_version: str,
    source_hash: str,
    spans: list[dict[str, int]],
) -> dict[str, object]:
    """Build the versioned TXT format metadata envelope."""
    return {
        "schema_version": FIDELITY_SCHEMA_VERSION,
        "format": "txt",
        "encoding": encoding,
        "bom": bom,
        "newline": newline,
        "parser_version": parser_version,
        "source_hash": source_hash,
        "locator": {
            "type": LOCATOR_TYPE_TXT_BYTE_SPANS,
            "segments": spans,
        },
    }


def build_json_envelope(
    *,
    encoding: str,
    bom: str | None,
    newline: str,
    parser_version: str,
    source_hash: str,
    segments: list[dict[str, object]],
) -> dict[str, object]:
    """Build the versioned JSON format metadata envelope.

    The JSON locator is structural-path based (``json.paths``): each entry
    carries the segment's sequence, JSON Pointer path, and the byte span of its
    string value token. This is JSON's format-specific locator under
    DEC-P1-T01-FOUNDATION; it deliberately does not reuse TXT's flat byte-span
    semantics.
    """
    return {
        "schema_version": FIDELITY_SCHEMA_VERSION,
        "format": "json",
        "encoding": encoding,
        "bom": bom,
        "newline": newline,
        "parser_version": parser_version,
        "source_hash": source_hash,
        "locator": {
            "type": LOCATOR_TYPE_JSON_PATHS,
            "segments": segments,
        },
    }


def build_srt_envelope(
    *,
    encoding: str,
    bom: str | None,
    newline: str,
    parser_version: str,
    source_hash: str,
    segments: list[dict[str, object]],
) -> dict[str, object]:
    """Build the versioned SRT format metadata envelope.

    The SRT locator is cue-based (``srt.cues``): each entry carries the cue's
    position, its printed index (when present), the exact timing strings and
    optional settings, and the byte span of its text block. This is SRT's
    format-specific locator under DEC-P1-T01-FOUNDATION; it deliberately does
    not reuse TXT's flat byte-span or JSON's path semantics.
    """
    return {
        "schema_version": FIDELITY_SCHEMA_VERSION,
        "format": "srt",
        "encoding": encoding,
        "bom": bom,
        "newline": newline,
        "parser_version": parser_version,
        "source_hash": source_hash,
        "locator": {
            "type": LOCATOR_TYPE_SRT_CUES,
            "segments": segments,
        },
    }


def build_vtt_envelope(
    *,
    encoding: str,
    bom: str | None,
    newline: str,
    parser_version: str,
    source_hash: str,
    segments: list[dict[str, object]],
) -> dict[str, object]:
    """Build the versioned VTT format metadata envelope.

    The VTT locator is cue-based (``vtt.cues``): each entry carries the cue's
    position, its identifier (when present), the exact timing strings and
    optional settings, and the byte span of its text block. This is VTT's
    format-specific locator under DEC-P1-T01-FOUNDATION; it deliberately does
    not reuse TXT's flat byte-span, JSON's path, or SRT's index semantics.
    """
    return {
        "schema_version": FIDELITY_SCHEMA_VERSION,
        "format": "vtt",
        "encoding": encoding,
        "bom": bom,
        "newline": newline,
        "parser_version": parser_version,
        "source_hash": source_hash,
        "locator": {
            "type": LOCATOR_TYPE_VTT_CUES,
            "segments": segments,
        },
    }


def _build_event_envelope(
    *,
    format: str,
    locator_type: str,
    encoding: str,
    bom: str | None,
    newline: str,
    parser_version: str,
    source_hash: str,
    segments: list[dict[str, object]],
) -> dict[str, object]:
    """Build a versioned ASS/SSA-style event envelope."""
    return {
        "schema_version": FIDELITY_SCHEMA_VERSION,
        "format": format,
        "encoding": encoding,
        "bom": bom,
        "newline": newline,
        "parser_version": parser_version,
        "source_hash": source_hash,
        "locator": {
            "type": locator_type,
            "segments": segments,
        },
    }


def build_ass_envelope(
    *,
    encoding: str,
    bom: str | None,
    newline: str,
    parser_version: str,
    source_hash: str,
    segments: list[dict[str, object]],
) -> dict[str, object]:
    """Build the versioned ASS format metadata envelope.

    The ASS locator is event-based (``ass.events``): each entry carries a
    Dialogue event's position, its exact Start/End timing strings, and the byte
    span of its Text field. This is ASS's format-specific locator under
    DEC-P1-T01-FOUNDATION; it deliberately does not reuse TXT's flat byte-span,
    JSON's path, or SRT/VTT cue semantics.
    """
    return _build_event_envelope(
        format="ass",
        locator_type=LOCATOR_TYPE_ASS_EVENTS,
        encoding=encoding,
        bom=bom,
        newline=newline,
        parser_version=parser_version,
        source_hash=source_hash,
        segments=segments,
    )


def build_ssa_envelope(
    *,
    encoding: str,
    bom: str | None,
    newline: str,
    parser_version: str,
    source_hash: str,
    segments: list[dict[str, object]],
) -> dict[str, object]:
    """Build the versioned SSA format metadata envelope.

    The SSA locator is event-based (``ssa.events``): each entry carries a
    Dialogue event's position, its exact Start/End timing strings, and the byte
    span of its Text field. This is SSA's format-specific locator under
    DEC-P1-T01-FOUNDATION; it deliberately does not reuse TXT's flat byte-span,
    JSON's path, or SRT/VTT cue semantics.
    """
    return _build_event_envelope(
        format="ssa",
        locator_type=LOCATOR_TYPE_SSA_EVENTS,
        encoding=encoding,
        bom=bom,
        newline=newline,
        parser_version=parser_version,
        source_hash=source_hash,
        segments=segments,
    )


def load_envelope(format_metadata: str | None, *, expected_format: str) -> dict[str, object]:
    """Parse and validate a persisted format metadata envelope.

    Raises:
        FidelityError: If the metadata is missing, malformed, has an
            unsupported schema version, or belongs to another format.
    """
    if not format_metadata:
        raise FidelityError("Fidelity metadata is missing for this document.")
    try:
        envelope = json.loads(format_metadata)
    except (ValueError, TypeError) as exc:
        raise FidelityError("Fidelity metadata is not valid JSON.") from exc
    if not isinstance(envelope, dict):
        raise FidelityError("Fidelity metadata is not an object.")
    if envelope.get("schema_version") != FIDELITY_SCHEMA_VERSION:
        raise FidelityError(
            f"Unsupported fidelity metadata schema version: "
            f"{envelope.get('schema_version')!r}.",
        )
    if envelope.get("format") != expected_format:
        raise FidelityError(
            f"Fidelity metadata format {envelope.get('format')!r} does not match "
            f"{expected_format!r}.",
        )
    return envelope


__all__ = [
    "FIDELITY_SCHEMA_VERSION",
    "LOCATOR_TYPE_ASS_EVENTS",
    "LOCATOR_TYPE_JSON_PATHS",
    "LOCATOR_TYPE_SRT_CUES",
    "LOCATOR_TYPE_SSA_EVENTS",
    "LOCATOR_TYPE_TXT_BYTE_SPANS",
    "LOCATOR_TYPE_VTT_CUES",
    "FidelityError",
    "bom_bytes",
    "bom_length",
    "build_ass_envelope",
    "build_json_envelope",
    "build_srt_envelope",
    "build_ssa_envelope",
    "build_txt_envelope",
    "build_vtt_envelope",
    "detect_bom",
    "detect_newline",
    "load_envelope",
    "resolve_encodings",
]
