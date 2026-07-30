"""Adapter data transfer objects.

These DTOs are transport-agnostic and used by the ModelAdapter protocol.
They carry only data; no UI or persistence concerns are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


class AdapterDtoError(ValueError):
    """Invalid adapter DTO construction."""


@dataclass(frozen=True)
class AdapterMessage:
    """A single message in an adapter request."""

    role: Literal["system", "user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        """Validate the message."""
        if self.role not in {"system", "user", "assistant"}:
            raise AdapterDtoError(f"Unsupported message role: {self.role!r}.")
        if not isinstance(self.content, str):
            raise AdapterDtoError("Message content must be a string.")


@dataclass(frozen=True)
class AdapterRequest:
    """A normalized request to a model adapter."""

    model_id: str
    messages: tuple[AdapterMessage, ...]
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    stream: bool = False
    structured_output: bool = False
    extra_params: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the request."""
        if not self.model_id or not self.model_id.strip():
            raise AdapterDtoError("model_id is required.")
        if not self.messages:
            raise AdapterDtoError("At least one message is required.")
        if self.temperature is not None and not 0.0 <= self.temperature <= 2.0:
            raise AdapterDtoError(
                f"temperature must be in [0.0, 2.0]: {self.temperature}",
            )
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise AdapterDtoError(
                f"max_tokens must be positive: {self.max_tokens}",
            )
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise AdapterDtoError(
                f"timeout_seconds must be positive: {self.timeout_seconds}",
            )


@dataclass(frozen=True)
class AdapterUsage:
    """Token usage reported by a provider."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        """Validate usage counts."""
        if self.prompt_tokens < 0:
            raise AdapterDtoError(
                f"prompt_tokens must be non-negative: {self.prompt_tokens}",
            )
        if self.completion_tokens < 0:
            raise AdapterDtoError(
                f"completion_tokens must be non-negative: {self.completion_tokens}",
            )
        if self.total_tokens < 0:
            raise AdapterDtoError(
                f"total_tokens must be non-negative: {self.total_tokens}",
            )


@dataclass(frozen=True)
class AdapterResponse:
    """A normalized response from a model adapter."""

    content: str
    finish_reason: str | None
    usage: AdapterUsage | None
    request_id: str | None
    raw_response: dict[str, object] | None

    def __post_init__(self) -> None:
        """Validate the response."""
        if not isinstance(self.content, str):
            raise AdapterDtoError("Response content must be a string.")
