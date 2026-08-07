"""Tests for P1-T01-M01: fidelity carrier and TXT byte proof.

Covers the DEC-P1-T01-FOUNDATION plan-2 acceptance matrix for TXT: no-op
exports are byte-identical (UTF-8 plain/multi-byte, UTF-8 BOM, UTF-16 BOM,
CRLF, empty/whitespace-only files); translated exports replace only the target
spans; span/hash/encoding/BOM/newline/metadata-version mismatches and missing
carriers are rejected without polluting the database, revisions, or an existing
target file; and legacy (pre-008) TXT projects upgrade safely and can be
backfilled only by providing the verified original file.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from transrealm.application.exporter import ExportError, TxtExporter
from transrealm.application.import_service import ImportService
from transrealm.application.project_service import ProjectService
from transrealm.domain.segment import Segment
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.database import create_database, transaction
from transrealm.infrastructure.errors import SqlExecutionError
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.parsers.txt_parser import TxtParser, parse_txt
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)

APP_VERSION = "0.0.0-test"
MIGRATIONS_DIR = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"


def _create_project(path: Path) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name="M01",
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_bytes(
    path: Path,
    project_id: int,
    raw: bytes,
    *,
    encoding: str = "utf-8",
    name: str = "source.txt",
) -> tuple[int, list[Segment]]:
    source = path.parent / name
    source.write_bytes(raw)
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_txt(project_id, source, name=name, encoding=encoding)
    assert document.id is not None
    return document.id, segments


def _add_revision(path: Path, segment_id: int, text: str) -> int:
    repo = TranslationRevisionRepository.open(path)
    try:
        saved = repo.save(
            TranslationRevision.create(segment_id=segment_id, text=text, origin="ai"),
        )
    finally:
        repo.close()
    assert saved.id is not None
    return saved.id


def _set_current_revision(path: Path, segment_id: int, text: str) -> int:
    """Save a revision and make it the segment's current revision."""
    revision_id = _add_revision(path, segment_id, text)
    db = create_database(path)
    try:
        with transaction(db):
            db.execute(
                "UPDATE segments SET current_revision_id = ? WHERE id = ?",
                (revision_id, segment_id),
            )
    finally:
        db.close()
    return revision_id


def _export(
    path: Path,
    source_document_id: int,
    target_path: Path,
    **kwargs: Any,
) -> None:
    exporter = TxtExporter(path, app_version=APP_VERSION)
    try:
        exporter.export_document(
            source_document_id=source_document_id,
            target_path=target_path,
            **kwargs,
        )
    finally:
        exporter.close()


def _envelope(path: Path, document_id: int) -> dict[str, Any]:
    db = create_database(path)
    try:
        row = db.execute(
            "SELECT format_metadata FROM source_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    result = json.loads(row[0])
    assert isinstance(result, dict)
    return result


def _set_metadata(path: Path, document_id: int, envelope: dict[str, Any]) -> None:
    """Persist a given envelope (or raw JSON object) for a document."""
    db = create_database(path)
    try:
        with transaction(db):
            db.execute(
                "UPDATE source_documents SET format_metadata = ? WHERE id = ?",
                (json.dumps(envelope, ensure_ascii=False), document_id),
            )
    finally:
        db.close()


def _tamper(path: Path, document_id: int, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Persist a tampered copy of the envelope for a document."""
    envelope = _envelope(path, document_id)
    mutate(envelope)
    _set_metadata(path, document_id, envelope)


def _new_target(tmp_path: Path, name: str) -> Path:
    target = tmp_path / "out" / name
    target.parent.mkdir(exist_ok=True)
    return target


class TestNoOpByteIdentity:
    """Import -> no-op export is byte-for-byte identical."""

    def test_noop_plain_utf8_preserves_blanks_and_whitespace(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n\n   Beta line.  \nGamma line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf8_multibyte(self, tmp_path: Path) -> None:
        raw = "こんにちは世界。\n次行\n".encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf8_bom(self, tmp_path: Path) -> None:
        raw = b"\xef\xbb\xbf" + b"Alpha line.\nBeta line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw, encoding="utf-8")
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf16_bom(self, tmp_path: Path) -> None:
        raw = "Alpha line.\r\nBeta line.\r\n".encode("utf-16")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw, encoding="utf-16")
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_crlf(self, tmp_path: Path) -> None:
        raw = b"One\r\nTwo\r\n\r\nThree\r\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_empty_file(self, tmp_path: Path) -> None:
        raw = b""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_whitespace_only_file(self, tmp_path: Path) -> None:
        raw = b"   \n\t\n\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_parser_matches_legacy_splitlines_boundaries(self, tmp_path: Path) -> None:
        """Line boundaries stay identical to the legacy splitlines() parser."""
        path = tmp_path / "separators.txt"
        path.write_bytes("Alpha Beta\vGamma\n".encode())
        _, segments = parse_txt(path, project_id=1)
        assert [s.source_text for s in segments] == ["Alpha", "Beta", "Gamma"]
        assert [s.sequence for s in segments] == [1, 2, 3]

    def test_noop_splitlines_separators(self, tmp_path: Path) -> None:
        raw = "Alpha Beta\vGamma\n".encode()
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_utf16_be_bom(self, tmp_path: Path) -> None:
        raw = b"\xfe\xff" + "Alpha line.\r\nBeta line.\r\n".encode("utf-16-be")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw, encoding="utf-16")
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw

    def test_noop_cr_only_newline(self, tmp_path: Path) -> None:
        raw = b"One\rTwo\rThree\r"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        target = _new_target(tmp_path, "noop.txt")

        _export(path, document_id, target, apply_revisions=False)

        assert target.read_bytes() == raw


class TestTranslatedReplacesOnlyTargetSpan:
    """Revisions change only the target spans; everything else is preserved."""

    def test_single_segment_replacement_preserves_whitespace_and_blank_line(
        self,
        tmp_path: Path,
    ) -> None:
        raw = b"  Alpha line.  \n\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw)
        assert len(segments) == 1
        assert segments[0].id is not None
        _set_current_revision(path, segments[0].id, "甲")
        target = _new_target(tmp_path, "translated.txt")

        _export(path, document_id, target)

        expected = b"  " + "甲".encode() + b"  \n\n"
        assert target.read_bytes() == expected

    def test_multi_segment_replacement_preserves_structure(self, tmp_path: Path) -> None:
        raw = b"First.  \r\n\r\nSecond.\r\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw)
        assert segments[0].id is not None
        assert segments[1].id is not None
        _set_current_revision(path, segments[0].id, "一")
        _set_current_revision(path, segments[1].id, "二")
        target = _new_target(tmp_path, "translated.txt")

        _export(path, document_id, target)

        expected = "一".encode() + b"  \r\n\r\n" + "二".encode() + b"\r\n"
        assert target.read_bytes() == expected

    def test_utf16_translated_replaces_span_only(self, tmp_path: Path) -> None:
        raw = "Alpha line.\r\nBeta line.\r\n".encode("utf-16")
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw, encoding="utf-16")
        assert segments[0].id is not None
        assert segments[1].id is not None
        _set_current_revision(path, segments[0].id, "甲")
        _set_current_revision(path, segments[1].id, "乙")
        target = _new_target(tmp_path, "translated.txt")

        _export(path, document_id, target)

        assert target.read_bytes().decode("utf-16") == "甲\r\n乙\r\n"

    def test_utf8_bom_translated_replaces_span_only(self, tmp_path: Path) -> None:
        raw = b"\xef\xbb\xbf" + b"Alpha line.\nBeta line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw, encoding="utf-8")
        assert segments[0].id is not None
        assert segments[1].id is not None
        _set_current_revision(path, segments[0].id, "甲")
        _set_current_revision(path, segments[1].id, "乙")
        target = _new_target(tmp_path, "translated.txt")

        _export(path, document_id, target)

        assert target.read_bytes() == b"\xef\xbb\xbf" + "甲\n乙\n".encode()

    def test_revision_override_changes_only_that_span(self, tmp_path: Path) -> None:
        raw = b"A\nB\nC\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw)
        assert segments[0].id is not None
        assert segments[1].id is not None
        assert segments[2].id is not None
        _set_current_revision(path, segments[0].id, "一")
        _set_current_revision(path, segments[1].id, "二")
        _set_current_revision(path, segments[2].id, "三")
        historical = _add_revision(path, segments[0].id, "X")
        target = _new_target(tmp_path, "override.txt")

        _export(path, document_id, target, revision_overrides={segments[0].id: historical})

        assert target.read_bytes() == b"X\n\xe4\xba\x8c\n\xe4\xb8\x89\n"


class TestVerificationFailuresRejected:
    """Any carrier validation failure is refused without writing a file."""

    def test_span_out_of_bounds_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(byte_end=999999),
        )
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="out of bounds"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_span_overlap_rejected(self, tmp_path: Path) -> None:
        raw = b"A\nB\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw)
        assert segments[0].id is not None
        assert segments[1].id is not None
        _set_current_revision(path, segments[0].id, "一")
        _set_current_revision(path, segments[1].id, "二")
        envelope = _envelope(path, document_id)
        spans = envelope["locator"]["segments"]
        spans[1]["byte_start"] = spans[0]["byte_start"]
        _set_metadata(path, document_id, envelope)
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="overlaps"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_span_misalignment_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(byte_end=2),
        )
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="different source text"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_source_hash_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(source_hash="0" * 64))
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="source hash"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_bom_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(bom="utf-16-le"))
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="BOM"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_newline_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(newline="crlf"))
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="newline"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_metadata_version_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(schema_version=99))
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="schema version"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_wrong_format_envelope_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(path, document_id, lambda env: env.update(format="json"))
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="does not match"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_malformed_envelope_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET format_metadata = ? WHERE id = ?",
                    ("{not json", document_id),
                )
        finally:
            db.close()
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="not valid JSON"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_stored_raw_bytes_hash_mismatch_rejected(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        db = create_database(path)
        try:
            with transaction(db):
                db.execute(
                    "UPDATE source_documents SET raw_bytes = ? WHERE id = ?",
                    (b"tampered original bytes", document_id),
                )
        finally:
            db.close()
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="raw bytes hash"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_bom_declared_none_but_present_rejected(self, tmp_path: Path) -> None:
        raw = b"\xef\xbb\xbf" + b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw, encoding="utf-8")
        _tamper(path, document_id, lambda env: env.update(bom=None))
        target = _new_target(tmp_path, "out.txt")

        with pytest.raises(ExportError, match="BOM"):
            _export(path, document_id, target)
        assert not target.exists()


class TestFailuresDoNotPollute:
    """Encoding/write failures preserve the existing target and the data."""

    def test_encoding_failure_preserves_target_and_data(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw, encoding="ascii")
        assert segments[0].id is not None
        _set_current_revision(path, segments[0].id, "你好")
        target = _new_target(tmp_path, "translated.txt")
        target.write_bytes(b"OLD CONTENT")

        with pytest.raises(ExportError, match="encode"):
            _export(path, document_id, target)

        assert target.read_bytes() == b"OLD CONTENT"
        assert list(target.parent.iterdir()) == [target]

        db = create_database(path)
        try:
            revisions = db.execute("SELECT COUNT(*) FROM translation_revisions").fetchone()[0]
            documents = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
        finally:
            db.close()
        assert revisions == 1
        assert documents == 1

    def test_unwritable_target_preserves_existing_target(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_bytes(path, project_id, raw)
        assert segments[0].id is not None
        _set_current_revision(path, segments[0].id, "甲")
        # The parent is a file, so mkstemp cannot create a temp file there.
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("occupied", encoding="utf-8")
        target = blocker / "translated.txt"

        with pytest.raises(ExportError, match="temp file"):
            _export(path, document_id, target)
        assert not target.exists()

    def test_span_failure_never_writes_partial_file(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, _ = _import_bytes(path, project_id, raw)
        _tamper(
            path,
            document_id,
            lambda env: env["locator"]["segments"][0].update(byte_end=2),
        )
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        target = out_dir / "translated.txt"

        with pytest.raises(ExportError):
            _export(path, document_id, target)

        assert list(out_dir.iterdir()) == []


class TestLegacyUpgradeAndBackfill:
    """Pre-008 TXT projects upgrade, refuse export, then backfill safely."""

    def test_legacy_project_upgrades_then_backfills(self, tmp_path: Path) -> None:
        raw = "第一行\n\n第二行  \n第三行\n".encode()
        source_file = tmp_path / "source.txt"
        source_file.write_bytes(raw)

        # Reconstruct the segments a legacy parser would have produced: the
        # segment mapping (source_text/stable_key/sequence) is unchanged by the
        # fidelity rework, so the current parser yields identical segments.
        parsed_doc, parsed_segments = TxtParser().parse(source_file, project_id=1)

        db_path = tmp_path / "legacy.sqlite"
        runner = MigrationRunner.open(db_path)
        runner.apply(discover_migrations(MIGRATIONS_DIR)[:7], app_version="0.1.0")
        runner.close()

        db = create_database(db_path)
        with transaction(db):
            project_id = db.execute(
                "INSERT INTO projects (name, source_language, target_language) "
                "VALUES ('P1', 'zh', 'en')",
            ).lastrowid
            document_id = db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 'source.txt', 'txt', 'utf-8', ?, ?)",
                (project_id, parsed_doc.source_hash, parsed_doc.parser_version),
            ).lastrowid
            assert document_id is not None
            for segment in parsed_segments:
                db.execute(
                    "INSERT INTO segments "
                    "(source_document_id, stable_key, source_text, sequence, status) "
                    "VALUES (?, ?, ?, ?, 'pending')",
                    (
                        document_id,
                        segment.stable_key,
                        segment.source_text,
                        segment.sequence,
                    ),
                )
        db.close()

        # Upgrade to 008 with a pre-upgrade backup; the backup predates 008.
        runner = MigrationRunner.open(db_path)
        applied = runner.apply(
            discover_migrations(MIGRATIONS_DIR),
            app_version="0.1.0",
        )
        assert any(m.migration_id == "008_add_format_fidelity" for m in applied)
        assert runner.last_backup_path is not None
        assert runner.last_backup_path.exists()
        backup_db = create_database(runner.last_backup_path)
        try:
            columns = {
                row[1]
                for row in backup_db.execute("PRAGMA table_info('source_documents')")
            }
        finally:
            backup_db.close()
        assert "raw_bytes" not in columns
        runner.close()

        # The legacy document has no carrier; fidelity export is refused.
        target = _new_target(tmp_path, "legacy.txt")
        with pytest.raises(ExportError, match="no preserved original bytes"):
            _export(db_path, document_id, target, apply_revisions=False)
        assert not target.exists()

        # A wrong file is refused; the real original file backfills the carrier.
        wrong_file = tmp_path / "wrong.txt"
        wrong_file.write_bytes(b"different content\n")
        with ImportService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ValueError, match="hash"):
                service.backfill_fidelity(document_id, wrong_file)
            service.backfill_fidelity(document_id, source_file)

        _export(db_path, document_id, target, apply_revisions=False)
        assert target.read_bytes() == raw

    def test_backfill_rejects_mismatched_segment_mapping(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        source_file = tmp_path / "source.txt"
        source_file.write_bytes(raw)
        parsed_doc, parsed_segments = TxtParser().parse(source_file, project_id=1)

        db_path = tmp_path / "legacy.sqlite"
        runner = MigrationRunner.open(db_path)
        runner.apply(
            discover_migrations(MIGRATIONS_DIR),
            app_version="0.1.0",
        )
        runner.close()
        db = create_database(db_path)
        with transaction(db):
            project_id = db.execute(
                "INSERT INTO projects (name, source_language, target_language) "
                "VALUES ('P1', 'zh', 'en')",
            ).lastrowid
            document_id = db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 'source.txt', 'txt', 'utf-8', ?, ?)",
                (project_id, parsed_doc.source_hash, parsed_doc.parser_version),
            ).lastrowid
            assert document_id is not None
            # Insert a segment whose source_text differs from the parsed one.
            db.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence, status) "
                "VALUES (?, ?, 'DIFFERENT', 1, 'pending')",
                (document_id, parsed_segments[0].stable_key),
            )
        db.close()

        with ImportService(db_path, app_version=APP_VERSION) as service:
            with pytest.raises(ValueError, match="mapping"):
                service.backfill_fidelity(document_id, source_file)

    def test_legacy_splitlines_separator_document_backfills(self, tmp_path: Path) -> None:
        """A legacy file using splitlines() separators can be backfilled."""
        raw = "Alpha Beta\n".encode()
        source_file = tmp_path / "source.txt"
        source_file.write_bytes(raw)
        parsed_doc, parsed_segments = TxtParser().parse(source_file, project_id=1)
        assert [s.source_text for s in parsed_segments] == ["Alpha", "Beta"]

        db_path = tmp_path / "legacy.sqlite"
        runner = MigrationRunner.open(db_path)
        runner.apply(discover_migrations(MIGRATIONS_DIR)[:7], app_version="0.1.0")
        runner.close()
        db = create_database(db_path)
        with transaction(db):
            project_id = db.execute(
                "INSERT INTO projects (name, source_language, target_language) "
                "VALUES ('P1', 'zh', 'en')",
            ).lastrowid
            document_id = db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 'source.txt', 'txt', 'utf-8', ?, ?)",
                (project_id, parsed_doc.source_hash, parsed_doc.parser_version),
            ).lastrowid
            assert document_id is not None
            for segment in parsed_segments:
                db.execute(
                    "INSERT INTO segments "
                    "(source_document_id, stable_key, source_text, sequence, status) "
                    "VALUES (?, ?, ?, ?, 'pending')",
                    (
                        document_id,
                        segment.stable_key,
                        segment.source_text,
                        segment.sequence,
                    ),
                )
        db.close()

        with ImportService(db_path, app_version=APP_VERSION) as service:
            service.backfill_fidelity(document_id, source_file)

        target = _new_target(tmp_path, "legacy.txt")
        _export(db_path, document_id, target, apply_revisions=False)
        assert target.read_bytes() == raw


class TestIdentityDomain:
    """008 isolates format and parser identity in the logical reuse domain."""

    def test_same_bytes_different_format_or_parser_version_are_separate(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "identity.sqlite"
        runner = MigrationRunner.open(db_path)
        runner.apply(
            discover_migrations(MIGRATIONS_DIR),
            app_version="0.1.0",
        )
        runner.close()
        db = create_database(db_path)
        try:
            with transaction(db):
                project_id = db.execute(
                    "INSERT INTO projects (name, source_language, target_language) "
                    "VALUES ('P1', 'zh', 'en')",
                ).lastrowid
                db.execute(
                    "INSERT INTO source_documents "
                    "(project_id, name, format, encoding, source_hash, parser_version) "
                    "VALUES (?, 'a.txt', 'txt', 'utf-8', 'hash', '1.0.0')",
                    (project_id,),
                )
                # Same bytes in a different format is a different document.
                db.execute(
                    "INSERT INTO source_documents "
                    "(project_id, name, format, encoding, source_hash, parser_version) "
                    "VALUES (?, 'a.json', 'json', 'utf-8', 'hash', '1.0.0')",
                    (project_id,),
                )
                # Same bytes/format under a different parser version is separate.
                db.execute(
                    "INSERT INTO source_documents "
                    "(project_id, name, format, encoding, source_hash, parser_version) "
                    "VALUES (?, 'a-v2.txt', 'txt', 'utf-8', 'hash', '2.0.0')",
                    (project_id,),
                )
            # The exact same identity is rejected by the unique index.
            with pytest.raises(SqlExecutionError):
                with transaction(db):
                    db.execute(
                        "INSERT INTO source_documents "
                        "(project_id, name, format, encoding, source_hash, parser_version) "
                        "VALUES (?, 'dupe.txt', 'txt', 'utf-8', 'hash', '1.0.0')",
                        (project_id,),
                    )
            count = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
        finally:
            db.close()
        assert count == 3

    def test_import_remains_idempotent_for_same_identity(self, tmp_path: Path) -> None:
        raw = b"Alpha line.\n"
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document1, segments1 = _import_bytes(path, project_id, raw)
        document2, segments2 = _import_bytes(path, project_id, raw)

        assert document1 == document2
        assert [s.id for s in segments1] == [s.id for s in segments2]
        db = create_database(path)
        try:
            count = db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0]
        finally:
            db.close()
        assert count == 1
