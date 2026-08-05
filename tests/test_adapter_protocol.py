"""Tests for the OpenAI-compatible adapter protocol, DTOs and errors."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from transrealm.adapters.dto import (
    AdapterDtoError,
    AdapterMessage,
    AdapterRequest,
    AdapterResponse,
    AdapterUsage,
)
from transrealm.adapters.errors import (
    AdapterAuthenticationError,
    AdapterAuthorizationError,
    AdapterCapabilityError,
    AdapterConnectionError,
    AdapterRateLimitError,
    AdapterResponseError,
    AdapterServerError,
    AdapterTimeoutError,
    AdapterValidationError,
    classify_http_error,
)
from transrealm.adapters.openai_adapter import OpenAICompatibleAdapter
from transrealm.adapters.protocol import (
    CredentialResolver,
    ModelAdapter,
    Transport,
    TransportResponse,
)
from transrealm.domain.model_profile import ModelCapability


class FakeTransport:
    """In-memory transport for adapter tests."""

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


class FakeResolver:
    """In-memory credential resolver."""

    def __init__(self, secret: str | Exception) -> None:
        self.secret = secret
        self.last_reference: str | None = None

    async def resolve(self, reference: str) -> str:
        self.last_reference = reference
        if isinstance(self.secret, Exception):
            raise self.secret
        return self.secret


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
    credential_reference: str | None = None,
    resolver: CredentialResolver | None = None,
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        endpoint="https://api.example.com",
        model_id="gpt-test",
        capability=capability or make_capability(),
        credential_reference=credential_reference,
        credential_resolver=resolver,
        transport=transport,
    )


def run(coro: Any) -> Any:
    """Run a coroutine in a temporary event loop for tests."""
    return asyncio.run(coro)


class TestAdapterDto:
    """DTO construction and validation."""

    def test_message_requires_supported_role(self) -> None:
        with pytest.raises(AdapterDtoError, match="Unsupported message role"):
            AdapterMessage(role="tool", content="hi")  # type: ignore[arg-type]

    def test_message_requires_string_content(self) -> None:
        with pytest.raises(AdapterDtoError, match="content must be a string"):
            AdapterMessage(role="user", content=123)  # type: ignore[arg-type]

    def test_request_requires_model_id(self) -> None:
        with pytest.raises(AdapterDtoError, match="model_id is required"):
            AdapterRequest(model_id="", messages=(AdapterMessage(role="user", content="hi"),))

    def test_request_requires_at_least_one_message(self) -> None:
        with pytest.raises(AdapterDtoError, match="At least one message"):
            AdapterRequest(model_id="m", messages=())

    def test_request_temperature_bounds(self) -> None:
        with pytest.raises(AdapterDtoError, match="temperature"):
            AdapterRequest(
                model_id="m",
                messages=(AdapterMessage(role="user", content="hi"),),
                temperature=2.5,
            )

    def test_request_positive_max_tokens(self) -> None:
        with pytest.raises(AdapterDtoError, match="max_tokens"):
            AdapterRequest(
                model_id="m",
                messages=(AdapterMessage(role="user", content="hi"),),
                max_tokens=0,
            )

    def test_request_positive_timeout(self) -> None:
        with pytest.raises(AdapterDtoError, match="timeout_seconds"):
            AdapterRequest(
                model_id="m",
                messages=(AdapterMessage(role="user", content="hi"),),
                timeout_seconds=-1.0,
            )

    def test_usage_non_negative(self) -> None:
        with pytest.raises(AdapterDtoError, match="prompt_tokens"):
            AdapterUsage(prompt_tokens=-1, completion_tokens=0, total_tokens=0)

    def test_response_content_must_be_string(self) -> None:
        with pytest.raises(AdapterDtoError, match="content must be a string"):
            AdapterResponse(
                content=123,  # type: ignore[arg-type]
                finish_reason=None,
                usage=None,
                request_id=None,
                raw_response=None,
            )


class TestAdapterProtocol:
    """Protocol runtime checkability."""

    def test_openai_adapter_is_model_adapter(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        assert isinstance(adapter, ModelAdapter)


class TestErrorClassification:
    """HTTP status to normalized error mapping."""

    def test_401_maps_to_authentication(self) -> None:
        err = classify_http_error(401, "unauthorized")
        assert isinstance(err, AdapterAuthenticationError)
        assert not err.is_retryable

    def test_403_maps_to_authorization(self) -> None:
        err = classify_http_error(403, "forbidden")
        assert isinstance(err, AdapterAuthorizationError)
        assert not err.is_retryable

    def test_429_maps_to_rate_limit_and_retryable(self) -> None:
        err = classify_http_error(429, "rate limited", retry_after_seconds=2.0)
        assert isinstance(err, AdapterRateLimitError)
        assert err.is_retryable
        assert err.retry_after_seconds == 2.0

    def test_500_maps_to_server_error_and_retryable(self) -> None:
        err = classify_http_error(503, "unavailable")
        assert isinstance(err, AdapterServerError)
        assert err.is_retryable

    def test_408_maps_to_timeout_and_retryable(self) -> None:
        err = classify_http_error(408, "timeout")
        assert isinstance(err, AdapterTimeoutError)
        assert err.is_retryable

    def test_400_422_maps_to_validation(self) -> None:
        err = classify_http_error(422, "validation")
        assert isinstance(err, AdapterValidationError)
        assert not err.is_retryable

    def test_unexpected_status_maps_to_response_error(self) -> None:
        err = classify_http_error(418, "teapot")
        assert isinstance(err, AdapterResponseError)

    def test_error_includes_provider_code(self) -> None:
        err = classify_http_error(429, "rate", provider_code="insufficient_quota")
        assert err.provider_code == "insufficient_quota"


class TestOpenAIAdapterCapabilityContract:
    """Capability contract enforcement."""

    def test_filter_params_keeps_only_supported(self) -> None:
        cap = make_capability(params={"temperature", "top_p"})
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport, capability=cap)
        filtered = adapter.filter_params({
            "temperature": 0.3,
            "max_tokens": 256,
            "top_p": 0.9,
        })
        assert filtered == {"temperature": 0.3, "top_p": 0.9}

    def test_filter_params_returns_empty_when_none_supported(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        assert adapter.filter_params({"temperature": 0.3}) == {}

    def test_streaming_requires_capability(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            stream=True,
        )
        with pytest.raises(AdapterCapabilityError, match="Streaming"):
            run(adapter.chat_completion(request))

    def test_structured_output_requires_capability(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            structured_output=True,
        )
        with pytest.raises(AdapterCapabilityError, match="Structured output"):
            run(adapter.chat_completion(request))

    def test_max_tokens_exceeding_capability_rejected(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport, capability=make_capability(max_output_tokens=512))
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            max_tokens=1024,
        )
        with pytest.raises(AdapterCapabilityError, match="max_tokens"):
            run(adapter.chat_completion(request))


class TestOpenAIAdapterRequestMapping:
    """Request body mapping."""

    def test_request_body_contains_model_and_messages(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="custom-model",
            messages=(
                AdapterMessage(role="system", content="sys"),
                AdapterMessage(role="user", content="hello"),
            ),
            temperature=0.3,
            max_tokens=128,
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        body = transport.last_call["body"]
        assert body["model"] == "custom-model"
        assert body["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        assert body["temperature"] == 0.3
        assert body["max_tokens"] == 128

    def test_structured_output_adds_response_format(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        cap = make_capability(structured=True)
        adapter = make_adapter(transport, capability=cap)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            structured_output=True,
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["body"]["response_format"] == {"type": "json_object"}

    def test_extra_params_filtered_by_capability(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        cap = make_capability(params={"temperature"})
        adapter = make_adapter(transport, capability=cap)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            extra_params={"temperature": 0.5, "top_p": 0.9},
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        body = transport.last_call["body"]
        assert body["temperature"] == 0.5
        assert "top_p" not in body

    @pytest.mark.parametrize(
        "key, value",
        [
            ("model", "unapproved-model"),
            ("messages", [{"role": "user", "content": "unapproved prompt"}]),
            ("stream", True),
            ("response_format", {"type": "text"}),
        ],
    )
    def test_extra_params_cannot_override_request_identity(
        self,
        key: str,
        value: object,
    ) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        cap = make_capability(params={key})
        adapter = make_adapter(transport, capability=cap)
        request = AdapterRequest(
            model_id="approved-model",
            messages=(AdapterMessage(role="user", content="approved prompt"),),
            extra_params={key: value},
        )

        with pytest.raises(AdapterValidationError, match=key) as exc:
            run(adapter.chat_completion(request))

        assert "unapproved" not in str(exc.value)
        assert transport.last_call is None

    def test_timeout_passed_to_transport(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
            timeout_seconds=7.5,
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert transport.last_call["timeout"] == 7.5


class TestOpenAIAdapterResponseMapping:
    """Response parsing."""

    def test_success_response_mapped(self) -> None:
        payload = {
            "id": "resp-1",
            "choices": [{
                "message": {"role": "assistant", "content": "translated"},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps(payload).encode(), 0.2,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        response = run(adapter.chat_completion(request))
        assert response.content == "translated"
        assert response.finish_reason == "stop"
        assert response.request_id == "resp-1"
        assert response.usage is not None
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 5
        assert response.usage.total_tokens == 15
        assert response.raw_response == payload

    def test_missing_usage_allowed(self) -> None:
        payload = {
            "id": "resp-2",
            "choices": [{
                "message": {"content": "ok"},
                "finish_reason": "stop",
            }],
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
        assert response.usage is None

    def test_invalid_json_raises_response_error(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"not-json", 0.1))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError, match="invalid JSON"):
            run(adapter.chat_completion(request))

    def test_missing_choices_raises_response_error(self) -> None:
        transport = FakeTransport(response=TransportResponse(
            200, {}, json.dumps({}).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError, match="missing choices"):
            run(adapter.chat_completion(request))


class TestOpenAIAdapterErrorMapping:
    """HTTP error responses mapped to normalized errors."""

    def test_401_maps_to_authentication(self) -> None:
        payload = {"error": {"code": "invalid_api_key"}}
        transport = FakeTransport(response=TransportResponse(
            401, {}, json.dumps(payload).encode(), 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterAuthenticationError) as exc:
            run(adapter.chat_completion(request))
        assert exc.value.provider_code == "invalid_api_key"
        assert "Authorization" not in str(exc.value)

    def test_429_extracts_retry_after(self) -> None:
        transport = FakeTransport(response=TransportResponse(
            429, {"retry-after": "3"}, b"rate limited", 0.1,
        ))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterRateLimitError) as exc:
            run(adapter.chat_completion(request))
        assert exc.value.retry_after_seconds == 3.0

    def test_transport_exception_maps_to_connection(self) -> None:
        transport = FakeTransport(response=RuntimeError("network down"))
        adapter = make_adapter(transport)
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterConnectionError, match="network down"):
            run(adapter.chat_completion(request))


class TestOpenAIAdapterCredentialBoundary:
    """Credential handling must not leak secrets."""

    def test_credential_resolver_used_for_authorization(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        resolver = FakeResolver(secret="sk-secret")
        adapter = make_adapter(
            transport,
            credential_reference="env:API_KEY",
            resolver=resolver,
        )
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert resolver.last_reference == "env:API_KEY"
        assert transport.last_call is not None
        assert transport.last_call["headers"]["Authorization"] == "Bearer sk-secret"

    def test_credential_resolution_failure_maps_to_authentication(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        resolver = FakeResolver(secret=RuntimeError("not found"))
        adapter = make_adapter(
            transport,
            credential_reference="env:API_KEY",
            resolver=resolver,
        )
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterAuthenticationError, match="credential"):
            run(adapter.chat_completion(request))

    def test_no_credential_when_resolver_missing(self) -> None:
        transport = FakeTransport(response=TransportResponse(200, {}, b"{}", 0.1))
        adapter = make_adapter(
            transport,
            credential_reference="env:API_KEY",
            resolver=None,
        )
        request = AdapterRequest(
            model_id="m",
            messages=(AdapterMessage(role="user", content="hi"),),
        )
        with pytest.raises(AdapterResponseError):
            run(adapter.chat_completion(request))
        assert transport.last_call is not None
        assert "Authorization" not in transport.last_call["headers"]
