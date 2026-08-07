"""Parser protocol and registry."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from transrealm.domain.segment import Segment, SourceDocument


@runtime_checkable
class Parser(Protocol):
    """Protocol for file parsers that produce SourceDocument and Segments."""

    format: str
    version: str

    def parse(
        self,
        file_path: Path,
        *,
        project_id: int,
        name: str | None = None,
        encoding: str = "utf-8",
    ) -> tuple[SourceDocument, list[Segment]]:
        """Parse a file and return a SourceDocument with its Segments."""
        ...


class ParserRegistry:
    """Registry of parsers by format."""

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}

    def register(self, parser: Parser) -> None:
        """Register a parser for its declared format."""
        self._parsers[parser.format] = parser

    def get(self, format: str) -> Parser:  # noqa: A002
        """Return the parser for the given format.

        Raises:
            ValueError: If no parser is registered for the format.
        """
        parser = self._parsers.get(format)
        if parser is None:
            raise ValueError(f"No parser registered for format: {format}")
        return parser

    def supported_formats(self) -> list[str]:
        """Return the list of registered formats."""
        return sorted(self._parsers.keys())


def default_registry() -> ParserRegistry:
    """Return a registry with the built-in format parsers registered."""
    from transrealm.infrastructure.parsers.ass_ssa_parser import AssParser, SsaParser
    from transrealm.infrastructure.parsers.json_parser import JSONParser
    from transrealm.infrastructure.parsers.srt_parser import SRTParser
    from transrealm.infrastructure.parsers.txt_parser import TxtParser
    from transrealm.infrastructure.parsers.vtt_parser import VTTParser

    registry = ParserRegistry()
    registry.register(TxtParser())
    registry.register(JSONParser())
    registry.register(SRTParser())
    registry.register(VTTParser())
    registry.register(AssParser())
    registry.register(SsaParser())
    return registry


__all__ = ["Parser", "ParserRegistry", "default_registry"]
