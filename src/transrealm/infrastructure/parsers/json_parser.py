"""JSON parser producing stable structural-path Segments with byte fidelity.

Only string values in value position (``string leaf values``) become
translatable Segments: object keys, numbers, booleans, nulls, and containers
are never translated. The parser validates the document against the JSON
grammar (rejecting malformed input, duplicate object keys, and nesting beyond
a safety limit) and records each string value's structural path together with
the byte span of its value token (quotes included, BOM offset included) in the
versioned format metadata envelope. The exporter re-parses the raw bytes with
the same tokenizer and verifies every stored path/span against the re-derived
leaves, so a tampered or misaligned envelope is refused.

This is the JSON-specific locator required by DEC-P1-T01-FOUNDATION (plan 2):
it does not reuse TXT's flat byte-span semantics, but lives inside the shared
versioned envelope with its own ``locator.type``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument
from transrealm.infrastructure.fidelity import (
    bom_length,
    build_json_envelope,
    detect_bom,
    detect_newline,
    resolve_encodings,
)

MAX_NESTING_DEPTH = 512

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")

_WHITESPACE = frozenset(" \t\n\r")

_STRING_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

_OBJ = "obj"
_ARR = "arr"


class JSONParseError(ValueError):
    """The input is not valid JSON or exceeds the nesting safety limit."""


@dataclass(frozen=True)
class JsonLeaf:
    """A string value in value position.

    ``byte_start``/``byte_end`` cover the entire JSON string token including
    its quotes, offset into the raw file bytes (BOM length included). ``path``
    is the JSON Pointer path of the value inside the document.
    """

    sequence: int
    path: str
    byte_start: int
    byte_end: int
    value: str


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str | None
    byte_start: int
    byte_end: int


class JSONParser:
    """Parser for the ``json`` format.

    Segments are one per string value in value position, in document order.
    ``source_text`` is the unescaped string value; ``stable_key`` is a hash of
    the structural path and the value, so keys stay stable across imports of
    the same bytes and never collide (a path plus its value is unique in a
    valid document).
    """

    format = "json"
    version = "1.0.0"

    def parse(
        self,
        file_path: Path,
        *,
        project_id: int,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Parse a JSON file into a SourceDocument and Segments.

        Args:
            file_path: Path to the JSON file.
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
            JSONParseError: If the file is not valid JSON or nests too deeply.
        """
        raw_bytes = file_path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()

        bom = detect_bom(raw_bytes)
        content_encoding, decode_encoding = resolve_encodings(encoding, bom)
        text = raw_bytes.decode(decode_encoding)
        newline = detect_newline(text)

        leaves = extract_string_leaves(
            text,
            content_encoding=content_encoding,
            bom_len=bom_length(bom),
        )

        segments = [self._to_segment(leaf) for leaf in leaves]
        locator_segments = [
            {
                "sequence": leaf.sequence,
                "path": leaf.path,
                "byte_start": leaf.byte_start,
                "byte_end": leaf.byte_end,
            }
            for leaf in leaves
        ]
        envelope = build_json_envelope(
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
    def _to_segment(leaf: JsonLeaf) -> Segment:
        return Segment.create(
            source_document_id=0,
            stable_key=_stable_key(leaf.path, leaf.value),
            source_text=leaf.value,
            sequence=leaf.sequence,
        )


def extract_string_leaves(
    text: str,
    *,
    content_encoding: str,
    bom_len: int = 0,
    max_depth: int = MAX_NESTING_DEPTH,
) -> list[JsonLeaf]:
    """Validate ``text`` as JSON and return its string-value leaves.

    The returned leaves are in document order and carry their structural path
    and byte span inside the raw file. Malformed input, duplicate object keys,
    and nesting beyond ``max_depth`` raise :class:`JSONParseError`.

    Args:
        text: The decoded file text (BOM already stripped by the codec).
        content_encoding: Plain codec used to compute byte offsets.
        bom_len: Byte length of the file's BOM, added to every offset.
        max_depth: Maximum container nesting depth.
    """
    tokens = _scan(text, content_encoding=content_encoding, bom_len=bom_len)
    return _build_leaves(tokens, max_depth=max_depth)


def _scan(text: str, *, content_encoding: str, bom_len: int) -> list[_Token]:
    """Tokenize JSON text into a validated token stream with byte offsets."""
    tokens: list[_Token] = []
    i = 0
    byte = bom_len
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _WHITESPACE:
            i, byte = _advance(text, i, byte, content_encoding)
            continue
        start = byte
        if ch == "{":
            i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("lbrace", None, start, byte))
        elif ch == "}":
            i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("rbrace", None, start, byte))
        elif ch == "[":
            i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("lbracket", None, start, byte))
        elif ch == "]":
            i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("rbracket", None, start, byte))
        elif ch == ":":
            i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("colon", None, start, byte))
        elif ch == ",":
            i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("comma", None, start, byte))
        elif ch == '"':
            value, i, byte = _scan_string(text, i, content_encoding, byte)
            tokens.append(_Token("string", value, start, byte))
        elif ch == "-" or ch.isdigit():
            start_char = i
            i, byte = _scan_number(text, i, byte, content_encoding)
            tokens.append(_Token("number", text[start_char:i], start, byte))
        elif text.startswith("true", i):
            for _ in range(4):
                i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("true", "true", start, byte))
        elif text.startswith("false", i):
            for _ in range(5):
                i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("false", "false", start, byte))
        elif text.startswith("null", i):
            for _ in range(4):
                i, byte = _advance(text, i, byte, content_encoding)
            tokens.append(_Token("null", "null", start, byte))
        else:
            raise JSONParseError(
                f"Unexpected character {ch!r} at position {i}.",
            )
    return tokens


def _scan_string(
    text: str,
    i: int,
    content_encoding: str,
    byte: int,
) -> tuple[str, int, int]:
    """Scan a JSON string literal; return (unescaped value, i, byte)."""
    n = len(text)
    i, byte = _advance(text, i, byte, content_encoding)  # opening quote
    parts: list[str] = []
    while i < n:
        ch = text[i]
        if ch == '"':
            i, byte = _advance(text, i, byte, content_encoding)
            return "".join(parts), i, byte
        if ch == "\\":
            i, byte = _advance(text, i, byte, content_encoding)
            if i >= n:
                raise JSONParseError("Unterminated string escape.")
            esc = text[i]
            i, byte = _advance(text, i, byte, content_encoding)
            if esc == "u":
                cp = _read_unicode_escape(text, i, byte, content_encoding)
                i, byte, value = cp
                parts.append(value)
            elif esc in _STRING_ESCAPES:
                parts.append(_STRING_ESCAPES[esc])
            else:
                raise JSONParseError(f"Invalid escape sequence \\{esc}.")
        else:
            if ch < " ":
                raise JSONParseError(
                    "Unescaped control character in string literal.",
                )
            i, byte = _advance(text, i, byte, content_encoding)
            parts.append(ch)
    raise JSONParseError("Unterminated string literal.")


def _read_unicode_escape(
    text: str,
    i: int,
    byte: int,
    content_encoding: str,
) -> tuple[int, int, str]:
    """Read a ``\\uXXXX`` escape; return (i, byte, value).

    A high surrogate is combined with a following low-surrogate ``\\uXXXX``
    escape into one code point. A lone surrogate (unpaired or invalid) is
    rejected: it is not a Unicode scalar value and would break downstream
    key hashing and prompt encoding.
    """
    hexs = text[i : i + 4]
    if len(hexs) < 4 or any(c not in _HEX_DIGITS for c in hexs):
        raise JSONParseError("Invalid \\u escape.")
    for _ in range(4):
        i, byte = _advance(text, i, byte, content_encoding)
    cp = int(hexs, 16)
    n = len(text)
    if (
        0xD800 <= cp <= 0xDBFF
        and i + 2 <= n
        and text[i] == "\\"
        and text[i + 1] == "u"
    ):
        hexs2 = text[i + 2 : i + 6]
        if len(hexs2) == 4 and all(c in _HEX_DIGITS for c in hexs2):
            cp2 = int(hexs2, 16)
            if 0xDC00 <= cp2 <= 0xDFFF:
                i, byte = _advance(text, i, byte, content_encoding)
                i, byte = _advance(text, i, byte, content_encoding)
                for _ in range(4):
                    i, byte = _advance(text, i, byte, content_encoding)
                cp = 0x10000 + ((cp - 0xD800) << 10) + (cp2 - 0xDC00)
    if 0xD800 <= cp <= 0xDFFF:
        raise JSONParseError("Unpaired surrogate in \\u escape.")
    return i, byte, chr(cp)


def _scan_number(text: str, i: int, byte: int, content_encoding: str) -> tuple[int, int]:
    """Scan a JSON number literal; return (i, byte) after the number."""
    n = len(text)
    start = i
    if text[i] == "-":
        i, byte = _advance(text, i, byte, content_encoding)
        if i >= n or not text[i].isdigit():
            raise JSONParseError(f"Invalid number at position {start}.")
    digits_start = i
    while i < n and text[i].isdigit():
        i, byte = _advance(text, i, byte, content_encoding)
    int_part = text[digits_start:i]
    if len(int_part) > 1 and int_part[0] == "0":
        raise JSONParseError(f"Invalid number (leading zero) at position {start}.")
    if i < n and text[i] == ".":
        i, byte = _advance(text, i, byte, content_encoding)
        frac_start = i
        while i < n and text[i].isdigit():
            i, byte = _advance(text, i, byte, content_encoding)
        if i == frac_start:
            raise JSONParseError(f"Invalid number at position {start}: missing fraction digits.")
    if i < n and text[i] in "eE":
        i, byte = _advance(text, i, byte, content_encoding)
        if i < n and text[i] in "+-":
            i, byte = _advance(text, i, byte, content_encoding)
        exp_start = i
        while i < n and text[i].isdigit():
            i, byte = _advance(text, i, byte, content_encoding)
        if i == exp_start:
            raise JSONParseError(f"Invalid number at position {start}: missing exponent digits.")
    return i, byte


def _advance(text: str, i: int, byte: int, content_encoding: str) -> tuple[int, int]:
    """Advance one character, adding its encoded byte length to ``byte``."""
    return i + 1, byte + _byte_len(text[i], content_encoding)


def _byte_len(ch: str, content_encoding: str) -> int:
    return len(ch.encode(content_encoding))


def _build_leaves(tokens: list[_Token], *, max_depth: int) -> list[JsonLeaf]:
    """Validate the token stream and assign structural paths to string values."""
    leaves: list[JsonLeaf] = []
    stack: list[dict[str, object]] = []
    expect = "value"
    i = 0
    n = len(tokens)

    def value_path() -> str:
        if not stack:
            return ""
        top = stack[-1]
        if top["kind"] == _ARR:
            return f"{top['path']}/{top['index']}"
        pending = top["pending"]
        if not isinstance(pending, str):
            raise JSONParseError("Internal structural error.")
        return f"{top['path']}/{_escape_pointer(pending)}"

    while i < n:
        tok = tokens[i]
        kind = tok.kind
        if expect == "value":
            if kind == "string":
                leaves.append(
                    JsonLeaf(
                        sequence=len(leaves) + 1,
                        path=value_path(),
                        byte_start=tok.byte_start,
                        byte_end=tok.byte_end,
                        value=tok.value or "",
                    ),
                )
                i += 1
                expect = "after_value"
            elif kind in ("number", "true", "false", "null"):
                i += 1
                expect = "after_value"
            elif kind == "lbrace":
                _push_container(stack, max_depth, _OBJ, value_path())
                i += 1
                expect = "name"
            elif kind == "lbracket":
                _push_container(stack, max_depth, _ARR, value_path())
                i += 1
                expect = "value"
            elif (
                kind == "rbracket"
                and stack
                and stack[-1]["kind"] == _ARR
                and not stack[-1]["has_member"]
            ):
                stack.pop()
                i += 1
                expect = "after_value"
            else:
                raise JSONParseError(f"Expected a JSON value at token {i}.")
        elif expect == "name":
            if kind == "string":
                top = stack[-1]
                name = tok.value or ""
                names = top["names"]
                assert isinstance(names, set)
                if name in names:
                    raise JSONParseError(f"Duplicate object key {name!r}.")
                names.add(name)
                top["pending"] = name
                top["has_member"] = True
                i += 1
                expect = "colon"
            elif (
                kind == "rbrace"
                and stack
                and stack[-1]["kind"] == _OBJ
                and not stack[-1]["has_member"]
            ):
                stack.pop()
                i += 1
                expect = "after_value"
            else:
                raise JSONParseError(f"Expected an object key at token {i}.")
        elif expect == "colon":
            if kind == "colon":
                i += 1
                expect = "value"
            else:
                raise JSONParseError(f"Expected a colon at token {i}.")
        elif expect == "comma_or_end":
            if kind == "comma":
                i += 1
                top = stack[-1]
                if top["kind"] == _OBJ:
                    top["pending"] = None
                    expect = "name"
                else:
                    expect = "value"
            elif kind == "rbrace" and stack and stack[-1]["kind"] == _OBJ:
                stack.pop()
                i += 1
                expect = "after_value"
            elif kind == "rbracket" and stack and stack[-1]["kind"] == _ARR:
                stack.pop()
                i += 1
                expect = "after_value"
            else:
                raise JSONParseError(
                    f"Expected a comma or closing bracket at token {i}.",
                )
        elif expect == "after_value":
            if not stack:
                raise JSONParseError("Trailing content after the root value.")
            top = stack[-1]
            if top["kind"] == _ARR:
                top["index"] = int(str(top["index"])) + 1
            expect = "comma_or_end"
        else:  # pragma: no cover - internal state machine is fully enumerated
            raise JSONParseError("Internal state error.")

    if stack:
        raise JSONParseError("Unterminated JSON structure.")
    if expect != "after_value":
        if expect == "value":
            raise JSONParseError("Empty JSON document.")
        raise JSONParseError("Incomplete JSON document.")
    return leaves


def _push_container(
    stack: list[dict[str, object]],
    max_depth: int,
    kind: str,
    path: str,
) -> None:
    if len(stack) >= max_depth:
        raise JSONParseError("JSON nesting exceeds the supported depth.")
    if kind == _OBJ:
        stack.append(
            {"kind": _OBJ, "path": path, "names": set(), "pending": None, "has_member": False},
        )
    else:
        stack.append({"kind": _ARR, "path": path, "index": 0, "has_member": False})


def _escape_pointer(key: str) -> str:
    """Escape an object key for use in a JSON Pointer path."""
    return key.replace("~", "~0").replace("/", "~1")


def _stable_key(path: str, value: str) -> str:
    """Return a stable key from the structural path and the value."""
    content = f"{path}\x00{value}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


PARSER_VERSION = JSONParser.version


def parse_json(
    file_path: Path,
    *,
    project_id: int,
    name: str | None = None,
    encoding: str = "utf-8",
) -> tuple[SourceDocument, list[Segment]]:
    """Convenience function that parses a JSON file using the default JSON parser."""
    return JSONParser().parse(
        file_path,
        project_id=project_id,
        name=name,
        encoding=encoding,
    )


__all__ = [
    "JSONParseError",
    "JSONParser",
    "JsonLeaf",
    "MAX_NESTING_DEPTH",
    "PARSER_VERSION",
    "extract_string_leaves",
    "parse_json",
]
