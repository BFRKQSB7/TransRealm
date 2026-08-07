"""P1-T05-M02: 翻译/恢复/长文本 Gate 矩阵。

旅程级（TranslationService + 真实 OpenAI-compatible adapter + 可控本地
``ThreadingHTTPServer``）自动覆盖：

- 请求切点：claim 后请求发出前崩溃（进程死亡，请求按定义从未发出）、
  请求中断网（server 被杀 → connection_error, retryable）、
  model-stop/超时（server 挂起 → timeout_error, retryable）；
- 事务切点：响应后 finalize 各写入点崩溃（revision insert / segment
  current update / attempt audit update），崩溃回滚保持可恢复；
- 恢复语义：lease 过期回收、retry_failed 重排、locked current 不被自动
  覆盖、completed 不被重复调用（外部调用次数 == Segment 数）。

lease/retry/cancel/locked 的服务级矩阵（P0-T07-M05）、传输级断连/超时/截断分类
（P0-T08-M02）、repair 途中崩溃（P0-T08-M03）、worker 取消/关闭/重启门禁
（P0-T08-M05/P1-T03-M05）与锁定编辑面（P1-T03-M04）由既有 nodeid 提供；本文件
在旅程级补足请求/事务崩溃切点与固定长文本资源基线（`03` §12.5 fixture 由各 M 定义、
`07` §20 执行 Agent 自决 fixture 大小）。

固定长文本 fixture 为模块级常量（`_LONG_TEXT`，120 行 / 固定字符数，测试内断言其
精确大小防漂移），用计数式本地 server 逐 Segment 回显译文，记录内存峰值
（tracemalloc）、耗时（perf_counter）、Segment 数与外部调用次数，并写入 JSON 证据
文件（tmp）。资源基线只记录、不断言虚构阈值（`02` §3 长文本测试）。
"""

from __future__ import annotations

import asyncio
import http.server
import json
import platform
import threading
import time
import tracemalloc
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse
from transrealm.adapters.protocol import ModelAdapter
from transrealm.application.adapter_factory import compose_adapter
from transrealm.application.exporter import TxtExporter
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import (
    TranslationRunService,
    TranslationRunServiceError,
)
from transrealm.application.translation_service import TranslationService, TranslationServiceError
from transrealm.domain.model_profile import ModelCapability
from transrealm.domain.segment import Segment
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_revision_repository import (
    TranslationRevisionRepository,
)

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}

LONG_TEXT_SEGMENT_COUNT = 120
LONG_TEXT_BASE = (
    "The old harbor town woke slowly under a pale winter sky. "
    "Fishermen mended their nets while gulls argued over the docks, "
    "and the smell of tar and salt hung over the quay."
)
_LONG_TEXT = "\n".join(
    f"{i}. {LONG_TEXT_BASE} 序号 {i}。" for i in range(1, LONG_TEXT_SEGMENT_COUNT + 1)
)
LONG_TEXT_CHARS = len(_LONG_TEXT)

# finalize 事务内的写入切点（SQL needle 与 P0-T07-M05 对齐）。
FINALIZE_CRASH_POINTS = [
    pytest.param("INSERT INTO translation_revisions", id="after-revision-insert"),
    pytest.param(
        "UPDATE segments SET status = ?, current_revision_id",
        id="after-segment-current-status-update",
    ),
    pytest.param(
        "UPDATE segment_attempts SET status = ?, request_id",
        id="after-attempt-audit-update",
    ),
]

Responder = Callable[[dict[str, Any]], tuple[int, dict[str, str], bytes]]


class SimulatedCrashError(RuntimeError):
    """由故障注入抛出的进程崩溃模拟。"""


class _TruncatedResponseError(Exception):
    """responder 哨兵：请求发出后、响应写中途截断连接（模拟 mid-response 断连）。"""


class CrashInjector:
    """在共享 ``DatabaseConnection`` 上组合式崩溃注入。

    激活期间，第一个 SQL 文本含 ``needle`` 的 ``execute`` 正常执行后抛
    ``SimulatedCrashError`` —— 模拟进程在该语句落库后、commit 前死亡。
    SQLite 丢弃未提交工作，调用方观察到与真实崩溃相同的恢复语义。
    """

    def __init__(self, connection: Any, needle: str) -> None:
        self._connection = connection
        self._needle = needle
        self._original: Callable[[str, tuple[object, ...] | None], Any] = connection.execute

    def __enter__(self) -> CrashInjector:
        def patched(
            sql: str,
            parameters: tuple[object, ...] | None = None,
        ) -> Any:
            result = self._original(sql, parameters)
            if self._needle in sql:
                raise SimulatedCrashError(
                    f"simulated crash after statement executed: {sql!r}",
                )
            return result

        self._connection.execute = patched  # type: ignore[method-assign]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._connection.execute = self._original  # type: ignore[assignment]
        return None


class AdvanceableClock:
    """可推进的 UTC 时钟，用于 lease 过期/恢复测试。"""

    def __init__(self) -> None:
        self._now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class CrashBeforeRequestAdapter:
    """首次 ``chat_completion`` 抛崩溃（模型请求按定义从未发出）。

    ``translate_segment`` 对 ``SimulatedCrashError`` 透传（不 finalize），因此 DB
    停留在 claim 后的 processing 状态，恰为"请求前崩溃"切点的真实模型。
    """

    def __init__(self, delegate: ModelAdapter) -> None:
        self._delegate = delegate
        self.calls = 0

    def get_capabilities(self) -> ModelCapability:
        return self._delegate.get_capabilities()

    def filter_params(self, params: dict[str, object]) -> dict[str, object]:
        return self._delegate.filter_params(params)

    async def chat_completion(self, request: AdapterRequest) -> AdapterResponse:
        self.calls += 1
        if self.calls == 1:
            raise SimulatedCrashError("process died after claim, before the request")
        return await self._delegate.chat_completion(request)


class _LocalServer:
    """stdlib 本地 HTTP server（可指定端口），记录每个请求。

    响应由可插拔 ``responder`` 决定；每次 POST 都记录 path/headers/body。
    """

    def __init__(
        self,
        responder: Responder,
        *,
        port: int | None = None,
    ) -> None:
        self.records: list[dict[str, Any]] = []
        self._responder = responder
        self._httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", port if port is not None else 0),
            self._make_handler(),
        )
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._stopped = False
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def _make_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                server._handle(self)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler

    def _handle(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        record = {
            "path": handler.path,
            "method": handler.command,
            "headers": {k.lower(): v for k, v in handler.headers.items()},
            "body": raw.decode("utf-8", "replace"),
        }
        self.records.append(record)
        try:
            status, headers, payload = self._responder(record)
        except _TruncatedResponseError:
            # 声明较大的 Content-Length 却只写少量字节后关闭连接：客户端读响应体
            # 时遇到 IncompleteRead，映射为 connection_error（与 P0-T08-M02 截断分类一致）。
            handler.send_response(200)
            handler.send_header("Content-Length", "100")
            handler.end_headers()
            try:
                handler.wfile.write(b"short")
                handler.wfile.flush()
            except OSError:
                pass
            return
        except Exception:
            status, headers, payload = (
                500,
                {"Content-Type": "application/json"},
                b'{"error": {"message": "test responder failed"}}',
            )
        handler.send_response(status)
        for name, value in headers.items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        try:
            handler.wfile.write(payload)
        except OSError:
            pass  # the client may have already timed out

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@contextmanager
def _server(responder: Responder, *, port: int | None = None) -> Any:
    server = _LocalServer(responder, port=port)
    try:
        yield server
    finally:
        server.stop()


def _success_body(stable_key: str, translation: str) -> bytes:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return json.dumps(
        {
            "id": "req-m02",
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                },
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _counting_responder(
    stable_keys: list[str],
    translations: dict[str, str],
) -> Responder:
    """按请求顺序逐 Segment 回显译文（journey 严格顺序、每 Segment 恰一请求）。"""
    state = {"i": 0}

    def responder(record: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        if state["i"] >= len(stable_keys):
            return 500, {"Content-Type": "application/json"}, b'{"error":{"code":"exhausted"}}'
        key = stable_keys[state["i"]]
        state["i"] += 1
        return 200, {"Content-Type": "application/json"}, _success_body(key, translations[key])

    return responder


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _create_project(path: Path, name: str = "M02") -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name=name,
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_txt(path: Path, project_id: int, content: str) -> list[Segment]:
    txt_path = path.parent / "source.txt"
    txt_path.write_text(content, encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as service:
        _document, segments = service.import_txt(project_id, txt_path, name="source.txt")
    return segments


def _make_capability() -> ModelCapability:
    return ModelCapability(
        context_window=128000,
        max_output_tokens=4096,
        supports_streaming=False,
        supports_structured_output=False,
        supported_parameters={"temperature", "max_tokens"},
    )


_CONNECTION_COUNTER = {"n": 0}


def _create_connection_and_profile(
    path: Path,
    *,
    endpoint: str,
    timeout_seconds: int = 30,
    max_retries: int = 0,
) -> tuple[int, int]:
    _CONNECTION_COUNTER["n"] += 1
    name = f"local-{_CONNECTION_COUNTER['n']}"
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.create_connection(
            name=name,
            provider_type="openai-compatible",
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=0.0,
            credential_reference=None,
        )
        assert connection.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profile_service:
            profile = profile_service.create_profile(
                name="general",
                provider_connection_id=connection.id,
                model_id="gpt-4o-mini",
                template_version="1.0.0",
                output_protocol="json",
                context_budget=DEFAULT_BUDGET,
                default_params={"temperature": 0.3},
                capability=_make_capability(),
            )
    assert profile.id is not None
    return connection.id, profile.id


def _load_adapter(path: Path, connection_id: int, profile_id: int) -> Any:
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.get_connection(connection_id)
    with ModelProfileService(path, app_version=APP_VERSION) as profile_service:
        profile = profile_service.get_profile(profile_id)
    assert connection is not None
    assert profile is not None
    return compose_adapter(connection, profile)


def _service(
    path: Path,
    adapter: Any,
    clock: AdvanceableClock | None = None,
) -> TranslationService:
    return TranslationService(path, app_version=APP_VERSION, adapter=adapter, clock=clock)


def _translate(
    service: TranslationService,
    *,
    project_id: int,
    segment_id: int,
    profile_id: int,
    run_id: int | None = None,
) -> tuple[Any, int]:
    if run_id is None:
        run = service.create_run(project_id=project_id)
        assert run.id is not None
        run_id = run.id
    revision = _run(
        service.translate_segment(
            run_id=run_id,
            segment_id=segment_id,
            profile_id=profile_id,
        ),
    )
    return revision, run_id


def _segment_state(path: Path, segment_id: int) -> tuple[str, int | None, str | None]:
    db = create_database(path)
    try:
        row = db.execute(
            "SELECT status, current_revision_id, lease_owner FROM segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    return (
        str(row[0]),
        int(str(row[1])) if row[1] is not None else None,
        str(row[2]) if row[2] is not None else None,
    )


def _revision_ids(path: Path, segment_id: int) -> list[int]:
    repo = TranslationRevisionRepository.open(path)
    try:
        revisions = repo.list_by_segment(segment_id)
    finally:
        repo.close()
    return [revision.id for revision in revisions if revision.id is not None]


def _get_segment(path: Path, segment_id: int) -> Segment:
    repo = SegmentRepository.open(path)
    try:
        segment = repo.get_by_id(segment_id)
    finally:
        repo.close()
    assert segment is not None
    return segment


def _attempt_rows(path: Path, segment_id: int) -> int:
    db = create_database(path)
    try:
        row = db.execute(
            "SELECT COUNT(*) FROM segment_attempts WHERE segment_id = ?",
            (segment_id,),
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    return int(str(row[0]))


def _seed_locked_current(path: Path, segment: Segment) -> int:
    """插入 locked user revision 并置为 current（segment 转 completed）。"""
    assert segment.id is not None
    repo = TranslationRevisionRepository.open(path)
    try:
        locked = TranslationRevision.create(
            segment_id=segment.id,
            text="人工锁定译文",
            origin="user",
        )
        locked.is_locked = True
        locked = repo.save(locked)
    finally:
        repo.close()
    assert locked.id is not None
    db = create_database(path)
    try:
        db.execute(
            "UPDATE segments SET status = 'completed', current_revision_id = ?, "
            "lease_owner = NULL, lease_expires_at = NULL WHERE id = ?",
            (locked.id, segment.id),
        )
        db.connection.commit()
    finally:
        db.close()
    return locked.id


class TestJourneyCrashBeforeRequest:
    """claim 后、请求发出前崩溃：processing 段按 lease 语义安全回收。"""

    def test_crash_after_claim_before_request_recovers(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "first line\nsecond line\n")
        segment = segments[0]
        assert segment.id is not None
        # 崩溃阶段 endpoint 指向不存在端口：崩溃适配器从不真正调用它。
        connection_id, profile_id = _create_connection_and_profile(
            path,
            endpoint="http://127.0.0.1:1",
        )
        clock = AdvanceableClock()

        adapter = _load_adapter(path, connection_id, profile_id)
        crash_adapter = CrashBeforeRequestAdapter(adapter)
        service = _service(path, crash_adapter, clock)
        try:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(SimulatedCrashError):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=segment.id,
                        profile_id=profile_id,
                    ),
                )
            run_id = run.id
        finally:
            service.close()

        # 网络请求从未发出（崩溃适配器第 1 次调用即崩溃，未真正访问 server），
        # DB 停留在 claim 后的 processing。
        assert crash_adapter.calls == 1
        status, current, owner = _segment_state(path, segment.id)
        assert status == "processing"
        assert owner is not None
        assert current is None
        assert _revision_ids(path, segment.id) == []
        assert _attempt_rows(path, segment.id) == 1

        # lease 过期 → 启动恢复 → 回到 pending → 重译成功。
        clock.advance(120)
        with _server(
            lambda record: (200, {}, _success_body(segment.stable_key, "译文")),
        ) as healthy:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=healthy.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            with _service(path, adapter, clock) as recovered:
                assert recovered.recover_expired_leases() == 1
                with TranslationRunService(path, app_version=APP_VERSION) as audit:
                    attempts = audit.list_attempts_for_run(run_id)
                    assert attempts[0].status == "cancelled"
                    assert attempts[0].error_type == "lease_expired"
            with _service(path, adapter, clock) as service2:
                revision, _ = _translate(
                    service2,
                    project_id=project_id,
                    segment_id=segment.id,
                    profile_id=profile_id,
                )
                assert revision.text == "译文"
            assert _segment_state(path, segment.id)[0] == "completed"


class TestJourneyNetworkAndTimeout:
    """请求中断网（server 被杀）与 model-stop/超时：retryable 失败可恢复。"""

    def test_network_loss_mid_journey_recovers(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "first line\nsecond line\n")
        first, second = segments[0], segments[1]
        assert first.id is not None and second.id is not None

        with _server(
            lambda record: (200, {}, _success_body(first.stable_key, "第一条")),
        ) as server:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=server.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            service = _service(path, adapter)
            try:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                _translate(
                    service,
                    project_id=project_id,
                    segment_id=first.id,
                    profile_id=profile_id,
                    run_id=run.id,
                )
                server.stop()  # 断网：model server 中途消失
                with pytest.raises(TranslationServiceError, match="connection_error"):
                    _translate(
                        service,
                        project_id=project_id,
                        segment_id=second.id,
                        profile_id=profile_id,
                        run_id=run.id,
                    )
                run_id = run.id
            finally:
                service.close()

        # 第一个段 completed；第二个段 failed(retryable) 且可解释。
        assert _segment_state(path, first.id)[0] == "completed"
        status, current, _ = _segment_state(path, second.id)
        assert status == "failed"
        assert current is None
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            failed = [a for a in attempts if a.segment_id == second.id]
            assert len(failed) == 1
            assert failed[0].status == "failed"
            assert failed[0].retryable is True
            assert failed[0].error_type == "connection_error"

        # 网络恢复后 retry_failed 重排 → 重译成功（endpoint 重新指向存活 server）。
        with _server(
            lambda record: (200, {}, _success_body(second.stable_key, "第二条")),
        ) as healthy:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=healthy.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            with TranslationRunService(path, app_version=APP_VERSION) as run_service:
                pending = run_service.retry_failed(segment_id=second.id)
                assert pending.status == "pending"
            retry_run_id: int | None = None
            with _service(path, adapter) as service2:
                _revision, retry_run_id = _translate(
                    service2,
                    project_id=project_id,
                    segment_id=second.id,
                    profile_id=profile_id,
                )
        assert _segment_state(path, second.id)[0] == "completed"
        # 原始 run 的失败 attempt 可解释；重试在新 run 中成功（worker 语义）。
        assert retry_run_id is not None
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            seg2 = [a for a in attempts if a.segment_id == second.id]
            assert len(seg2) == 1
            assert seg2[0].status == "failed"
            assert seg2[0].retryable is True
            retried = audit.list_attempts_for_run(retry_run_id)
            assert len(retried) == 1
            assert retried[0].status == "succeeded"

    def test_mid_response_connection_drop_recovers(self, tmp_path: Path) -> None:
        """请求发出后、响应写中途断连（截断）→ connection_error retryable → 可恢复。"""
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "first line\nsecond line\n")
        first, second = segments[0], segments[1]
        assert first.id is not None and second.id is not None
        calls = {"n": 0}

        def truncate_second(record: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
            calls["n"] += 1
            if calls["n"] == 1:
                return 200, {}, _success_body(first.stable_key, "第一条")
            raise _TruncatedResponseError()  # 第二个请求：响应体写中途断连

        with _server(truncate_second) as server:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=server.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            service = _service(path, adapter)
            try:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                _translate(
                    service,
                    project_id=project_id,
                    segment_id=first.id,
                    profile_id=profile_id,
                    run_id=run.id,
                )
                with pytest.raises(TranslationServiceError, match="connection_error"):
                    _translate(
                        service,
                        project_id=project_id,
                        segment_id=second.id,
                        profile_id=profile_id,
                        run_id=run.id,
                    )
                run_id = run.id
            finally:
                service.close()

        assert _segment_state(path, first.id)[0] == "completed"
        status, current, _ = _segment_state(path, second.id)
        assert status == "failed"
        assert current is None
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            seg2 = [a for a in attempts if a.segment_id == second.id]
            assert len(seg2) == 1
            assert seg2[0].status == "failed"
            assert seg2[0].retryable is True
            assert seg2[0].error_type == "connection_error"

        # 连接恢复后 retry_failed 重排 → 重译成功。
        with _server(
            lambda record: (200, {}, _success_body(second.stable_key, "第二条")),
        ) as healthy:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=healthy.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            with TranslationRunService(path, app_version=APP_VERSION) as run_service:
                pending = run_service.retry_failed(segment_id=second.id)
                assert pending.status == "pending"
            with _service(path, adapter) as service2:
                _translate(
                    service2,
                    project_id=project_id,
                    segment_id=second.id,
                    profile_id=profile_id,
                )
        assert _segment_state(path, second.id)[0] == "completed"

    def test_model_stop_timeout_mid_journey_recovers(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "first line\nsecond line\n")
        first, second = segments[0], segments[1]
        assert first.id is not None and second.id is not None
        calls = {"n": 0}

        def hang_once(record: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
            calls["n"] += 1
            if calls["n"] == 2:
                time.sleep(3.0)  # 本地 model 停止/挂起：远超客户端超时前不返回
            key = first.stable_key if calls["n"] == 1 else second.stable_key
            return 200, {}, _success_body(key, "译文")

        with _server(hang_once) as server:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=server.base_url,
                timeout_seconds=1,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            service = _service(path, adapter)
            try:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                _translate(
                    service,
                    project_id=project_id,
                    segment_id=first.id,
                    profile_id=profile_id,
                    run_id=run.id,
                )
                with pytest.raises(TranslationServiceError, match="timeout_error"):
                    _translate(
                        service,
                        project_id=project_id,
                        segment_id=second.id,
                        profile_id=profile_id,
                        run_id=run.id,
                    )
                run_id = run.id
            finally:
                service.close()

        assert _segment_state(path, first.id)[0] == "completed"
        status, current, _ = _segment_state(path, second.id)
        assert status == "failed"
        assert current is None
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            attempts = audit.list_attempts_for_run(run_id)
            seg2 = [a for a in attempts if a.segment_id == second.id]
            assert len(seg2) == 1
            assert seg2[0].status == "failed"
            assert seg2[0].retryable is True
            assert seg2[0].error_type == "timeout_error"

        # model 恢复后重试成功。
        with _server(
            lambda record: (200, {}, _success_body(second.stable_key, "第二条")),
        ) as healthy:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=healthy.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            with TranslationRunService(path, app_version=APP_VERSION) as run_service:
                pending = run_service.retry_failed(segment_id=second.id)
                assert pending.status == "pending"
            with _service(path, adapter) as service2:
                _translate(
                    service2,
                    project_id=project_id,
                    segment_id=second.id,
                    profile_id=profile_id,
                )
        assert _segment_state(path, second.id)[0] == "completed"


class TestJourneyFinalizeCrash:
    """响应后 finalize 事务各写入点崩溃：无伪 completed、无孤立 current。"""

    @pytest.mark.parametrize("needle", FINALIZE_CRASH_POINTS)
    def test_crash_during_finalize_recovers(
        self,
        tmp_path: Path,
        needle: str,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "first line\n")
        segment = segments[0]
        assert segment.id is not None
        clock = AdvanceableClock()

        with _server(
            lambda record: (200, {}, _success_body(segment.stable_key, "译文")),
        ) as server:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=server.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            service = _service(path, adapter, clock)
            try:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                with CrashInjector(service._run_service._db, needle):
                    with pytest.raises(SimulatedCrashError, match="simulated crash"):
                        _run(
                            service.translate_segment(
                                run_id=run.id,
                                segment_id=segment.id,
                                profile_id=profile_id,
                            ),
                        )
                run_id = run.id
            finally:
                service.close()

        # 崩溃后：processing + lease、attempt created 无审计、无 revision、无孤立 current。
        status, current, owner = _segment_state(path, segment.id)
        assert status == "processing"
        assert owner is not None
        assert current is None
        assert _revision_ids(path, segment.id) == []
        assert _attempt_rows(path, segment.id) == 1

        # lease 过期 → 恢复 → 重译成功，attempt 终态可解释。
        clock.advance(120)
        with _server(
            lambda record: (200, {}, _success_body(segment.stable_key, "译文")),
        ) as healthy:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=healthy.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            with _service(path, adapter, clock) as recovered:
                assert recovered.recover_expired_leases() == 1
                with TranslationRunService(path, app_version=APP_VERSION) as audit:
                    attempts = audit.list_attempts_for_run(run_id)
                    assert attempts[0].status == "cancelled"
                    assert attempts[0].error_type == "lease_expired"
            with _service(path, adapter, clock) as service2:
                revision, _ = _translate(
                    service2,
                    project_id=project_id,
                    segment_id=segment.id,
                    profile_id=profile_id,
                )
                assert revision.text == "译文"
        assert _segment_state(path, segment.id)[0] == "completed"


class TestJourneyLockedAndCompleted:
    """locked current 不被自动覆盖；completed 不被重复调用/覆盖。"""

    def test_locked_current_not_overwritten_by_journey(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "first line\nsecond line\n")
        locked_segment, pending_segment = segments[0], segments[1]
        assert locked_segment.id is not None and pending_segment.id is not None
        locked_id = _seed_locked_current(path, locked_segment)

        with _server(
            lambda record: (200, {}, _success_body(pending_segment.stable_key, "第二条")),
        ) as server:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=server.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            service = _service(path, adapter)
            try:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                # locked 段已 completed（非 pending）：自动旅程无法 claim、不发请求。
                with pytest.raises(TranslationRunServiceError, match="not pending"):
                    _run(
                        service.translate_segment(
                            run_id=run.id,
                            segment_id=locked_segment.id,
                            profile_id=profile_id,
                        ),
                    )
                _translate(
                    service,
                    project_id=project_id,
                    segment_id=pending_segment.id,
                    profile_id=profile_id,
                    run_id=run.id,
                )
            finally:
                service.close()

        # locked 段保持：completed、current 仍为 locked revision、无新增 revision。
        status, current, _ = _segment_state(path, locked_segment.id)
        assert status == "completed"
        assert current == locked_id
        assert _revision_ids(path, locked_segment.id) == [locked_id]
        # 其他 pending 段正常翻译。
        assert _segment_state(path, pending_segment.id)[0] == "completed"

    def test_completed_not_recalled_after_restart(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, "first line\nsecond line\n")
        stable_keys = [s.stable_key for s in segments]
        translations = {key: f"译文-{i}" for i, key in enumerate(stable_keys, 1)}

        with _server(_counting_responder(stable_keys, translations)) as server:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=server.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            service = _service(path, adapter)
            run_id: int | None = None
            try:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                run_id = run.id
                for segment in segments:
                    assert segment.id is not None
                    _translate(
                        service,
                        project_id=project_id,
                        segment_id=segment.id,
                        profile_id=profile_id,
                        run_id=run.id,
                    )
            finally:
                service.close()
        assert len(server.records) == len(segments)

        # 重启：无过期 lease；completed 段重译被"not pending"拒绝（不发请求）。
        with _service(path, adapter) as reopened:
            assert reopened.recover_expired_leases() == 0
            for segment in segments:
                assert segment.id is not None
                state = _get_segment(path, segment.id)
                assert state.status == "completed"
                assert state.current_revision_id is not None
            for segment in segments:
                assert segment.id is not None
                with pytest.raises(TranslationRunServiceError, match="not pending"):
                    _run(
                        reopened.translate_segment(
                            run_id=run_id,
                            segment_id=segment.id,
                            profile_id=profile_id,
                        ),
                    )
        # completed 不重复覆盖：server 请求数保持 = Segment 数。
        assert len(server.records) == len(segments)


class TestLongTextJourney:
    """固定长文本完整旅程：资源基线 + 状态全可解释 + 零数据损失。"""

    def test_fixture_is_fixed_and_recorded(self) -> None:
        """长文本 fixture 是固定常量；防漂移断言其精确大小。"""
        assert LONG_TEXT_SEGMENT_COUNT == 120
        assert len(_LONG_TEXT.splitlines()) == LONG_TEXT_SEGMENT_COUNT
        assert LONG_TEXT_CHARS == len(_LONG_TEXT)
        assert LONG_TEXT_CHARS > 8000  # 长文本：固定但足量的输入基准

    def test_long_text_complete_journey_records_resource_baseline(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path)
        segments = _import_txt(path, project_id, _LONG_TEXT)
        assert len(segments) == LONG_TEXT_SEGMENT_COUNT
        stable_keys = [s.stable_key for s in segments]
        translations = {key: f"译文-{i}" for i, key in enumerate(stable_keys, 1)}

        with _server(_counting_responder(stable_keys, translations)) as server:
            connection_id, profile_id = _create_connection_and_profile(
                path,
                endpoint=server.base_url,
            )
            adapter = _load_adapter(path, connection_id, profile_id)
            service = _service(path, adapter)
            run_id: int | None = None
            try:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                run_id = run.id
                tracemalloc.start()
                try:
                    started = time.perf_counter()
                    for segment in segments:
                        assert segment.id is not None
                        _translate(
                            service,
                            project_id=project_id,
                            segment_id=segment.id,
                            profile_id=profile_id,
                            run_id=run.id,
                        )
                    elapsed = time.perf_counter() - started
                finally:
                    _current, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                service.finish_run(run_id=run.id, status="completed")
            finally:
                service.close()

        metrics = {
            "fixture": "fixed 120-line long text",
            "input_chars": LONG_TEXT_CHARS,
            "segment_count": LONG_TEXT_SEGMENT_COUNT,
            "model_calls": len(server.records),
            "elapsed_seconds": round(elapsed, 4),
            "peak_python_bytes": peak,
            "python_version": platform.python_version(),
        }
        print(f"\nLONG_TEXT_RESOURCE_BASELINE {json.dumps(metrics, ensure_ascii=False)}")
        evidence = tmp_path / "long_text_metrics.json"
        evidence.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

        # 外部调用次数 == Segment 数（clean journey：每 Segment 恰一次，
        # 无 repair/transport retry）。
        assert len(server.records) == LONG_TEXT_SEGMENT_COUNT
        # 状态全可解释：每个 Segment completed 且有 current revision；run 终态 completed。
        for segment in segments:
            assert segment.id is not None
            state = _get_segment(path, segment.id)
            assert state.status == "completed"
            assert state.current_revision_id is not None
        with TranslationRunService(path, app_version=APP_VERSION) as audit:
            persisted_run = audit.get_run(run_id)
            assert persisted_run is not None
            assert persisted_run.status == "completed"
            attempts = audit.list_attempts_for_run(run_id)
            assert len(attempts) == LONG_TEXT_SEGMENT_COUNT

        # 重启：零数据损失、无过期 lease、completed 不重复覆盖。
        with _service(path, adapter) as reopened:
            assert reopened.recover_expired_leases() == 0
            revisions = 0
            for segment in segments:
                assert segment.id is not None
                persisted = _get_segment(path, segment.id)
                assert persisted.source_text == segment.source_text
                assert persisted.status == "completed"
                revisions += len(_revision_ids(path, segment.id))
            assert revisions == LONG_TEXT_SEGMENT_COUNT
        assert len(server.records) == LONG_TEXT_SEGMENT_COUNT

        # 完整旅程含导出 round-trip：TxtExporter 读 current Revision 导出、可重导入。
        export_path = tmp_path / "translated.txt"
        with TxtExporter(path, app_version=APP_VERSION) as exporter:
            exporter.export_document(
                source_document_id=segments[0].source_document_id,
                target_path=export_path,
            )
        exported = export_path.read_text(encoding="utf-8")
        assert "译文-1" in exported
        assert _LONG_TEXT.splitlines()[0] not in exported  # 目标 span 已被译文替换

        # 资源基线记录为证据：断言指标已捕获（不虚构无依据阈值）。
        assert peak > 0
        assert elapsed > 0
        assert metrics["model_calls"] == LONG_TEXT_SEGMENT_COUNT
