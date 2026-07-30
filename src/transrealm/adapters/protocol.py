"""Model Adapter protocol and transport abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from transrealm.adapters.dto import AdapterRequest, AdapterResponse
from transrealm.domain.model_profile import ModelCapability


@runtime_checkable
class CredentialResolver(Protocol):
    """Resolves an opaque credential reference to a secret value."""

    async def resolve(self, reference: str) -> str:
        """Return the secret identified by ``reference``.

        Raises:
            AdapterError: if the reference cannot be resolved.
        """
        ...


@dataclass(frozen=True)
class TransportResponse:
    """Raw transport response used by the adapter protocol."""

    status_code: int
    headers: dict[str, str]
    body: bytes
    elapsed_seconds: float


@runtime_checkable
class Transport(Protocol):
    """HTTP transport abstraction for adapter implementations."""

    async def post(
        self,
        path: str,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> TransportResponse:
        """POST ``body`` as JSON to ``path`` and return the raw response."""
        ...


@runtime_checkable
class ModelAdapter(Protocol):
    """Provider-neutral adapter contract."""

    async def chat_completion(self, request: AdapterRequest) -> AdapterResponse:
        """Execute a chat completion request and return a normalized response."""
        ...

    def get_capabilities(self) -> ModelCapability:
        """Return the runtime capability contract for this adapter."""
        ...

    def filter_params(self, params: dict[str, object]) -> dict[str, object]:
        """Return only the parameters supported by the declared capability."""
        ...
