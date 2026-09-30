"""Versioned TXT mapping, identity and byte-fidelity acceptance tests."""

import json
from pathlib import Path

import pytest

from transrealm.application.exporter import TxtExporter
from transrealm.application.import_service import ImportService
from transrealm.application.project_service import ProjectService
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.parsers.parser import ParserRegistry
from transrealm.infrastructure.parsers.txt_parser import LegacyTxtParser, TxtParser
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)


def _project(db_path: Path) -> int:
    with ProjectService(db_path, app_version="0.2.0") as service:
        project = service.create_project(name="TXT", source_language="zh", target_language="en")
        assert project.id is not None
        return project.id


def test_v2_golden_boundaries_and_determinism(tmp_path: Path) -> None:
    prose = "这是一个长度足够的自然段落，第一行没有句末标点，需要与下一行按原样合并成连续区间。"
    raw = (
        f"{prose[:-1]}\r\n{prose[:-1]}\r\n\r\n"
        "— 你好。\r\nHello world. Next sentence! 再见？\r\n"
    ).encode()
    path = tmp_path / "novel.txt"
    path.write_bytes(raw)
    first, segments = TxtParser().parse(path, project_id=1)
    second, repeated = TxtParser().parse(path, project_id=1)
    assert first.parser_version == second.parser_version == "2.0.0"
    assert [(s.source_text, s.stable_key) for s in segments] == [
        (s.source_text, s.stable_key) for s in repeated
    ]
    assert any("\r\n" in s.source_text for s in segments)
    assert any(s.source_text.startswith("— 你好") for s in segments)
    assert any(s.source_text == "Hello world." for s in segments)
    assert any(s.source_text == "Next sentence!" for s in segments)
    assert any(s.source_text == "再见？" for s in segments)
    envelope = json.loads(first.format_metadata or "{}")
    spans = envelope["locator"]["segments"]
    assert envelope["segmentation"]["max_chars"] == 180
    assert all(len(s.source_text) <= 180 for s in segments)
    assert all(a["byte_end"] <= b["byte_start"] for a, b in zip(spans, spans[1:]))
    assert all(raw[p["byte_start"] : p["byte_end"]].decode() == s.source_text
               for p, s in zip(spans, segments))


@pytest.mark.parametrize(
    ("encoding", "raw"),
    [
        ("utf-8", "  长句。 Next!\n\n— 对话。\n".encode()),
        ("utf-8", b"\xef\xbb\xbf" + "  长句。 Next!\r\n\r\n— 对话。\r\n".encode()),
        ("utf-16", "  长句。 Next!\r\n\r\n— 对话。\r\n".encode("utf-16")),
        ("utf-8", "A\u2028B\vC\n".encode()),
    ],
)
def test_all_targets_replace_only_their_spans(
    tmp_path: Path, encoding: str, raw: bytes
) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _project(db_path)
    source = tmp_path / "source.txt"
    source.write_bytes(raw)
    with ImportService(db_path, app_version="0.2.0") as service:
        document, segments = service.import_txt(project_id, source, encoding=encoding)
    assert document.id is not None
    assert segments
    envelope = json.loads(document.format_metadata or "{}")
    spans = envelope["locator"]["segments"]
    codec = envelope["encoding"]
    repo = TranslationRevisionRepository.open(db_path)
    db = create_database(db_path)
    try:
        for segment in segments:
            assert segment.id is not None
            revision = repo.save(
                TranslationRevision.create(segment_id=segment.id, text="译", origin="ai")
            )
            with transaction(db):
                db.execute(
                    "UPDATE segments SET current_revision_id = ? WHERE id = ?",
                    (revision.id, segment.id),
                )
    finally:
        repo.close()
        db.close()
    target = tmp_path / "output.txt"
    with TxtExporter(db_path, app_version="0.2.0") as exporter:
        exporter.export_document(source_document_id=document.id, target_path=target)
    expected = raw
    for span in reversed(spans):
        expected = (
            expected[: span["byte_start"]]
            + "译".encode(codec)
            + expected[span["byte_end"] :]
        )
    assert target.read_bytes() == expected


def test_legacy_identity_and_revision_survive_v2_import(tmp_path: Path) -> None:
    db_path = tmp_path / "project.sqlite"
    project_id = _project(db_path)
    source = tmp_path / "source.txt"
    source.write_text(
        "A long soft wrapped prose line without a sentence ending\n"
        "Another long continuation also without a sentence ending\n",
        encoding="utf-8",
    )
    registry = ParserRegistry()
    registry.register(LegacyTxtParser())
    with ImportService(db_path, app_version="0.2.0", parser_registry=registry) as service:
        old, old_segments = service.import_txt(project_id, source)
    assert old.id is not None and len(old_segments) == 2
    assert old_segments[0].id is not None
    repo = TranslationRevisionRepository.open(db_path)
    try:
        revision = repo.save(TranslationRevision.create(
            segment_id=old_segments[0].id, text="legacy", origin="ai"
        ))
        assert old_segments[1].id is not None
        second_revision = repo.save(TranslationRevision.create(
            segment_id=old_segments[1].id, text="legacy two", origin="ai"
        ))
    finally:
        repo.close()
    db = create_database(db_path)
    try:
        with transaction(db):
            db.execute("UPDATE segments SET current_revision_id = ? WHERE id = ?",
                       (revision.id, old_segments[0].id))
            db.execute("UPDATE segments SET current_revision_id = ? WHERE id = ?",
                       (second_revision.id, old_segments[1].id))
    finally:
        db.close()
    with ImportService(db_path, app_version="0.2.0") as service:
        new, new_segments = service.import_txt(project_id, source)
    assert new.id != old.id and new.parser_version == "2.0.0"
    assert old.parser_version == "1.0.0" and len(new_segments) == 1
    target = tmp_path / "old.txt"
    with TxtExporter(db_path, app_version="0.2.0") as exporter:
        exporter.export_document(source_document_id=old.id, target_path=target)
        assert target.read_text(encoding="utf-8") == "legacy\nlegacy two\n"
        exporter.export_document(source_document_id=old.id, target_path=target,
                                 apply_revisions=False)
    assert target.read_bytes() == source.read_bytes()
    repo = TranslationRevisionRepository.open(db_path)
    try:
        assert revision.id is not None
        loaded = repo.get_by_id(revision.id)
        assert loaded is not None and loaded.text == "legacy"
    finally:
        repo.close()
