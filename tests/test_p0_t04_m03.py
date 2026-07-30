"""P0-T04-M03: timeout, rate limit, error classification and transport retry.

These tests verify the OpenAI-compatible adapter's limited retry policy using
a fake transport and a fake async sleeper. No real network calls are made.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterMessage, AdapterRequest
from transrealm.adapters.errors import (
    AdapterAuthenticationError,
    AdapterAuthorizationError,
    AdapterConnectionError,
    AdapterResponseError,
    AdapterServerError,
    AdapterTimeoutError,
    AdapterValidationError,
)
from transrealm.adapters.openai_adapter import OpenAICompatibleAdapter
from transrealm.adapters.protocol import TransportResponse
from transrealm.domain.model_profile import ModelCapability


class FakeSequencedTransport:
    """In-memory transport that returns a programmed sequence of responses."""

    def __init__(self, responses: list[TransportResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def post(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> TransportResponse:
        self.calls.append({
            "path": path,
            "headers": headers,
            "body": body,
            "timeout": timeout,
        })
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSleeper:
    """Records async sleep delays without actually waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


def make_capability(
    *,
    context_window: int = 4096,
    max_output_tokens: int = 512,
    streaming: bool = False,
    structured: bool = False,
    params: set[str] | None = None,
) -> ModelCapability:
    return ModelCapability(
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        supports_streaming=streaming,
        supports_structured_output=structured,
        supported_parameters=params or set(),
    )


def make_success_payload(content: str = "ok") -> dict[str, object]:
    return {
        "id": "r",
        "choices": [{
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }


def make_adapter(
    transport: Any,
    capability: ModelCapability | None = None,
    max_retries: int = 0,
    retry_delay_seconds: float = 0.0,
    sleeper: FakeSleeper | None = None,
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        endpoint="https://api.example.com",
        model_id="gpt-test",
        capability=capability or make_capability(),
        transport=transport,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        _sleeper=sleeper.sleep if sleeper else asyncio.sleep,
    )


def run(coro: Any) -> Any:
    """Run a coroutine in a temporary event loop for tests."""
    return asyncio.run(coro)


def make_request(**kwargs: Any) -> AdapterRequest:
    defaults: dict[str, Any] = {
        "model_id": "m",
        "messages": (AdapterMessage(role="user", content="hi"),),
    }
    defaults.update(kwargs)
    return AdapterRequest(**defaults)


class TestOpenAIAdapterRetryClassification:
    """Retry only retryable errors and stop on permanent errors."""

    def test_non_retryable_errors_do_not_retry(self) -> None:
        non_retryable_cases = [
            (401, AdapterAuthenticationError),
            (403, AdapterAuthorizationError),
            (400, AdapterValidationError),
            (422, AdapterValidationError),
            (418, AdapterResponseError),
        ]
        for status, expected_exc in non_retryable_cases:
            transport = FakeSequencedTransport([
                TransportResponse(status, {}, b"err", 0.1),
                TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
            ])
            sleeper = FakeSleeper()
            adapter = make_adapter(transport, max_retries=2, sleeper=sleeper)
            with pytest.raises(expected_exc):
                run(adapter.chat_completion(make_request()))
            assert len(transport.calls) == 1
            assert len(sleeper.delays) == 0

    def test_500_retries_until_success(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(500, {}, b"server error", 0.1),
            TransportResponse(500, {}, b"server error", 0.1),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=2,
            retry_delay_seconds=1.0,
            sleeper=sleeper,
        )
        response = run(adapter.chat_completion(make_request()))
        assert response.content == "ok"
        assert len(transport.calls) == 3
        assert sleeper.delays == [1.0, 2.0]

    def test_500_exhausts_retries_and_raises_last_error(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(500, {}, b"server error", 0.1),
            TransportResponse(503, {}, b"unavailable", 0.1),
            TransportResponse(
                504, {}, json.dumps({"error": {"code": "gateway_timeout"}}).encode(), 0.1,
            ),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=2,
            retry_delay_seconds=0.5,
            sleeper=sleeper,
        )
        with pytest.raises(AdapterServerError) as exc:
            run(adapter.chat_completion(make_request()))
        assert exc.value.provider_code == "gateway_timeout"
        assert len(transport.calls) == 3
        assert sleeper.delays == [0.5, 1.0]

    def test_429_uses_retry_after_header(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(429, {"retry-after": "0.3"}, b"rate limited", 0.1),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=2,
            retry_delay_seconds=10.0,
            sleeper=sleeper,
        )
        response = run(adapter.chat_completion(make_request()))
        assert response.content == "ok"
        assert len(transport.calls) == 2
        assert sleeper.delays == [0.3]

    def test_429_zero_retry_after_falls_back_to_backoff(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(429, {"retry-after": "0"}, b"rate limited", 0.1),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=2,
            retry_delay_seconds=0.5,
            sleeper=sleeper,
        )
        response = run(adapter.chat_completion(make_request()))
        assert response.content == "ok"
        assert sleeper.delays == [0.5]

    def test_408_timeout_retries(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(408, {}, b"timeout", 0.1),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=1,
            retry_delay_seconds=0.25,
            sleeper=sleeper,
        )
        response = run(adapter.chat_completion(make_request()))
        assert response.content == "ok"
        assert len(transport.calls) == 2
        assert sleeper.delays == [0.25]


class TestOpenAIAdapterTransportRetry:
    """Transport-level failures are retried when retryable."""

    def test_adapter_timeout_exception_retries(self) -> None:
        transport = FakeSequencedTransport([
            AdapterTimeoutError("connection timed out"),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=1,
            retry_delay_seconds=0.2,
            sleeper=sleeper,
        )
        response = run(adapter.chat_completion(make_request()))
        assert response.content == "ok"
        assert len(transport.calls) == 2
        assert sleeper.delays == [0.2]

    def test_generic_transport_exception_retries_then_wraps_as_connection(self) -> None:
        transport = FakeSequencedTransport([
            RuntimeError("network down"),
            RuntimeError("still down"),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=1,
            retry_delay_seconds=0.1,
            sleeper=sleeper,
        )
        with pytest.raises(AdapterConnectionError, match="still down"):
            run(adapter.chat_completion(make_request()))
        assert len(transport.calls) == 2
        assert len(sleeper.delays) == 1

    def test_zero_retries_raises_immediately(self) -> None:
        transport = FakeSequencedTransport([
            AdapterTimeoutError("connection timed out"),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(transport, max_retries=0, sleeper=sleeper)
        with pytest.raises(AdapterTimeoutError, match="connection timed out"):
            run(adapter.chat_completion(make_request()))
        assert len(transport.calls) == 1
        assert len(sleeper.delays) == 0


class TestOpenAIAdapterRetryConfiguration:
    """Retry policy parameters are validated and applied per attempt."""

    def test_negative_max_retries_rejected(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        with pytest.raises(ValueError, match="max_retries"):
            make_adapter(transport, max_retries=-1)

    def test_negative_retry_delay_rejected(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        with pytest.raises(ValueError, match="retry_delay_seconds"):
            make_adapter(transport, retry_delay_seconds=-0.1)

    def test_timeout_is_per_attempt(self) -> None:
        transport = FakeSequencedTransport([
            AdapterTimeoutError("timeout"),
            AdapterTimeoutError("timeout"),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=1,
            retry_delay_seconds=0.0,
            sleeper=sleeper,
        )
        request = make_request(timeout_seconds=7.5)
        with pytest.raises(AdapterTimeoutError):
            run(adapter.chat_completion(request))
        assert len(transport.calls) == 2
        assert all(call["timeout"] == 7.5 for call in transport.calls)

    def test_request_and_body_preserved_across_retries(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(503, {}, b"down", 0.1),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        sleeper = FakeSleeper()
        adapter = make_adapter(
            transport,
            max_retries=1,
            retry_delay_seconds=0.0,
            sleeper=sleeper,
        )
        request = make_request(
            model_id="retry-model",
            messages=(AdapterMessage(role="system", content="sys"),),
            temperature=0.3,
        )
        run(adapter.chat_completion(request))
        for call in transport.calls:
            assert call["body"]["model"] == "retry-model"
            assert call["body"]["messages"] == [{"role": "system", "content": "sys"}]
            assert call["body"]["temperature"] == 0.3
