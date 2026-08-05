"""Tests for P0-T08-M02: the production call boundary.

A real stdlib transport, env/wincred credential resolvers and the
connection+profile composition are verified against a controlled local
``ThreadingHTTPServer``: endpoint composition, timeout, redirects (same-origin
keeps Authorization, cross-origin strips it), auth and response errors
classify stably under the AdapterError taxonomy, and secrets never leak into
errors or audit records.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import socket
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.credential_resolvers import (
    EnvironmentResolver,
    WindowsCredentialResolver,
    build_resolver,
)
from transrealm.adapters.dto import AdapterMessage, AdapterRequest
from transrealm.adapters.errors import (
    AdapterAuthenticationError,
    AdapterConnectionError,
    AdapterRateLimitError,
    AdapterResponseError,
    AdapterServerError,
    AdapterTimeoutError,
)
from transrealm.adapters.http_transport import StdlibHttpTransport
from transrealm.application.adapter_factory import (
    AdapterCompositionError,
    compose_adapter,
)
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.translation_service import (
    TranslationService,
    TranslationServiceError,
)
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.provider_connection import ProviderConnection
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}

Responder = Callable[[dict[str, Any]], tuple[int, dict[str, str], bytes]]


class _LocalServer:
    """A stdlib HTTP server on an ephemeral port with a pluggable responder.

    Every request is recorded (path, method, normalized headers, body) so
    tests can assert what the transport actually sent.
    """

    def __init__(self, responder: Responder) -> None:
        self.records: list[dict[str, Any]] = []
        self._responder = responder
        self._httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            self._make_handler(),
        )
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
        )
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
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


@contextmanager
def _server(responder: Responder) -> Any:
    server = _LocalServer(responder)
    try:
        yield server
    finally:
        server.stop()


def _success_body(stable_key: str = "S-1", translation: str = "こんにちは") -> bytes:
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


def _error_body(code: str) -> bytes:
    return json.dumps(
        {"error": {"code": code, "message": "provider says no"}},
    ).encode("utf-8")


def _request() -> AdapterRequest:
    return AdapterRequest(
        model_id="test-model",
        messages=(AdapterMessage(role="user", content="translate this"),),
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_capability() -> ModelCapability:
    return ModelCapability(
        context_window=128000,
        max_output_tokens=4096,
        supports_streaming=False,
        supports_structured_output=False,
        supported_parameters={"temperature", "max_tokens"},
    )


class TestEnvironmentResolver:
    """env: references resolve against the process environment."""

    def test_resolves_existing_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("M02_API_KEY", "sk-value")
        resolver = EnvironmentResolver()
        assert _run(resolver.resolve("env:M02_API_KEY")) == "sk-value"

    def test_missing_variable_raises_and_never_leaks_secret(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("M02_ABSENT", raising=False)
        resolver = EnvironmentResolver()
        with pytest.raises(AdapterAuthenticationError) as exc:
            _run(resolver.resolve("env:M02_ABSENT"))
        assert "M02_ABSENT" in str(exc.value)
        assert "sk-" not in str(exc.value)

    def test_rejects_non_env_scheme(self) -> None:
        resolver = EnvironmentResolver()
        with pytest.raises(AdapterAuthenticationError, match="env:"):
            _run(resolver.resolve("wincred:transrealm/key"))


class TestWindowsCredentialResolver:
    """wincred: references resolve against the Windows Credential Manager."""

    def test_resolves_utf8_blob(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            WindowsCredentialResolver,
            "_read_credential",
            lambda self, target: b"sk-win-secret",
        )
        resolver = WindowsCredentialResolver()
        assert _run(resolver.resolve("wincred:transrealm/key")) == "sk-win-secret"

    def test_missing_credential_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            WindowsCredentialResolver,
            "_read_credential",
            lambda self, target: None,
        )
        resolver = WindowsCredentialResolver()
        with pytest.raises(AdapterAuthenticationError, match="not found"):
            _run(resolver.resolve("wincred:transrealm/missing"))

    def test_invalid_utf8_blob_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            WindowsCredentialResolver,
            "_read_credential",
            lambda self, target: b"\xff\xfe\x80",
        )
        resolver = WindowsCredentialResolver()
        with pytest.raises(AdapterAuthenticationError, match="UTF-8"):
            _run(resolver.resolve("wincred:transrealm/binary"))

    def test_rejects_non_wincred_scheme(self) -> None:
        resolver = WindowsCredentialResolver()
        with pytest.raises(AdapterAuthenticationError, match="wincred:"):
            _run(resolver.resolve("env:M02_API_KEY"))


class TestBuildResolver:
    """Resolver selection follows the reference scheme."""

    def test_none_when_unset(self) -> None:
        assert build_resolver(None) is None

    def test_env_scheme(self) -> None:
        assert isinstance(build_resolver("env:M02_API_KEY"), EnvironmentResolver)

    def test_wincred_scheme(self) -> None:
        assert isinstance(
            build_resolver("wincred:transrealm/key"),
            WindowsCredentialResolver,
        )

    def test_unsupported_scheme(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            build_resolver("plain:secret")


class TestStdlibHttpTransport:
    """The real transport against a controlled local server."""

    def test_posts_to_endpoint_path(self) -> None:
        with _server(lambda record: (200, {}, _success_body())) as server:
            transport = StdlibHttpTransport(base_url=server.base_url)
            response = _run(
                transport.post(
                    "/v1/chat/completions",
                    {"Content-Type": "application/json"},
                    {"model": "test-model", "messages": []},
                    5.0,
                ),
            )
            assert response.status_code == 200
            assert len(server.records) == 1
            assert server.records[0]["path"] == "/v1/chat/completions"
            assert server.records[0]["method"] == "POST"
            body = json.loads(server.records[0]["body"])
            assert body["model"] == "test-model"

    def test_returns_status_headers_body_and_elapsed(self) -> None:
        with _server(lambda record: (201, {"X-Trace": "abc"}, b"raw")) as server:
            transport = StdlibHttpTransport(base_url=server.base_url)
            response = _run(
                transport.post("/path", {}, {"a": 1}, 5.0),
            )
            assert response.status_code == 201
            assert response.headers["x-trace"] == "abc"
            assert response.body == b"raw"
            assert response.elapsed_seconds >= 0.0

    def test_v1_endpoint_prefix_is_not_doubled(self) -> None:
        with _server(lambda record: (200, {}, _success_body())) as server:
            transport = StdlibHttpTransport(base_url=f"{server.base_url}/v1")
            _run(transport.post("/v1/chat/completions", {}, {"model": "m"}, 5.0))
            assert server.records[0]["path"] == "/v1/chat/completions"

    def test_same_origin_redirect_keeps_authorization(self) -> None:
        calls = {"n": 0}

        def responder(record: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
            calls["n"] += 1
            if calls["n"] == 1:
                return 307, {"Location": "/v1/chat/completions?hop=2"}, b""
            return 200, {"Content-Type": "application/json"}, _success_body()

        with _server(responder) as server:
            transport = StdlibHttpTransport(base_url=server.base_url)
            headers = {"Authorization": "Bearer sk-hop"}
            response = _run(
                transport.post("/v1/chat/completions", headers, {"model": "m"}, 5.0),
            )
            assert response.status_code == 200
            assert len(server.records) == 2
            assert server.records[0]["headers"]["authorization"] == "Bearer sk-hop"
            assert server.records[1]["headers"]["authorization"] == "Bearer sk-hop"

    def test_cross_origin_redirect_strips_authorization(self) -> None:
        target_records: list[dict[str, Any]] = []

        def target_responder(
            record: dict[str, Any],
        ) -> tuple[int, dict[str, str], bytes]:
            target_records.append(record)
            return 200, {"Content-Type": "application/json"}, _success_body()

        with _server(target_responder) as target:
            with _server(lambda record: (
                307,
                {"Location": f"{target.base_url}/v1/chat/completions"},
                b"",
            )) as source:
                transport = StdlibHttpTransport(base_url=source.base_url)
                response = _run(
                    transport.post(
                        "/v1/chat/completions",
                        {"Authorization": "Bearer sk-hop"},
                        {"model": "m"},
                        5.0,
                    ),
                )
                assert response.status_code == 200
                assert source.records[0]["headers"]["authorization"] == "Bearer sk-hop"
                assert "authorization" not in target_records[0]["headers"]

    def test_redirect_loop_is_bounded(self) -> None:
        with _server(lambda record: (
            307,
            {"Location": "/v1/chat/completions"},
            b"",
        )) as server:
            transport = StdlibHttpTransport(base_url=server.base_url, max_redirects=5)
            response = _run(
                transport.post("/v1/chat/completions", {}, {"model": "m"}, 5.0),
            )
            assert response.status_code == 307
            assert len(server.records) == 6

    def test_redirect_without_location_is_returned(self) -> None:
        with _server(lambda record: (302, {}, b"")) as server:
            transport = StdlibHttpTransport(base_url=server.base_url)
            response = _run(
                transport.post("/v1/chat/completions", {}, {"model": "m"}, 5.0),
            )
            assert response.status_code == 302

    def test_non_http_redirect_is_not_followed(self) -> None:
        with _server(lambda record: (
            307,
            {"Location": "file:///C:/Windows/win.ini"},
            b"",
        )) as server:
            transport = StdlibHttpTransport(base_url=server.base_url)
            response = _run(
                transport.post("/v1/chat/completions", {}, {"model": "m"}, 5.0),
            )
            assert response.status_code == 307
            assert len(server.records) == 1

    def test_timeout_classified_as_timeout_error(self) -> None:
        def slow(record: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
            time.sleep(0.4)
            return 200, {}, _success_body()

        with _server(slow) as server:
            transport = StdlibHttpTransport(base_url=server.base_url)
            with pytest.raises(AdapterTimeoutError, match="timed out"):
                _run(transport.post("/v1/chat/completions", {}, {"model": "m"}, 0.05))

    def test_connection_refused_classified_as_connection_error(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        transport = StdlibHttpTransport(base_url=f"http://127.0.0.1:{port}")
        with pytest.raises(AdapterConnectionError):
            _run(transport.post("/v1/chat/completions", {}, {"model": "m"}, 5.0))

    def test_non_2xx_returned_for_adapter_classification(self) -> None:
        with _server(lambda record: (401, {}, _error_body("bad_key"))) as server:
            transport = StdlibHttpTransport(base_url=server.base_url)
            response = _run(
                transport.post("/v1/chat/completions", {}, {"model": "m"}, 5.0),
            )
            assert response.status_code == 401
            assert b"bad_key" in response.body

    def test_truncated_response_classified_as_connection_error(self) -> None:
        ready = threading.Event()
        port: dict[str, int] = {}

        def serve() -> None:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port["value"] = sock.getsockname()[1]
                sock.listen(1)
                ready.set()
                conn, _ = sock.accept()
                conn.recv(65536)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 100\r\n"
                    b"Content-Type: application/json\r\n"
                    b"\r\n"
                    b"short",
                )
                conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        assert ready.wait(timeout=5)
        transport = StdlibHttpTransport(base_url=f"http://127.0.0.1:{port['value']}")
        with pytest.raises(AdapterConnectionError):
            _run(transport.post("/v1/chat/completions", {}, {"model": "m"}, 5.0))
        thread.join(timeout=5)


class TestComposition:
    """Connection/profile config composes into a working adapter."""

    def _connection(
        self,
        endpoint: str,
        credential_reference: str | None,
        max_retries: int = 0,
    ) -> ProviderConnection:
        return ProviderConnection.create(
            name="local",
            provider_type="openai-compatible",
            endpoint=endpoint,
            timeout_seconds=30,
            max_retries=max_retries,
            retry_delay_seconds=0.0,
            credential_reference=credential_reference,
        )

    def _profile(self, capability: ModelCapability | None) -> ModelProfile:
        return ModelProfile.create(
            name="general",
            provider_connection_id=1,
            model_id="gpt-4o-mini",
            template_version="1.0.0",
            output_protocol="json",
            context_budget=DEFAULT_BUDGET,
            default_params={"temperature": 0.3},
            capability=capability,
        )

    def _adapter(
        self,
        server: _LocalServer,
        *,
        credential_reference: str | None,
        max_retries: int = 0,
    ) -> Any:
        return compose_adapter(
            self._connection(server.base_url, credential_reference, max_retries),
            self._profile(_make_capability()),
        )

    def test_success_roundtrip_sends_authorization(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("M02_API_KEY", "sk-composed-secret")
        with _server(lambda record: (200, {}, _success_body())) as server:
            adapter = self._adapter(server, credential_reference="env:M02_API_KEY")
            response = _run(adapter.chat_completion(_request()))
            assert response.content != ""
            assert server.records[0]["path"] == "/v1/chat/completions"
            assert server.records[0]["headers"]["authorization"] == "Bearer sk-composed-secret"
            body = json.loads(server.records[0]["body"])
            assert body["model"] == "test-model"

    def test_no_credential_sends_no_authorization(self) -> None:
        with _server(lambda record: (200, {}, _success_body())) as server:
            adapter = self._adapter(server, credential_reference=None)
            _run(adapter.chat_completion(_request()))
            assert "authorization" not in server.records[0]["headers"]

    def test_401_classified_as_authentication_without_secret(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("M02_API_KEY", "sk-secret-401")
        with _server(lambda record: (401, {}, _error_body("invalid_api_key"))) as server:
            adapter = self._adapter(server, credential_reference="env:M02_API_KEY")
            with pytest.raises(AdapterAuthenticationError) as exc:
                _run(adapter.chat_completion(_request()))
            assert "sk-secret-401" not in str(exc.value)
            assert "Authorization" not in str(exc.value)

    def test_429_classified_as_rate_limit_with_retry_after(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("M02_API_KEY", "sk-secret-429")
        with _server(lambda record: (
            429,
            {"Retry-After": "3"},
            _error_body("rate_limit"),
        )) as server:
            adapter = self._adapter(server, credential_reference="env:M02_API_KEY")
            with pytest.raises(AdapterRateLimitError) as exc:
                _run(adapter.chat_completion(_request()))
            assert exc.value.retry_after_seconds == 3.0
            assert "sk-secret-429" not in str(exc.value)

    def test_500_classified_as_server_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("M02_API_KEY", "sk-secret-500")
        with _server(lambda record: (500, {}, _error_body("server_error"))) as server:
            adapter = self._adapter(server, credential_reference="env:M02_API_KEY")
            with pytest.raises(AdapterServerError):
                _run(adapter.chat_completion(_request()))

    def test_unexpected_status_classified_as_response_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("M02_API_KEY", "sk-secret-418")
        with _server(lambda record: (418, {}, b"teapot")) as server:
            adapter = self._adapter(server, credential_reference="env:M02_API_KEY")
            with pytest.raises(AdapterResponseError):
                _run(adapter.chat_completion(_request()))

    def test_retryable_server_error_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("M02_API_KEY", "sk-secret-retry")
        calls = {"n": 0}

        def responder(record: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
            calls["n"] += 1
            if calls["n"] == 1:
                return 503, {}, _error_body("overloaded")
            return 200, {"Content-Type": "application/json"}, _success_body()

        with _server(responder) as server:
            adapter = self._adapter(
                server,
                credential_reference="env:M02_API_KEY",
                max_retries=1,
            )
            response = _run(adapter.chat_completion(_request()))
            assert response.content != ""
            assert calls["n"] == 2

    def test_compose_missing_capability_raises(self) -> None:
        connection = self._connection("http://127.0.0.1:1", None)
        profile = self._profile(capability=None)
        with pytest.raises(AdapterCompositionError, match="capability"):
            compose_adapter(connection, profile)


class TestEndToEndWithLocalServer:
    """The full vertical slice through a real HTTP server."""

    def _project(self, path: Path) -> int:
        with ProjectService(path, app_version=APP_VERSION) as service:
            project = service.create_project(
                name="M02",
                source_language="ja",
                target_language="zh",
            )
            assert project.id is not None
            return project.id

    def _import_txt(self, path: Path, project_id: int, content: str) -> Any:
        txt_path = path.parent / "source.txt"
        txt_path.write_text(content, encoding="utf-8")
        with ImportService(path, app_version=APP_VERSION) as service:
            _document, segments = service.import_txt(project_id, txt_path, name="source.txt")
        return segments

    def _create_connection_and_profile(
        self,
        path: Path,
        *,
        endpoint: str,
        credential_reference: str | None,
    ) -> tuple[int, int]:
        with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
            connection = conn_service.create_connection(
                name="local",
                provider_type="openai-compatible",
                endpoint=endpoint,
                timeout_seconds=30,
                max_retries=0,
                retry_delay_seconds=0.0,
                credential_reference=credential_reference,
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

    def _load_connection_and_profile(
        self,
        path: Path,
        connection_id: int,
        profile_id: int,
    ) -> tuple[Any, Any]:
        with ProviderConnectionService(path, app_version=APP_VERSION) as service:
            connection = service.get_connection(connection_id)
        with ModelProfileService(path, app_version=APP_VERSION) as service:
            profile = service.get_profile(profile_id)
        assert connection is not None
        assert profile is not None
        return connection, profile

    def test_translate_segment_against_local_server(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("M02_E2E_KEY", "sk-e2e-secret")
        path = tmp_path / "project.sqlite"
        project_id = self._project(path)
        segments = self._import_txt(path, project_id, "Hello world.\nSecond line here.\n")
        stable_key = segments[0].stable_key
        segment_id = segments[0].id
        assert segment_id is not None

        with _server(lambda record: (
            200,
            {},
            _success_body(stable_key, "こんにちは"),
        )) as server:
            connection_id, profile_id = self._create_connection_and_profile(
                path,
                endpoint=server.base_url,
                credential_reference="env:M02_E2E_KEY",
            )
            connection, profile = self._load_connection_and_profile(
                path,
                connection_id,
                profile_id,
            )
            adapter = compose_adapter(connection, profile)

            with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                revision = _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=segment_id,
                        profile_id=profile_id,
                    ),
                )
                assert revision.text == "こんにちは"

            record = server.records[0]
            assert record["path"] == "/v1/chat/completions"
            assert record["headers"]["authorization"] == "Bearer sk-e2e-secret"
            body = json.loads(record["body"])
            assert body["model"] == "gpt-4o-mini"

    def test_http_error_attempt_audit_has_no_secret(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("M02_E2E_KEY", "sk-e2e-secret-401")
        with _server(lambda record: (
            401,
            {},
            _error_body("invalid_api_key"),
        )) as server:
            path = tmp_path / "project.sqlite"
            project_id = self._project(path)
            segments = self._import_txt(path, project_id, "Hello world.\n")
            assert segments[0].id is not None
            connection_id, profile_id = self._create_connection_and_profile(
                path,
                endpoint=server.base_url,
                credential_reference="env:M02_E2E_KEY",
            )
            connection, profile = self._load_connection_and_profile(
                path,
                connection_id,
                profile_id,
            )
            adapter = compose_adapter(connection, profile)

            with TranslationService(path, app_version=APP_VERSION, adapter=adapter) as service:
                run = service.create_run(project_id=project_id)
                assert run.id is not None
                with pytest.raises(TranslationServiceError, match="authentication_error"):
                    _run(
                        service.translate_segment(
                            run_id=run.id,
                            segment_id=segments[0].id,
                            profile_id=profile_id,
                        ),
                    )
                secret = "sk-e2e-secret-401"
                with TranslationRunService(path, app_version=APP_VERSION) as audit:
                    attempts = audit.list_attempts_for_run(run.id)
                    assert len(attempts) == 1
                    assert attempts[0].status == "failed"
                    assert attempts[0].retryable is False
                    assert attempts[0].error_type == "authentication_error"
                    assert secret not in (attempts[0].error_message or "")

                repo = SegmentRepository.open(path)
                try:
                    segment = repo.get_by_id(segments[0].id)
                finally:
                    repo.close()
                assert segment is not None
                assert segment.status == "failed"
