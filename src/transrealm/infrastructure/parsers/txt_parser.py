"""TXT parser producing stable Segments."""

import hashlib
from pathlib import Path

from transrealm.domain.segment import Segment, SourceDocument


class TxtParser:
    """Line-based TXT parser."""

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

        The file is split into one Segment per non-empty line. Empty lines are
        ignored. The sequence number reflects the position among non-empty lines.

        Args:
            file_path: Path to the TXT file.
            project_id: Project that owns the source document.
            name: Optional display name for the source document. Defaults to the
                file name.
            encoding: Text encoding to use when reading the file.

        Returns:
            A tuple of (SourceDocument, list of Segments).

        Raises:
            FileNotFoundError: If the file does not exist.
            UnicodeDecodeError: If the file cannot be decoded with the given encoding.
        """
        text = file_path.read_text(encoding=encoding)
        raw_bytes = file_path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()

        document = SourceDocument.create(
            project_id=project_id,
            name=name or file_path.name,
            format=self.format,
            encoding=encoding,
            source_hash=source_hash,
            parser_version=self.version,
        )

        segments: list[Segment] = []
        sequence = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            sequence += 1
            segments.append(
                Segment.create(
                    source_document_id=0,
                    stable_key=_stable_key(stripped, sequence),
                    source_text=stripped,
                    sequence=sequence,
                ),
            )

        return document, segments


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
