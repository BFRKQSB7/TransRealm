"""Normalized adapter error taxonomy.

All provider-specific errors are mapped to one of these subclasses before
leaving the adapter layer. Secrets are never included in messages.
"""

from __future__ import annotations

from typing import ClassVar


class AdapterError(Exception):
    """Base class for adapter-layer errors.

    Attributes:
        category: Machine-readable error category.
        is_retryable: Whether the caller should retry this error.
        provider_code: Optional provider-specific code or HTTP status.
        retry_after_seconds: Optional server-suggested retry delay.
        safe_message: A message that is safe to log or display.
    """

    category: ClassVar[str] = "adapter_error"
    is_retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        provider_code: str | int | None = None,
        retry_after_seconds: float | None = None,
        cause: Exception | None = None,
    ) -> None:
        """Initialize a normalized adapter error.

        Args:
            message: Human-readable, secret-free message.
            provider_code: Provider code or HTTP status (never a secret).
            retry_after_seconds: Suggested retry delay if applicable.
            cause: Original exception, if any.
        """
        super().__init__(message)
        self.safe_message = message
        self.provider_code = str(provider_code) if provider_code is not None else None
        self.retry_after_seconds = retry_after_seconds
        self.cause = cause

    def __str__(self) -> str:
        parts = [self.category, self.safe_message]
        if self.provider_code is not None:
            parts.append(f"provider_code={self.provider_code}")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after={self.retry_after_seconds}")
        return " | ".join(parts)


class AdapterAuthenticationError(AdapterError):
    """Invalid or missing credentials (401/403). Not retryable."""

    category = "authentication_error"


class AdapterAuthorizationError(AdapterError):
    """Valid credentials lack permission. Not retryable."""

    category = "authorization_error"


class AdapterRateLimitError(AdapterError):
    """Rate limited by provider (429). Retryable."""

    category = "rate_limit_error"
    is_retryable = True


class AdapterServerError(AdapterError):
    """Provider server error (5xx). Retryable."""

    category = "server_error"
    is_retryable = True


class AdapterTimeoutError(AdapterError):
    """Request timed out. Retryable."""

    category = "timeout_error"
    is_retryable = True


class AdapterConnectionError(AdapterError):
    """Network or transport failure. Retryable."""

    category = "connection_error"
    is_retryable = True


class AdapterValidationError(AdapterError):
    """Invalid request parameters (400/422). Not retryable."""

    category = "validation_error"


class AdapterResponseError(AdapterError):
    """Malformed or unexpected provider response. Not retryable."""

    category = "response_error"


class AdapterCapabilityError(AdapterError):
    """Request exceeds declared model capability. Not retryable."""

    category = "capability_error"


def classify_http_error(
    status_code: int,
    message: str,
    *,
    provider_code: str | int | None = None,
    retry_after_seconds: float | None = None,
) -> AdapterError:
    """Map an HTTP status code to a normalized adapter error.

    Args:
        status_code: HTTP status code.
        message: Secret-free message.
        provider_code: Optional provider-specific code.
        retry_after_seconds: Optional retry-after hint.

    Returns:
        A normalized AdapterError subclass.
    """
    if status_code == 401:
        return AdapterAuthenticationError(
            message,
            provider_code=provider_code,
            retry_after_seconds=retry_after_seconds,
        )
    if status_code == 403:
        return AdapterAuthorizationError(
            message,
            provider_code=provider_code,
            retry_after_seconds=retry_after_seconds,
        )
    if status_code == 429:
        return AdapterRateLimitError(
            message,
            provider_code=provider_code,
            retry_after_seconds=retry_after_seconds,
        )
    if 500 <= status_code < 600:
        return AdapterServerError(
            message,
            provider_code=provider_code,
            retry_after_seconds=retry_after_seconds,
        )
    if status_code == 408:
        return AdapterTimeoutError(
            message,
            provider_code=provider_code,
            retry_after_seconds=retry_after_seconds,
        )
    if status_code in {400, 422}:
        return AdapterValidationError(
            message,
            provider_code=provider_code,
            retry_after_seconds=retry_after_seconds,
        )
    return AdapterResponseError(
        message,
        provider_code=provider_code,
        retry_after_seconds=retry_after_seconds,
    )
