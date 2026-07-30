"""P0-T04-M02: OpenAI-compatible adapter success request/response mapping.

These tests verify the successful-path conversion between normalized
:class:`~transrealm.adapters.dto.AdapterRequest`/`AdapterResponse` and the
OpenAI ``/v1/chat/completions`` wire format using a fake in-memory transport.
No real network calls are made.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from transrealm.adapters.dto import (
    AdapterMessage,
    AdapterRequest,
)
from transrealm.adapters.errors import AdapterResponseError
from transrealm.adapters.openai_adapter import OpenAICompatibleAdapter
from transrealm.adapters.protocol import Transport, TransportResponse
from transrealm.domain.model_profile import ModelCapability


class FakeTransport:
    """In-memory transport for success-path adapter tests."""

    def __init__(self, response: TransportResponse | Exception) -> None:
        self.response = response
        self.last_call: dict[str, Any] | None = None

    async def post(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> TransportResponse:
        self.last_call = {
            "path": path,
            "headers": headers,
            "body": body,
            "timeout": timeout,
        }
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


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


def make_adapter(
    transport: Transport,
    capability: ModelCapability | None = None,
    model_id: str = "gpt-test",
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        endpoint="https://api.example.com",
        model_id=model_id,
        capability=capability or make_capability(),
        transport=transport,
    )


def run(coro: Any) -> Any:
    """Run a coroutine in a temporary event loop for tests."""
    return asyncio.run(coro)


class TestOpenAIAdapterEndpointAndModel:
    """Endpoint path and model identity mapping."""

    def test_uses_chat_completions_path(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["path"] == "/v1/chat/completions"

    def test_request_model_id_sent_in_body(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport, model_id="adapter-model")
        request = AdapterRequest(
            model_id="request-model",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["body"]["model"] == "request-model"


class TestOpenAIAdapterParameterMapping:
    """Successful request body construction."""

    def test_omits_none_parameters(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        body = transport.last_call["body"]
        assert "temperature" not in body
        assert "max_tokens" not in body
        assert "response_format" not in body
        assert "stream" not in body

    def test_maps_temperature_and_max_tokens(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            temperature=0.7,
            max_tokens=256,
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        body = transport.last_call["body"]
        assert body["temperature"] == 0.7
        assert body["max_tokens"] == 256

    def test_maps_all_message_roles(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(
                AdapterMessage(role="system", content="sys"),
                AdapterMessage(role="user", content="hello"),
                AdapterMessage(role="assistant", content="hi there"),
            ),
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["body"]["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

    def test_supported_extra_params_are_included(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        cap = make_capability(params={"top_p", "presence_penalty", "frequency_penalty"})
        adapter = make_adapter(transport, capability=cap)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            extra_params={
                "top_p": 0.9,
                "presence_penalty": 0.5,
                "frequency_penalty": -0.2,
                "unsupported": "drop",
            },
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        body = transport.last_call["body"]
        assert body["top_p"] == 0.9
        assert body["presence_penalty"] == 0.5
        assert body["frequency_penalty"] == -0.2
        assert "unsupported" not in body

    def test_extra_params_can_override_defaults_when_supported(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        cap = make_capability(params={"temperature", "max_tokens"})
        adapter = make_adapter(transport, capability=cap)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            temperature=0.3,
            max_tokens=100,
            extra_params={"temperature": 0.9, "max_tokens": 200},
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        body = transport.last_call["body"]
        assert body["temperature"] == 0.9
        assert body["max_tokens"] == 200

    def test_stream_param_mapped_when_supported(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        cap = make_capability(streaming=True)
        adapter = make_adapter(transport, capability=cap)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            stream=True,
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["body"]["stream"] is True

    def test_default_timeout_used_when_request_has_none(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = OpenAICompatibleAdapter(
            endpoint="https://api.example.com",
            model_id="m",
            capability=make_capability(),
            transport=transport,
            timeout_seconds=15.0,
        )
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["timeout"] == 15.0

    def test_request_timeout_overrides_default(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = OpenAICompatibleAdapter(
            endpoint="https://api.example.com",
            model_id="m",
            capability=make_capability(),
            transport=transport,
            timeout_seconds=15.0,
        )
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            timeout_seconds=42.0,
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["timeout"] == 42.0


class TestOpenAIAdapterResponseMapping:
    """Successful response parsing and normalization."""

    def test_maps_finish_reason_and_request_id(self) -> None:
        payload = {
            "id": "chatcmpl-123",
            "choices": [{
                "message": {"role": "assistant", "content": "done"},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
            },
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.content == "done"
        assert response.finish_reason == "stop"
        assert response.request_id == "chatcmpl-123"

    def test_finish_reason_length_mapped(self) -> None:
        payload = {
            "id": "r",
            "choices": [{"message": {"content": "trunc"}, "finish_reason": "length"}],
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.finish_reason == "length"

    def test_missing_finish_reason_defaults_to_none(self) -> None:
        payload = {
            "id": "r",
            "choices": [{"message": {"content": "ok"}}],
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.finish_reason is None

    def test_missing_request_id_defaults_to_none(self) -> None:
        payload = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.request_id is None

    def test_empty_content_is_allowed(self) -> None:
        payload = {
            "id": "r",
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.content == ""

    def test_multiple_choices_use_first(self) -> None:
        payload = {
            "id": "r",
            "choices": [
                {"message": {"content": "first"}, "finish_reason": "stop"},
                {"message": {"content": "second"}, "finish_reason": "length"},
            ],
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.content == "first"
        assert response.finish_reason == "stop"

    def test_usage_inferred_when_total_missing(self) -> None:
        payload = {
            "id": "r",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7},
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.usage is not None
        assert response.usage.prompt_tokens == 5
        assert response.usage.completion_tokens == 7
        assert response.usage.total_tokens == 12

    def test_zero_usage_allowed(self) -> None:
        payload = {
            "id": "r",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.usage is not None
        assert response.usage.total_tokens == 0

    def test_raw_response_preserves_extra_fields(self) -> None:
        payload = {
            "id": "r",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-test",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.raw_response == payload

    def test_non_integer_usage_raises_response_error(self) -> None:
        payload = {
            "id": "r",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": "abc", "completion_tokens": 0},
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError, match="usage"):
            run(adapter.chat_completion(request))

    def test_negative_usage_raises_response_error(self) -> None:
        payload = {
            "id": "r",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": -1, "completion_tokens": 0, "total_tokens": 0},
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError, match="usage"):
            run(adapter.chat_completion(request))
