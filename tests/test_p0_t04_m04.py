"""P0-T04-M04: capability degradation and credential resolver boundary.

These tests verify the adapter's capability-aware fallback policy and the
strict boundary around credential resolution: secrets must not leak into
errors or test-visible strings, and the resolver is only invoked when both a
reference and a resolver are provided.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterMessage, AdapterRequest
from transrealm.adapters.errors import (
    AdapterAuthenticationError,
    AdapterCapabilityError,
    AdapterValidationError,
)
from transrealm.adapters.openai_adapter import DegradationPolicy, OpenAICompatibleAdapter
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


class FakeResolver:
    """In-memory credential resolver."""

    def __init__(self, secret: str | Exception) -> None:
        self.secret = secret
        self.calls: list[str] = []

    async def resolve(self, reference: str) -> str:
        self.calls.append(reference)
        if isinstance(self.secret, Exception):
            raise self.secret
        return self.secret


def make_capability(
    *,
    context_window: int = 4096,
    max_output_tokens: int = 512,
    streaming: bool = True,
    structured: bool = True,
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


def make_error_response(
    status: int,
    *,
    provider_code: str | None = "unsupported_parameter",
    body_text: str | None = None,
) -> TransportResponse:
    if body_text is not None:
        return TransportResponse(status, {}, body_text.encode(), 0.1)
    payload: dict[str, object] = {"error": {}}
    if provider_code is not None:
        payload["error"] = {"code": provider_code}
    return TransportResponse(status, {}, json.dumps(payload).encode(), 0.1)


def make_adapter(
    transport: Any,
    capability: ModelCapability | None = None,
    credential_reference: str | None = None,
    resolver: FakeResolver | None = None,
    degradation_policy: DegradationPolicy | None = None,
    max_retries: int = 0,
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        endpoint="https://api.example.com",
        model_id="gpt-test",
        capability=capability or make_capability(),
        credential_reference=credential_reference,
        credential_resolver=resolver,
        transport=transport,
        degradation_policy=degradation_policy,
        max_retries=max_retries,
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


class TestCapabilityDegradation:
    """Adapter degrades structured output / streaming on capability errors."""

    def test_structured_output_degrades_to_plain_text(self) -> None:
        transport = FakeSequencedTransport([
            make_error_response(400, provider_code="unsupported_parameter"),
            TransportResponse(200, {}, json.dumps(make_success_payload("plain")).encode(), 0.1),
        ])
        adapter = make_adapter(
            transport,
            degradation_policy=DegradationPolicy(
                fallback_on_structured_output_error=True,
            ),
        )
        request = make_request(structured_output=True)
        response = run(adapter.chat_completion(request))

        assert response.content == "plain"
        assert len(transport.calls) == 2
        assert transport.calls[0]["body"].get("response_format") == {"type": "json_object"}
        assert "response_format" not in transport.calls[1]["body"]

    def test_streaming_degrades_to_non_streaming(self) -> None:
        transport = FakeSequencedTransport([
            make_error_response(400, provider_code="unsupported_parameter"),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        adapter = make_adapter(
            transport,
            degradation_policy=DegradationPolicy(fallback_on_streaming_error=True),
        )
        request = make_request(stream=True)
        response = run(adapter.chat_completion(request))

        assert response.content == "ok"
        assert len(transport.calls) == 2
        assert transport.calls[0]["body"].get("stream") is True
        assert "stream" not in transport.calls[1]["body"]

    def test_no_degradation_policy_raises_original_error(self) -> None:
        transport = FakeSequencedTransport([
            make_error_response(400, provider_code="unsupported_parameter"),
        ])
        adapter = make_adapter(transport)
        request = make_request(structured_output=True)
        with pytest.raises(AdapterValidationError) as exc:
            run(adapter.chat_completion(request))
        assert exc.value.provider_code == "unsupported_parameter"
        assert len(transport.calls) == 1

    def test_non_capability_400_does_not_degrade(self) -> None:
        transport = FakeSequencedTransport([
            make_error_response(400, provider_code="invalid_request_error"),
        ])
        adapter = make_adapter(
            transport,
            degradation_policy=DegradationPolicy(
                fallback_on_structured_output_error=True,
            ),
        )
        request = make_request(structured_output=True)
        with pytest.raises(AdapterValidationError) as exc:
            run(adapter.chat_completion(request))
        assert exc.value.provider_code == "invalid_request_error"
        assert len(transport.calls) == 1

    def test_degraded_request_keeps_other_parameters(self) -> None:
        transport = FakeSequencedTransport([
            make_error_response(400, provider_code="unsupported_parameter"),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        adapter = make_adapter(
            transport,
            degradation_policy=DegradationPolicy(
                fallback_on_structured_output_error=True,
            ),
        )
        request = make_request(
            structured_output=True,
            temperature=0.7,
            max_tokens=128,
        )
        run(adapter.chat_completion(request))

        for call in transport.calls:
            assert call["body"]["temperature"] == 0.7
            assert call["body"]["max_tokens"] == 128
        assert transport.calls[1]["body"].get("response_format") is None

    def test_degradation_retry_uses_transport_retry_policy(self) -> None:
        transport = FakeSequencedTransport([
            make_error_response(500),
            make_error_response(400, provider_code="unsupported_parameter"),
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        adapter = make_adapter(
            transport,
            degradation_policy=DegradationPolicy(
                fallback_on_structured_output_error=True,
            ),
            max_retries=1,
        )
        request = make_request(structured_output=True)
        response = run(adapter.chat_completion(request))

        assert response.content == "ok"
        assert len(transport.calls) == 3

    def test_degradation_failure_raises_last_error(self) -> None:
        transport = FakeSequencedTransport([
            make_error_response(400, provider_code="unsupported_parameter"),
            make_error_response(400, provider_code="unsupported_parameter"),
        ])
        adapter = make_adapter(
            transport,
            degradation_policy=DegradationPolicy(
                fallback_on_structured_output_error=True,
            ),
        )
        request = make_request(structured_output=True)
        with pytest.raises(AdapterValidationError) as exc:
            run(adapter.chat_completion(request))
        assert exc.value.provider_code == "unsupported_parameter"
        assert len(transport.calls) == 2
        assert "response_format" not in transport.calls[1]["body"]

    def test_declared_capability_still_blocks_unsupported_request(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        cap = make_capability(streaming=False, structured=False)
        adapter = make_adapter(
            transport,
            capability=cap,
            degradation_policy=DegradationPolicy(
                fallback_on_structured_output_error=True,
                fallback_on_streaming_error=True,
            ),
        )
        with pytest.raises(AdapterCapabilityError, match="Streaming"):
            run(adapter.chat_completion(make_request(stream=True)))
        assert len(transport.calls) == 0


class TestCredentialResolverBoundary:
    """Credential resolver is invoked only when needed and failures stay bounded."""

    def test_resolver_not_called_without_reference(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        resolver = FakeResolver(secret="sk-secret")
        adapter = make_adapter(
            transport,
            resolver=resolver,
            credential_reference=None,
        )
        run(adapter.chat_completion(make_request()))
        assert len(resolver.calls) == 0
        assert "Authorization" not in transport.calls[0]["headers"]

    def test_resolver_not_called_without_resolver(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        adapter = make_adapter(
            transport,
            resolver=None,
            credential_reference="env:API_KEY",
        )
        run(adapter.chat_completion(make_request()))
        assert "Authorization" not in transport.calls[0]["headers"]

    def test_resolver_called_once_when_reference_and_resolver_present(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        resolver = FakeResolver(secret="sk-secret")
        adapter = make_adapter(
            transport,
            resolver=resolver,
            credential_reference="env:API_KEY",
        )
        run(adapter.chat_completion(make_request()))
        assert resolver.calls == ["env:API_KEY"]
        assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-secret"

    def test_secret_does_not_leak_into_error_string(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(401, {}, b"unauthorized", 0.1),
        ])
        resolver = FakeResolver(secret="sk-leaked")
        adapter = make_adapter(
            transport,
            resolver=resolver,
            credential_reference="env:API_KEY",
        )
        with pytest.raises(AdapterAuthenticationError) as exc:
            run(adapter.chat_completion(make_request()))
        error_text = str(exc.value)
        assert "sk-leaked" not in error_text
        assert "Authorization" not in error_text

    def test_credential_resolution_failure_does_not_leak_secret(self) -> None:
        transport = FakeSequencedTransport([
            TransportResponse(200, {}, json.dumps(make_success_payload()).encode(), 0.1),
        ])
        resolver = FakeResolver(secret=RuntimeError("sk-bad"))
        adapter = make_adapter(
            transport,
            resolver=resolver,
            credential_reference="env:API_KEY",
        )
        with pytest.raises(AdapterAuthenticationError) as exc:
            run(adapter.chat_completion(make_request()))
        error_text = str(exc.value)
        assert "sk-bad" not in error_text
