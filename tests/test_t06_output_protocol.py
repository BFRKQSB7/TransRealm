"""Release matrix: real compatible endpoint, plain text and legacy JSON output."""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_facade import TranslationFacade
from transrealm.application.translation_service import TranslationServiceError
from transrealm.domain.model_profile import ModelCapability

VERSION = "0.2.0-test"


class Endpoint:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.response = "你好，世界。"
        self.finish_reason = "stop"
        self.as_json = False
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append(body)
                text = owner.response
                if owner.as_json:
                    prompt = body["messages"][0]["content"]
                    # The endpoint only sees the request; it cannot query the app database.
                    key = json.loads(
                        prompt.split("Target segment IDs (in order): ")[1].split("\n", 1)[0]
                    )[0]
                    text = json.dumps({"items": [{"segment_id": key, "translation": text}]})
                payload = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": text},
                                "finish_reason": owner.finish_reason,
                            }
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def endpoint() -> Iterator[Endpoint]:
    server = Endpoint()
    try:
        yield server
    finally:
        server.close()


def configured(db: Path, endpoint: Endpoint, protocol: str, *, structured: bool = False) -> int:
    with ProviderConnectionService(db, app_version=VERSION) as service:
        provider = service.create_connection(
            name="Release loopback",
            provider_type="openai-compatible",
            endpoint=f"http://127.0.0.1:{endpoint.server.server_port}/v1",
            timeout_seconds=3,
            max_retries=0,
            retry_delay_seconds=0,
        )
    assert provider.id is not None
    with ModelProfileService(db, app_version=VERSION) as service:
        profile = service.create_profile(
            name="Release model",
            provider_connection_id=provider.id,
            model_id="test-model",
            template_version="1.0.0",
            output_protocol=protocol,
            context_budget={"total": 8192, "reserved_output": 1024, "reserved_prompt": 512},
            capability=ModelCapability(8192, 1024, False, structured, {"max_tokens"}),
            default_params={"max_tokens": 1024, "unsupported_parameter": 99},
        )
    assert profile.id is not None
    return profile.id


def prepare(db: Path, model_id: int) -> tuple[int, int]:
    source = db.parent / "source.txt"
    source.write_text("Hello, world.\nAnother segment.\n", encoding="utf-8")
    with TranslationFacade(db, app_version=VERSION) as facade:
        job = facade.create_job(name="Release", source_language="en", target_language="zh")
        assert job.id is not None
        facade.select_active_profile(job.id, model_id)
        _, segments = facade.import_document(job.id, source)
        assert segments[0].id is not None
        return job.id, segments[0].id


def test_plain_text_endpoint_creates_exactly_one_target_revision(
    tmp_path: Path,
    endpoint: Endpoint,
) -> None:
    db = tmp_path / "job.sqlite"
    model_id = configured(db, endpoint, "text")
    job_id, segment_id = prepare(db, model_id)
    adapter = TranslationFacade.adapter_for_profile(db, VERSION, model_id)
    with TranslationFacade(db, app_version=VERSION, adapter=adapter) as facade:
        run = facade.start_run(job_id)
        assert run.id is not None
        revision = asyncio.run(
            facade.translate_segment(
                run_id=run.id,
                segment_id=segment_id,
                profile_id=model_id,
            )
        )
        assert revision.text == endpoint.response
        assert len(facade.revisions(segment_id)) == 1
        attempts = facade.attempts(run.id)
        assert len(attempts) == 1 and attempts[0].status == "succeeded"
        assert attempts[0].validator_summary["output_protocol"] == "text"
        assert "Return only the translation" in endpoint.requests[0]["messages"][0]["content"]
        assert "response_format" not in endpoint.requests[0]
        assert "unsupported_parameter" not in endpoint.requests[0]


@pytest.mark.parametrize(
    "text,reason",
    [
        ("", "stop"),
        ("   ", "stop"),
        ("Hello, world.", "stop"),
        ("<think>reasoning</think>你好", "stop"),
        ("```text\n你好\n```", "stop"),
        ("Current segment:\nHello, world.", "stop"),
        ("你好", "length"),
        ("你好", "content_filter"),
        ('{"items":[{"segment_id":"unrelated","translation":"wrong target"}]}', "stop"),
    ],
)
def test_invalid_or_incomplete_plain_text_creates_no_revision(
    tmp_path: Path,
    endpoint: Endpoint,
    text: str,
    reason: str,
) -> None:
    endpoint.response, endpoint.finish_reason = text, reason
    db = tmp_path / "job.sqlite"
    model_id = configured(db, endpoint, "text")
    job_id, segment_id = prepare(db, model_id)
    adapter = TranslationFacade.adapter_for_profile(db, VERSION, model_id)
    with TranslationFacade(db, app_version=VERSION, adapter=adapter) as facade:
        run = facade.start_run(job_id)
        assert run.id is not None
        with pytest.raises(TranslationServiceError, match="validation"):
            asyncio.run(
                facade.translate_segment(
                    run_id=run.id,
                    segment_id=segment_id,
                    profile_id=model_id,
                )
            )
        assert facade.revisions(segment_id) == []
        assert facade.attempts(run.id)[0].status == "failed"
        assert len(endpoint.requests) == 1


@pytest.mark.parametrize("structured", [False, True])
def test_legacy_json_target_is_in_request_and_structured_feature_is_capability_driven(
    tmp_path: Path,
    endpoint: Endpoint,
    structured: bool,
) -> None:
    endpoint.as_json = True
    db = tmp_path / "job.sqlite"
    model_id = configured(db, endpoint, "json", structured=structured)
    job_id, segment_id = prepare(db, model_id)
    adapter = TranslationFacade.adapter_for_profile(db, VERSION, model_id)
    with TranslationFacade(db, app_version=VERSION, adapter=adapter) as facade:
        run = facade.start_run(job_id)
        assert run.id is not None
        revision = asyncio.run(
            facade.translate_segment(
                run_id=run.id,
                segment_id=segment_id,
                profile_id=model_id,
            )
        )
        assert revision.text == endpoint.response
        assert ("response_format" in endpoint.requests[0]) == structured
