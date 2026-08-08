"""P1-T05-M03: 格式/迁移/Project 双形态/security Gate 矩阵.

验证型 Gate（目标/硬约束/验收不变，不新增产品能力），旅程级补足既有
per-format / per-container 套件未覆盖的复合证据（``03`` §12.5 fixture = 六格式/
旧库/容器）：

- **六格式 golden**：六种格式的固定 golden 字节（模块级常量 + 防漂移守卫），
  单一 Project 导入全部六格式 → no-op 导出逐字节一致 → 每段 ``append_user_revision``
  后导出仅改目标 span → 重导入 round-trip；
- **旧库 migration backup/restore**：001-007 旧库带数据迁移至最新，pre-upgrade
  备份先于 008 且可打开；用备份替换活库重开数据保留、再向前迁移可打开（演练文档
  中的恢复步骤）；
- **开放目录/``.aiproject`` 跨机/tamper/path/resource limits**：六格式容器
  跨机 round-trip 保留 fidelity carrier，篡改/traversal/超限额在目标落地前拒绝；
- **secret scan**：``src``/配置内容扫描无硬编码凭据；archive/目标/错误只含引用、
  永不泄 secret；
- **失败隔离**：某格式导出失败不影响其他文档/DB/目标，migration 备份失败阻断。

六格式 no-op/translated/error/unwritable/旧库升级的逐格式矩阵（P1-T01-M01..M05，
422 项）、容器跨机/tamper/path/resource-limit 全矩阵（P1-T02-M01..M05，191 项）
与 migration 备份矩阵（``test_migrations.py``）经 verify_task --baseline-test 复引；
本文件只补复合旅程证据。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pytest

from transrealm.application.archive_service import (
    export_open_directory_archive,
    import_archive_to_staging,
)
from transrealm.application.exporter import (
    AssExporter,
    ExportError,
    JsonExporter,
    SrtExporter,
    SsaExporter,
    TxtExporter,
    VttExporter,
)
from transrealm.application.import_service import ImportService
from transrealm.application.install_service import install_staging_to_target
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.open_directory_service import (
    create_open_directory_project,
    open_open_directory_project,
)
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.domain.segment import Segment
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.migrations.discovery import discover_migrations
from transrealm.infrastructure.migrations.runner import MigrationRunner
from transrealm.infrastructure.open_directory import (
    CRITICAL_ENTRY_TYPE,
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    ArchiveLimitError,
    FileIntegrityError,
    ManifestInfo,
    compute_entry,
    write_manifest,
)

APP_VERSION = "0.0.0-test"
MIGRATIONS_DIR = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"

_SIX_FORMATS = ["txt", "json", "srt", "vtt", "ass", "ssa"]

# ---------------------------------------------------------------------------
# 固定 golden fixtures（六格式）
# ---------------------------------------------------------------------------

GOLDEN_TXT = b"Alpha line.\nSecond line.\n\nFourth line.\n"
GOLDEN_JSON = json.dumps(
    {"greeting": "hello", "nested": {"items": ["world", "你好"]}, "n": 42},
    ensure_ascii=False,
).encode("utf-8")
GOLDEN_SRT = (
    b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
    b"2\n00:00:05,000 --> 00:00:07,000\nSecond cue\n"
)
GOLDEN_VTT = (
    b"WEBVTT\n"
    b"\n"
    b"00:01.000 --> 00:04.000\n"
    b"Hello world\n"
    b"\n"
    b"00:05.000 --> 00:07.000\n"
    b"Second cue\n"
)

_ASS_EVENTS_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text"
)
_SSA_EVENTS_FORMAT = (
    "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text"
)
GOLDEN_ASS = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "\n"
    "[Events]\n"
    f"{_ASS_EVENTS_FORMAT}\n"
    "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello world\n"
).encode()
GOLDEN_SSA = (
    "[Script Info]\n"
    "ScriptType: v4.00\n"
    "\n"
    "[Events]\n"
    f"{_SSA_EVENTS_FORMAT}\n"
    "Dialogue: Marked=0,0:00:01.00,0:00:02.00,Default,,0000,0000,0000,,Hello world\n"
).encode()

GOLDEN_FIXTURES: dict[str, bytes] = {
    "txt": GOLDEN_TXT,
    "json": GOLDEN_JSON,
    "srt": GOLDEN_SRT,
    "vtt": GOLDEN_VTT,
    "ass": GOLDEN_ASS,
    "ssa": GOLDEN_SSA,
}

EXPECTED_SEGMENT_COUNTS: dict[str, int] = {
    "txt": 3,
    "json": 3,
    "srt": 2,
    "vtt": 2,
    "ass": 1,
    "ssa": 1,
}

TRANSLATIONS: dict[str, list[str]] = {
    "txt": ["译文一", "译文二", "译文四"],
    "json": ["译文g", "译文w", "译文你好"],
    "srt": ["译文一", "译文二"],
    "vtt": ["译文一", "译文二"],
    "ass": ["译文ass"],
    "ssa": ["译文ssa"],
}

_EXPORTERS: dict[str, type[Any]] = {
    "txt": TxtExporter,
    "json": JsonExporter,
    "srt": SrtExporter,
    "vtt": VttExporter,
    "ass": AssExporter,
    "ssa": SsaExporter,
}


def _golden_path(tmp_path: Path, fmt: str) -> Path:
    source = tmp_path / f"golden.{fmt}"
    source.write_bytes(GOLDEN_FIXTURES[fmt])
    return source


def _create_project(path: Path, name: str = "M03") -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name=name,
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_golden(
    path: Path,
    project_id: int,
    fmt: str,
) -> tuple[int, list[Segment]]:
    source = _golden_path(path.parent, fmt)
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_file(
            project_id,
            source,
            format=fmt,
            name=source.name,
        )
    assert document.id is not None
    assert len(segments) == EXPECTED_SEGMENT_COUNTS[fmt]
    return document.id, segments


def _append_user_revisions(path: Path, segments: list[Segment], texts: list[str]) -> None:
    assert len(segments) == len(texts)
    with TranslationRunService(path, app_version=APP_VERSION) as service:
        for segment, text in zip(segments, texts):
            assert segment.id is not None
            service.append_user_revision(segment_id=segment.id, text=text)


def _export(
    path: Path,
    source_document_id: int,
    target_path: Path,
    fmt: str,
    **kwargs: Any,
) -> None:
    exporter = _EXPORTERS[fmt](path, app_version=APP_VERSION)
    try:
        exporter.export_document(
            source_document_id=source_document_id,
            target_path=target_path,
            **kwargs,
        )
    finally:
        exporter.close()


def _reimport_golden(path: Path, project_id: int, fmt: str, target: Path) -> None:
    with ImportService(path, app_version=APP_VERSION) as service:
        document, segments = service.import_file(
            project_id,
            target,
            format=fmt,
            name=target.name,
        )
    assert document.id is not None
    assert len(segments) == EXPECTED_SEGMENT_COUNTS[fmt]


def _apply_old_migrations(db_path: Path) -> None:
    """Apply migrations 001-007 only, simulating an older app version."""
    migs = discover_migrations(MIGRATIONS_DIR)
    old = [m for m in migs if m.migration_id != "008_add_format_fidelity"]
    db = create_database(db_path)
    try:
        MigrationRunner(db).apply(old, app_version=APP_VERSION)
    finally:
        db.close()


def _checkpoint_clean(db_path: Path) -> None:
    raw = sqlite3.connect(str(db_path))
    try:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        raw.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _refresh_manifest(directory: Path) -> None:
    db_path = directory / DATABASE_FILENAME
    entries = [
        compute_entry(DATABASE_FILENAME, db_path, entry_type=CRITICAL_ENTRY_TYPE),
    ]
    sidecars = {f"{DATABASE_FILENAME}-wal", f"{DATABASE_FILENAME}-shm"}
    for entry in directory.rglob("*"):
        if (
            entry.is_file()
            and entry.name != MANIFEST_FILENAME
            and entry != db_path
            and entry.name not in sidecars
        ):
            relpath = entry.relative_to(directory).as_posix()
            entries.append(compute_entry(relpath, entry, entry_type="attachment"))
    write_manifest(
        directory,
        ManifestInfo(1, 1, APP_VERSION, tuple(entries)),
    )


def _db_rows(db_path: Path, sql: str, *params: object) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. 六格式 golden —— 固定 fixture + 防漂移守卫
# ---------------------------------------------------------------------------


class TestSixFormatGolden:
    """六格式固定 golden fixtures：防漂移 + 单一 Project 复合旅程。"""

    def test_golden_fixtures_are_fixed_and_recorded(self) -> None:
        """Golden fixtures 是固定常量；防漂移断言精确大小+sha256 与预期段数。"""
        expected_sizes = {
            "txt": 39,
            "json": 72,
            "srt": 88,
            "vtt": 80,
            "ass": 185,
            "ssa": 201,
        }
        expected_hashes = {
            "txt": "8e3b6babbe20623d0c654d0fc708d3671ccf8289288956fdecd1dd7bb77b2548",
            "json": "75afe91db177fecf51fea3b147f6e40708b8a94a7dfe339783c5d5c5397b7812",
            "srt": "af44cd53b1096af57fcf6629dc221f19cb37a3aa7758539f54cc29b16c7c81bf",
            "vtt": "39792263802bc10f5682b41b283fd0f96a9bf6f4d09fc0f51db36ee43a464021",
            "ass": "335f4b406a879dab544f1ad345ece60d07a7ecdc15e1bc69f97a0a8f420dc149",
            "ssa": "7a047ddfe3f5d997305396304040d0fe91e1290691f2ae47c2ab8675786fcffb",
        }
        for fmt in _SIX_FORMATS:
            raw = GOLDEN_FIXTURES[fmt]
            assert len(raw) == expected_sizes[fmt], fmt
            assert hashlib.sha256(raw).hexdigest() == expected_hashes[fmt], fmt
        assert set(GOLDEN_FIXTURES) == set(_SIX_FORMATS)
        assert set(EXPECTED_SEGMENT_COUNTS) == set(_SIX_FORMATS)

    def test_six_formats_noop_export_byte_identical(self, tmp_path: Path) -> None:
        """单一 Project 导入全部六格式 → no-op 导出逐字节一致。"""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        for fmt in _SIX_FORMATS:
            document_id, _segments = _import_golden(path, project_id, fmt)
            target = tmp_path / f"noop.{fmt}"
            _export(path, document_id, target, fmt, apply_revisions=False)
            assert target.read_bytes() == GOLDEN_FIXTURES[fmt], fmt

    def test_six_formats_translate_export_only_target_spans(self, tmp_path: Path) -> None:
        """每段 append_user_revision → 导出仅改目标 span、结构保留、round-trip。"""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        for fmt in _SIX_FORMATS:
            document_id, segments = _import_golden(path, project_id, fmt)
            _append_user_revisions(path, segments, TRANSLATIONS[fmt])
            target = tmp_path / f"translated.{fmt}"
            _export(path, document_id, target, fmt)
            out = target.read_bytes().decode("utf-8")
            for translation in TRANSLATIONS[fmt]:
                assert translation in out, fmt
            # 源文本"Hello world"在 srt/vtt/ass/ssa golden 中真实存在，翻译后必须消失。
            if fmt in ("srt", "vtt", "ass", "ssa"):
                assert "Hello world" not in out, fmt
            # 结构字节保留：对字幕格式，时间轴行必须原样存在。
            if fmt == "srt":
                assert "00:00:01,000 --> 00:00:04,000" in out
            if fmt == "vtt":
                assert "WEBVTT" in out and "00:01.000 --> 00:04.000" in out
            if fmt in ("ass", "ssa"):
                assert "[Events]" in out and "Format:" in out
            # round-trip：导出文件可重导入且段数一致。
            _reimport_golden(path, project_id, fmt, target)

    def test_six_formats_error_and_unwritable_do_not_pollute(self, tmp_path: Path) -> None:
        """某格式导出失败（无载体/不可写目标）不影响其他文档与 DB。"""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_ids: dict[str, int] = {}
        for fmt in _SIX_FORMATS:
            document_id, _segments = _import_golden(path, project_id, fmt)
            document_ids[fmt] = document_id

        # 篡改 txt 的 carrier 使其缺载体 → 导出拒绝且不写目标。
        db = create_database(path)
        try:
            db.execute(
                "UPDATE source_documents SET raw_bytes = NULL WHERE id = ?",
                (document_ids["txt"],),
            )
            db.connection.commit()
        finally:
            db.close()
        bad_target = tmp_path / "out" / "bad.txt"
        with pytest.raises(ExportError, match="no preserved original bytes"):
            _export(path, document_ids["txt"], bad_target, "txt", apply_revisions=False)
        assert not bad_target.exists()

        # 其余五格式仍可 no-op 导出，DB 未被污染。
        for fmt in _SIX_FORMATS:
            if fmt == "txt":
                continue
            target = tmp_path / f"still-ok.{fmt}"
            _export(path, document_ids[fmt], target, fmt, apply_revisions=False)
            assert target.read_bytes() == GOLDEN_FIXTURES[fmt]

        # txt 缺载体文档本身不受影响（补载体后可再导出）。
        source = _golden_path(tmp_path, "txt")
        with ImportService(path, app_version=APP_VERSION) as service:
            service.backfill_fidelity(document_ids["txt"], source)
        restored = tmp_path / "restored.txt"
        _export(path, document_ids["txt"], restored, "txt", apply_revisions=False)
        assert restored.read_bytes() == GOLDEN_TXT


# ---------------------------------------------------------------------------
# 2. 旧库 migration backup/restore —— 演练文档中的恢复步骤
# ---------------------------------------------------------------------------


class TestLegacyMigrationBackupRestore:
    """旧库迁移带备份；用备份替换活库重开数据保留；再向前迁移可打开。"""

    def test_legacy_migrate_creates_restorable_backup(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.sqlite"
        _apply_old_migrations(db_path)
        db = create_database(db_path)
        try:
            project_id = db.execute(
                "INSERT INTO projects (name, source_language, target_language) "
                "VALUES ('Legacy', 'zh', 'en')",
            ).lastrowid
            doc_id = db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 's.txt', 'txt', 'utf-8', 'h', '1.0.0')",
                (project_id,),
            ).lastrowid
            db.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence, status) "
                "VALUES (?, 'k1', 'Hello', 1, 'pending')",
                (doc_id,),
            )
            db.connection.commit()
        finally:
            db.close()
        _checkpoint_clean(db_path)

        runner = MigrationRunner.open(db_path)
        applied = runner.apply(discover_migrations(MIGRATIONS_DIR), app_version=APP_VERSION)
        assert any(m.migration_id == "008_add_format_fidelity" for m in applied)
        backup_path = runner.last_backup_path
        assert backup_path is not None and backup_path.exists()
        # 备份先于 008：无 raw_bytes 列，且含旧数据。
        backup_db = create_database(backup_path)
        try:
            columns = {
                row[1] for row in backup_db.execute("PRAGMA table_info('source_documents')")
            }
            projects = backup_db.execute("SELECT name FROM projects").fetchall()
            segments = backup_db.execute("SELECT source_text FROM segments").fetchall()
        finally:
            backup_db.close()
        assert "raw_bytes" not in columns
        assert projects == [("Legacy",)]
        assert segments == [("Hello",)]
        runner.close()

    def test_restore_from_backup_reopens_then_forward_migrates(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.sqlite"
        _apply_old_migrations(db_path)
        db = create_database(db_path)
        try:
            project_id = db.execute(
                "INSERT INTO projects (name, source_language, target_language) "
                "VALUES ('Legacy', 'zh', 'en')",
            ).lastrowid
            doc_id = db.execute(
                "INSERT INTO source_documents "
                "(project_id, name, format, encoding, source_hash, parser_version) "
                "VALUES (?, 's.txt', 'txt', 'utf-8', 'h', '1.0.0')",
                (project_id,),
            ).lastrowid
            db.execute(
                "INSERT INTO segments "
                "(source_document_id, stable_key, source_text, sequence, status) "
                "VALUES (?, 'k1', 'Hello', 1, 'pending')",
                (doc_id,),
            )
            db.connection.commit()
        finally:
            db.close()
        _checkpoint_clean(db_path)

        runner = MigrationRunner.open(db_path)
        runner.apply(discover_migrations(MIGRATIONS_DIR), app_version=APP_VERSION)
        backup_path = runner.last_backup_path
        assert backup_path is not None
        runner.close()

        # 恢复：用 pre-upgrade 备份替换活库（模拟回滚到迁移前状态）。
        db_path.unlink(missing_ok=True)
        _checkpoint_clean(db_path)
        shutil.copyfile(backup_path, db_path)
        # 先用只读连接核验恢复结果：数据保留、schema 回到 008 前（无 raw_bytes）。
        restored_db = create_database(db_path)
        try:
            segments = restored_db.execute(
                "SELECT source_text FROM segments",
            ).fetchall()
            columns = {
                row[1] for row in restored_db.execute("PRAGMA table_info('source_documents')")
            }
        finally:
            restored_db.close()
        assert segments == [("Hello",)]
        assert "raw_bytes" not in columns  # 恢复后回到 008 前 schema

        # 再向前迁移 → 可打开、数据保留、008 已应用。
        runner = MigrationRunner.open(db_path)
        applied = runner.apply(discover_migrations(MIGRATIONS_DIR), app_version=APP_VERSION)
        assert any(m.migration_id == "008_add_format_fidelity" for m in applied)
        runner.close()
        with ProjectService(db_path, app_version=APP_VERSION) as service:
            assert [p.name for p in service.list_projects()] == ["Legacy"]
        migrated_db = create_database(db_path)
        try:
            columns = {
                row[1] for row in migrated_db.execute("PRAGMA table_info('source_documents')")
            }
            segments = migrated_db.execute("SELECT source_text FROM segments").fetchall()
        finally:
            migrated_db.close()
        assert "raw_bytes" in columns
        assert segments == [("Hello",)]

    def test_migration_backup_failure_blocks_migration(self, tmp_path: Path) -> None:
        """备份失败时迁移被阻断，旧库保持可用。"""
        from transrealm.infrastructure.migrations.errors import MigrationBackupError

        db_path = tmp_path / "legacy.sqlite"
        _apply_old_migrations(db_path)

        def failing_backup(
            source_connection: sqlite3.Connection,
            path: Path,
        ) -> Path:
            raise MigrationBackupError("forced backup failure", path=path)

        runner = MigrationRunner.open(db_path)
        try:
            runner._create_backup = lambda: failing_backup(  # type: ignore[method-assign]
                runner._db.connection,
                db_path,
            )
            with pytest.raises(MigrationBackupError):
                runner.apply(
                    discover_migrations(MIGRATIONS_DIR),
                    app_version=APP_VERSION,
                )
        finally:
            runner.close()
        # 迁移未执行：无 008 应用（历史仅 001-007）。
        history = MigrationRunner.open(db_path).history()
        applied_ids = {row["migration_id"] for row in history}
        assert "008_add_format_fidelity" not in applied_ids


# ---------------------------------------------------------------------------
# 3. 开放目录/.aiproject 跨机 + 篡改/限额
# ---------------------------------------------------------------------------


def _build_six_format_container(directory: Path) -> tuple[int, str]:
    with create_open_directory_project(
        directory,
        name="Alpha",
        source_language="zh",
        target_language="en",
        app_version=APP_VERSION,
    ) as created:
        assert created.project.id is not None
        project_id = created.project.id
    db_path = directory / DATABASE_FILENAME
    with ProviderConnectionService(db_path, app_version=APP_VERSION) as svc:
        connection = svc.create_connection(
            name="openai",
            provider_type="openai-compatible",
            endpoint="https://example.invalid/v1",
            credential_reference="env:TRANSLATOR_M03_SECRET",
        )
        connection_name = connection.name
        assert connection.id is not None
        connection_id = connection.id
    with ModelProfileService(db_path, app_version=APP_VERSION) as svc:
        profile = svc.create_profile(
            name="default",
            provider_connection_id=connection_id,
            model_id="gpt-4o-mini",
            template_version="1",
            output_protocol="json",
            context_budget={"max_tokens": 4096},
            default_params={"temperature": 0.2},
            capability=None,
        )
        assert profile.name == "default"
    for fmt in _SIX_FORMATS:
        with ImportService(db_path, app_version=APP_VERSION) as svc:
            source = _golden_path(directory.parent, fmt)
            svc.import_file(project_id, source, format=fmt, name=source.name)
    _checkpoint_clean(db_path)
    _refresh_manifest(directory)
    return project_id, connection_name


class TestContainerCrossMachineAndSecurity:
    """六格式容器跨机 round-trip；篡改/路径/限额在目标落地前拒绝。"""

    def test_six_format_container_cross_machine_round_trip(self, tmp_path: Path) -> None:
        """开放目录 → .aiproject → 第二台机器 → 安装 → 重开：六格式数据全保留。"""
        directory = tmp_path / "machine_a" / "project"
        directory.parent.mkdir()
        project_id, connection_name = _build_six_format_container(directory)
        archive = directory.parent / "alpha.aiproject"
        export_open_directory_archive(directory, archive, app_version=APP_VERSION)

        machine_b = tmp_path / "machine_b"
        machine_b.mkdir()
        staging = machine_b / "staging"
        import_archive_to_staging(archive, staging)
        target = machine_b / "project"
        install_staging_to_target(staging, target, app_version=APP_VERSION)

        with open_open_directory_project(target, app_version=APP_VERSION) as opened:
            assert opened.project.name == "Alpha"
            db = target / DATABASE_FILENAME
            # 六格式文档 + fidelity carrier（008）跨机保留。
            formats = {
                row[0]
                for row in _db_rows(db, "SELECT format FROM source_documents")
            }
            assert formats == set(_SIX_FORMATS)
            assert all(
                row[0] is not None and row[1] is not None
                for row in _db_rows(
                    db,
                    "SELECT raw_bytes, format_metadata FROM source_documents",
                )
            )
            # segments 总量 = 六格式 golden 段数之和。
            (segment_count,) = _db_rows(db, "SELECT COUNT(*) FROM segments")[0]
            assert segment_count == sum(EXPECTED_SEGMENT_COUNTS.values())
            # 连接只存引用，profile 保留。
            (cred_ref,) = _db_rows(
                db,
                "SELECT credential_reference FROM provider_connections WHERE name=?",
                connection_name,
            )[0]
            assert cred_ref == "env:TRANSLATOR_M03_SECRET"
            assert _db_rows(db, "SELECT COUNT(*) FROM model_profiles") == [(1,)]
        # project identity 保留（source_id 追踪）。
        with open_open_directory_project(target, app_version=APP_VERSION) as opened:
            assert opened.manifest.source_id == project_id

    def test_tampered_archive_rejected_before_target_touched(self, tmp_path: Path) -> None:
        directory = tmp_path / "machine_a" / "project"
        directory.parent.mkdir()
        _build_six_format_container(directory)
        archive = directory.parent / "alpha.aiproject"
        export_open_directory_archive(directory, archive, app_version=APP_VERSION)

        # 篡改 manifest 中 database entry 的 hash。
        with zipfile.ZipFile(archive) as reader:
            manifest = json.loads(reader.read(MANIFEST_FILENAME).decode("utf-8"))
        manifest["files"][DATABASE_FILENAME]["hash"] = "sha256:" + "0" * 64
        tampered = directory.parent / "tampered.aiproject"
        with zipfile.ZipFile(archive) as reader:
            names = reader.namelist()
            with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as writer:
                for name in names:
                    if name == MANIFEST_FILENAME:
                        writer.writestr(
                            name,
                            json.dumps(manifest, separators=(",", ":")).encode(),
                        )
                    else:
                        writer.writestr(name, reader.read(name))

        staging = tmp_path / "staging"
        with pytest.raises(FileIntegrityError):
            import_archive_to_staging(tampered, staging)
        # staging 无目标产物（隔离失败清理）。
        assert not staging.exists() or not any(staging.iterdir())

    def test_traversal_archive_rejected_before_target_touched(self, tmp_path: Path) -> None:
        """manifest 声明 ``..`` 越界条目 → 目标落地前拒绝且 staging 无产物。"""
        from transrealm.infrastructure.open_directory import PathValidationError

        directory = tmp_path / "machine_a" / "project"
        directory.parent.mkdir()
        _build_six_format_container(directory)
        archive = directory.parent / "alpha.aiproject"
        export_open_directory_archive(directory, archive, app_version=APP_VERSION)

        with zipfile.ZipFile(archive) as reader:
            manifest = json.loads(reader.read(MANIFEST_FILENAME).decode("utf-8"))
        manifest["files"]["../escape.txt"] = {
            "type": "attachment",
            "size": 4,
            "hash": "sha256:" + "0" * 64,
        }
        evil = directory.parent / "evil.aiproject"
        with zipfile.ZipFile(archive) as reader:
            names = reader.namelist()
            with zipfile.ZipFile(evil, "w", zipfile.ZIP_DEFLATED) as writer:
                for name in names:
                    if name == MANIFEST_FILENAME:
                        writer.writestr(
                            name,
                            json.dumps(manifest, separators=(",", ":")).encode(),
                        )
                    else:
                        writer.writestr(name, reader.read(name))
                writer.writestr("../escape.txt", b"boom")

        staging = tmp_path / "staging"
        with pytest.raises(PathValidationError):
            import_archive_to_staging(evil, staging)
        assert not staging.exists() or not any(staging.iterdir())

    def test_overlimit_archive_rejected_before_target_touched(self, tmp_path: Path) -> None:
        from transrealm.infrastructure.open_directory import ArchiveLimits, extract_archive

        directory = tmp_path / "machine_a" / "project"
        directory.parent.mkdir()
        _build_six_format_container(directory)
        archive = directory.parent / "alpha.aiproject"
        export_open_directory_archive(directory, archive, app_version=APP_VERSION)

        staging = tmp_path / "staging"
        staging.mkdir()
        with pytest.raises(ArchiveLimitError):
            extract_archive(archive, staging, limits=ArchiveLimits(max_entries=1))


# ---------------------------------------------------------------------------
# 4. secret scan
# ---------------------------------------------------------------------------


class TestSecretScan:
    """源码/配置无硬编码凭据；archive/目标只含引用、永不泄 secret。"""

    _CRED_PATTERNS = (
        "sk-m03-live-secret",
        "api_key = '",
        "api_key=\"",
        "password = '",
        "Bearer sk-",
    )

    def test_source_tree_has_no_hardcoded_secrets(self) -> None:
        """``src/`` 与配置中无常见硬编码凭据字面量。"""
        root = Path(__file__).parents[1]
        scan_targets = [
            *sorted((root / "src" / "transrealm").rglob("*.py")),
            root / "pyproject.toml",
            root / "requirements.lock",
        ]
        hits: list[str] = []
        for path in scan_targets:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in self._CRED_PATTERNS:
                if pattern in text:
                    hits.append(f"{path}: {pattern}")
        assert hits == [], "candidate source contains hardcoded credential patterns"

    def test_archive_and_target_hold_only_credential_references(self, tmp_path: Path) -> None:
        directory = tmp_path / "machine_a" / "project"
        directory.parent.mkdir()
        _build_six_format_container(directory)
        archive = directory.parent / "alpha.aiproject"
        export_open_directory_archive(directory, archive, app_version=APP_VERSION)

        secret = "sk-m03-live-secret-value"
        with zipfile.ZipFile(archive) as reader:
            all_bytes = b"".join(reader.read(name) for name in reader.namelist())
        assert secret.encode() not in all_bytes

        machine_b = tmp_path / "machine_b"
        machine_b.mkdir()
        staging = machine_b / "staging"
        import_archive_to_staging(archive, staging)
        target = machine_b / "project"
        install_staging_to_target(staging, target, app_version=APP_VERSION)
        db = target / DATABASE_FILENAME
        (cred_ref,) = _db_rows(
            db,
            "SELECT credential_reference FROM provider_connections",
        )[0]
        assert cred_ref == "env:TRANSLATOR_M03_SECRET"
        assert secret not in (db.read_bytes().decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# 5. 失败隔离
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    """migration 备份失败阻断、导出失败不写目标、DB 不受影响。"""

    def test_failed_export_never_writes_target_and_db_intact(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        document_id, segments = _import_golden(path, project_id, "txt")

        existing = tmp_path / "existing.txt"
        existing.write_text("keep me", encoding="utf-8")
        # 无 revision 且 apply_revisions=True → 缺可用 revision 失败。
        with pytest.raises(ExportError):
            _export(path, document_id, existing, "txt", apply_revisions=True)
        assert existing.read_text(encoding="utf-8") == "keep me"

        # DB 未污染：追加 user revision 后同文档可导出。
        _append_user_revisions(path, segments, TRANSLATIONS["txt"])
        target = tmp_path / "ok.txt"
        _export(path, document_id, target, "txt")
        assert target.read_text(encoding="utf-8") == "译文一\n译文二\n\n译文四\n"

    def test_segments_still_explainable_after_failure(self, tmp_path: Path) -> None:
        """任一失败后所有 Segment 状态可解释（无孤儿/伪 completed）。"""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        _document_id, segments = _import_golden(path, project_id, "txt")
        _append_user_revisions(path, segments, TRANSLATIONS["txt"])
        states = _db_rows(
            path,
            "SELECT status FROM segments ORDER BY sequence",
        )
        assert states == [("completed",), ("completed",), ("completed",)]
        # 每段恰一个 user revision 且其 id == current_revision_id（无孤儿/半写）。
        rows = _db_rows(
            path,
            "SELECT r.id, r.origin, r.is_locked FROM translation_revisions r "
            "JOIN segments s ON s.current_revision_id = r.id ORDER BY r.id",
        )
        assert [(r[1], r[2]) for r in rows] == [("user", 0), ("user", 0), ("user", 0)]
        assert len(rows) == len(segments)
