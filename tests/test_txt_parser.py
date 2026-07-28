"""Tests for TXT parser and Segment import."""

from pathlib import Path

import pytest

from transrealm.application.import_service import ImportService
from transrealm.application.project_service import ProjectService
from transrealm.infrastructure.parsers.txt_parser import PARSER_VERSION, parse_txt
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "project.db"


@pytest.fixture
def txt_file(tmp_path: Path) -> Path:
    """Return a temporary TXT file with three lines."""
    path = tmp_path / "source.txt"
    path.write_text("第一行\n第二行\n第三行\n", encoding="utf-8")
    return path


def test_parse_txt_splits_lines(tmp_path: Path) -> None:
    """TXT parser splits non-empty lines into segments."""
    path = tmp_path / "lines.txt"
    path.write_text("Hello\n\nWorld\n", encoding="utf-8")

    document, segments = parse_txt(path, project_id=1)
    assert document.name == "lines.txt"
    assert document.format == "txt"
    assert document.encoding == "utf-8"
    assert document.parser_version == PARSER_VERSION
    assert len(segments) == 2
    assert segments[0].source_text == "Hello"
    assert segments[0].sequence == 1
    assert segments[1].source_text == "World"
    assert segments[1].sequence == 2


def test_parse_txt_empty_file(tmp_path: Path) -> None:
    """An empty TXT file yields no segments."""
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    document, segments = parse_txt(path, project_id=1)
    assert segments == []


def test_parse_txt_stable_keys_are_deterministic(tmp_path: Path) -> None:
    """Parsing the same file twice produces identical stable keys."""
    path = tmp_path / "stable.txt"
    path.write_text("Same content\n", encoding="utf-8")
    _, segments1 = parse_txt(path, project_id=1)
    _, segments2 = parse_txt(path, project_id=1)
    assert segments1[0].stable_key == segments2[0].stable_key


def test_parse_txt_raises_for_missing_file(tmp_path: Path) -> None:
    """Parsing a missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        parse_txt(tmp_path / "missing.txt", project_id=1)


def test_import_service_saves_segments(db_path: Path, txt_file: Path) -> None:
    """ImportService persists source document and segments."""
    project_service = ProjectService(db_path, app_version="0.1.0")
    project = project_service.create_project(name="P1", source_language="zh", target_language="en")
    assert project.id is not None
    project_service.close()

    import_service = ImportService(db_path, app_version="0.1.0")
    document, segments = import_service.import_txt(project.id, txt_file)
    import_service.close()

    assert document.id is not None
    assert len(segments) == 3
    assert segments[0].source_document_id == document.id
    assert segments[0].status == "pending"


def test_import_service_is_idempotent_by_hash(db_path: Path, txt_file: Path) -> None:
    """Importing the same file twice returns existing segments."""
    project_service = ProjectService(db_path, app_version="0.1.0")
    project = project_service.create_project(name="P1", source_language="zh", target_language="en")
    assert project.id is not None
    project_service.close()

    with ImportService(db_path, app_version="0.1.0") as import_service:
        document1, segments1 = import_service.import_txt(project.id, txt_file)

    with ImportService(db_path, app_version="0.1.0") as import_service:
        document2, segments2 = import_service.import_txt(project.id, txt_file)

    assert document1.id == document2.id
    assert len(segments1) == len(segments2)


def test_segment_repository_lists_segments(db_path: Path, txt_file: Path) -> None:
    """SegmentRepository can read back saved segments."""
    project_service = ProjectService(db_path, app_version="0.1.0")
    project = project_service.create_project(name="P1", source_language="zh", target_language="en")
    assert project.id is not None
    project_service.close()

    with ImportService(db_path, app_version="0.1.0") as import_service:
        document, _ = import_service.import_txt(project.id, txt_file)

    assert document.id is not None

    from transrealm.infrastructure.database import create_database

    db = create_database(db_path)
    repo = SegmentRepository(db)
    loaded = repo.list_segments_by_document(document.id)
    assert len(loaded) == 3
    assert loaded[0].source_text == "第一行"
    repo.close()


def test_import_service_rejects_bad_encoding(tmp_path: Path, db_path: Path) -> None:
    """Importing a file with the wrong encoding raises UnicodeDecodeError."""
    path = tmp_path / "binary.txt"
    path.write_bytes(b"\xff\xfe")

    project_service = ProjectService(db_path, app_version="0.1.0")
    project = project_service.create_project(name="P1", source_language="zh", target_language="en")
    assert project.id is not None
    project_service.close()

    with ImportService(db_path, app_version="0.1.0") as import_service:
        with pytest.raises(UnicodeDecodeError):
            import_service.import_txt(project.id, path, encoding="utf-8")
