"""OpenAI-compatible model adapter.

This adapter maps normalized :mod:`transrealm.adapters.dto` requests to the
OpenAI chat completions endpoint and maps responses back to normalized DTOs.
It does not contain persistence or UI code.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from transrealm.adapters.dto import (
    AdapterDtoError,
    AdapterRequest,
    AdapterResponse,
    AdapterUsage,
)
from transrealm.adapters.errors import (
    AdapterAuthenticationError,
    AdapterCapabilityError,
    AdapterConnectionError,
    AdapterError,
    AdapterResponseError,
    AdapterValidationError,
    classify_http_error,
)
from transrealm.adapters.protocol import CredentialResolver, Transport
from transrealm.domain.model_profile import ModelCapability


@dataclass(frozen=True)
class DegradationPolicy:
    """Describes how to degrade a request when the provider rejects a
    capability-dependent parameter.

    This is a minimal Phase 0 policy: the adapter can retry without the
    unsupported structured-output or streaming flag when the provider returns
    a capability-related 400 error.
    """

    fallback_on_structured_output_error: bool = False
    fallback_on_streaming_error: bool = False

    def is_empty(self) -> bool:
        """Return True when no degradation is enabled."""
        return not (
            self.fallback_on_structured_output_error
            or self.fallback_on_streaming_error
        )


class OpenAICompatibleAdapter:
    """Adapter for OpenAI-compatible HTTP endpoints.

    The adapter expects a :class:`~transrealm.adapters.protocol.Transport`
    and an optional :class:`~transrealm.adapters.protocol.CredentialResolver`.
    Secrets are only used to build the ``Authorization`` header and are never
    logged or stored by the adapter.
    """

    API_PATH = "/v1/chat/completions"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        capability: ModelCapability,
        credential_reference: str | None = None,
        credential_resolver: CredentialResolver | None = None,
        transport: Transport,
        timeout_seconds: float = 30.0,
        max_retries: int = 0,
        retry_delay_seconds: float = 0.0,
        degradation_policy: DegradationPolicy | None = None,
        _sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize an OpenAI-compatible adapter.

        Args:
            endpoint: Base URL of the provider endpoint.
            model_id: Model identifier sent to the provider.
            capability: Declared capability contract.
            credential_reference: Optional opaque credential reference.
            credential_resolver: Optional resolver for the credential reference.
            transport: HTTP transport implementing the protocol.
            timeout_seconds: Default request timeout.
            max_retries: Maximum retry attempts for retryable errors.
            retry_delay_seconds: Base delay between retries in seconds.
            degradation_policy: Optional policy for retrying structured-output
                or streaming requests without the unsupported flag.
            _sleeper: Optional async sleep function for tests; defaults to
                ``asyncio.sleep``.
        """
        if max_retries < 0:
            raise ValueError(f"max_retries must be non-negative: {max_retries}")
        if retry_delay_seconds < 0:
            raise ValueError(
                f"retry_delay_seconds must be non-negative: {retry_delay_seconds}",
            )
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._capability = capability
        self._credential_reference = credential_reference
        self._credential_resolver = credential_resolver
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._degradation_policy = degradation_policy or DegradationPolicy()
        self._sleeper = _sleeper or asyncio.sleep

    def get_capabilities(self) -> ModelCapability:
        """Return the declared capability contract."""
        return self._capability

    def filter_params(self, params: dict[str, object]) -> dict[str, object]:
        """Return only the parameters supported by the capability."""
        supported = self._capability.supported_parameters
        if not supported:
            return {}
        return {k: v for k, v in params.items() if k in supported}

    async def chat_completion(self, request: AdapterRequest) -> AdapterResponse:
        """Execute a chat completion request with transport retry and optional
        capability degradation.

        Retryable transport errors are retried up to ``max_retries`` times with
        exponential backoff. If the provider rejects a capability-dependent
        parameter (structured output or streaming) and a degradation policy is
        configured, the adapter retries once without the unsupported flag.

        Raises:
            AdapterError: On transport, capability, or response errors.
        """
        self._validate_request(request)

        try:
            return await self._execute_with_transport_retry(request)
        except AdapterValidationError as exc:
            degraded = self._degraded_request(request, exc)
            if degraded is None:
                raise
            return await self._execute_with_transport_retry(degraded)

    async def _execute_with_transport_retry(
        self,
        request: AdapterRequest,
    ) -> AdapterResponse:
        """Execute a single request variant with limited transport retries."""
        body = self._build_body(request)
        headers = await self._build_headers()
        timeout = request.timeout_seconds or self._timeout_seconds

        last_error: AdapterError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                raw = await self._transport.post(self.API_PATH, headers, body, timeout)
            except AdapterError as exc:
                if not exc.is_retryable or attempt == self._max_retries:
                    raise
                last_error = exc
            except Exception as exc:
                mapped = AdapterConnectionError(
                    f"Transport failed: {type(exc).__name__}: {exc}",
                    cause=exc,
                )
                if attempt == self._max_retries:
                    raise mapped
                last_error = mapped
            else:
                if raw.status_code == 200:
                    return self._parse_success_response(raw.body)

                provider_code = self._extract_provider_code(raw.body)
                err = classify_http_error(
                    raw.status_code,
                    f"Provider returned HTTP {raw.status_code}",
                    provider_code=provider_code,
                    retry_after_seconds=self._parse_retry_after(raw.headers),
                )
                if not err.is_retryable or attempt == self._max_retries:
                    raise err
                last_error = err

            assert last_error is not None
            await self._sleeper(self._compute_delay(last_error, attempt))

        if last_error is not None:
            raise last_error
        raise AdapterConnectionError("Exhausted retries without a recorded error.")

    def _validate_request(self, request: AdapterRequest) -> None:
        """Ensure the request fits within the declared capability."""
        if request.stream and not self._capability.supports_streaming:
            raise AdapterCapabilityError(
                "Streaming is not supported by this model capability.",
            )
        if request.structured_output and not self._capability.supports_structured_output:
            raise AdapterCapabilityError(
                "Structured output is not supported by this model capability.",
            )
        if request.max_tokens is not None:
            if request.max_tokens > self._capability.max_output_tokens:
                raise AdapterCapabilityError(
                    f"max_tokens {request.max_tokens} exceeds capability "
                    f"{self._capability.max_output_tokens}.",
                )

    def _build_body(self, request: AdapterRequest) -> dict[str, object]:
        """Build the OpenAI chat completions request body."""
        body: dict[str, object] = {
            "model": request.model_id,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.structured_output:
            body["response_format"] = {"type": "json_object"}
        if request.stream:
            body["stream"] = True

        filtered = self.filter_params(request.extra_params)
        body.update(filtered)
        return body

    async def _build_headers(self) -> dict[str, str]:
        """Build request headers, resolving credentials when needed."""
        headers = {"Content-Type": "application/json"}
        if self._credential_resolver is None or self._credential_reference is None:
            return headers
        try:
            token = await self._credential_resolver.resolve(self._credential_reference)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterAuthenticationError(
                "Failed to resolve credential reference.",
                cause=exc,
            ) from exc
        headers["Authorization"] = f"Bearer {token}"
        return headers

    def _parse_success_response(self, body: bytes) -> AdapterResponse:
        """Map a 200 OK response body to a normalized AdapterResponse."""
        try:
            data: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AdapterResponseError(
                "Provider returned invalid JSON.",
                cause=exc,
            ) from exc

        if not isinstance(data, dict):
            raise AdapterResponseError("Provider response root must be a JSON object.")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AdapterResponseError("Provider response missing choices.")

        first = choices[0]
        if not isinstance(first, dict):
            raise AdapterResponseError("Provider choice must be a JSON object.")

        message = first.get("message")
        if not isinstance(message, dict):
            raise AdapterResponseError("Provider choice missing message object.")

        content = message.get("content")
        if not isinstance(content, str):
            raise AdapterResponseError("Provider message content must be a string.")

        finish_reason = first.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise AdapterResponseError("finish_reason must be a string or null.")

        usage = self._parse_usage(data.get("usage"))
        request_id = data.get("id")
        if request_id is not None and not isinstance(request_id, str):
            raise AdapterResponseError("id must be a string or null.")

        return AdapterResponse(
            content=content,
            finish_reason=finish_reason,
            usage=usage,
            request_id=request_id,
            raw_response=data,
        )

    def _parse_usage(self, usage: object) -> AdapterUsage | None:
        """Map the usage object to AdapterUsage."""
        if usage is None:
            return None
        if not isinstance(usage, dict):
            raise AdapterResponseError("usage must be a JSON object or null.")
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens")
        try:
            prompt_int = int(prompt)
            completion_int = int(completion)
            if total is None:
                total_int = prompt_int + completion_int
            else:
                total_int = int(total)
            return AdapterUsage(
                prompt_tokens=prompt_int,
                completion_tokens=completion_int,
                total_tokens=total_int,
            )
        except (TypeError, ValueError) as exc:
            raise AdapterResponseError(
                "usage token counts must be integers.",
                cause=exc,
            ) from exc
        except AdapterDtoError as exc:
            raise AdapterResponseError(
                "usage token counts are invalid.",
                cause=exc,
            ) from exc

    def _extract_provider_code(self, body: bytes) -> str | None:
        """Try to extract a provider error code from an error response body."""
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        error = data.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, (str, int)):
                return str(code)
        return None

    def _parse_retry_after(self, headers: dict[str, str]) -> float | None:
        """Parse a Retry-After header value, if present."""
        value = headers.get("retry-after") or headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _compute_delay(self, error: AdapterError, attempt: int) -> float:
        """Return the delay before the next retry attempt.

        A positive server-provided ``retry_after_seconds`` value takes
        precedence. Otherwise, use exponential backoff based on the
        configured base delay.
        """
        if error.retry_after_seconds is not None and error.retry_after_seconds > 0:
            return error.retry_after_seconds
        return self._retry_delay_seconds * float(2 ** attempt)

    def _degraded_request(
        self,
        request: AdapterRequest,
        error: AdapterValidationError,
    ) -> AdapterRequest | None:
        """Return a degraded request if the error triggers a fallback policy."""
        if self._degradation_policy.is_empty():
            return None
        feature = self._is_degradation_trigger(error, request)
        if feature == "structured_output":
            return self._clone_request_without_feature(
                request,
                disable_structured_output=True,
            )
        if feature == "stream":
            return self._clone_request_without_feature(
                request,
                disable_stream=True,
            )
        return None

    def _is_degradation_trigger(
        self,
        error: AdapterValidationError,
        request: AdapterRequest,
    ) -> str | None:
        """Detect a provider-side capability rejection that allows degradation.

        The provider must indicate that a parameter is unsupported. Plain
        validation errors (e.g. invalid temperature) are not degradation
        triggers.
        """
        if error.provider_code not in {
            "unsupported_parameter",
            "unsupported_value",
            "invalid_type",
        }:
            return None
        if (
            request.structured_output
            and self._degradation_policy.fallback_on_structured_output_error
        ):
            return "structured_output"
        if request.stream and self._degradation_policy.fallback_on_streaming_error:
            return "stream"
        return None

    def _clone_request_without_feature(
        self,
        request: AdapterRequest,
        *,
        disable_structured_output: bool = False,
        disable_stream: bool = False,
    ) -> AdapterRequest:
        """Return a copy of ``request`` with selected capability flags disabled."""
        return AdapterRequest(
            model_id=request.model_id,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            timeout_seconds=request.timeout_seconds,
            stream=False if disable_stream else request.stream,
            structured_output=False if disable_structured_output else request.structured_output,
            extra_params=request.extra_params,
        )
