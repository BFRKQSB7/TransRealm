"""Provider Connection domain model.

A Provider Connection stores non-sensitive connection configuration only.
Secrets (API keys, tokens) are never persisted; only an opaque credential
reference such as ``env:VAR_NAME`` or ``wincred:TARGET_NAME`` is stored.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar


class ProviderConnectionError(ValueError):
    """Invalid provider connection configuration."""


@dataclass
class ProviderConnection:
    """Non-sensitive configuration for connecting to a model provider."""

    id: int | None
    name: str
    provider_type: str
    endpoint: str
    timeout_seconds: int
    max_retries: int
    retry_delay_seconds: float
    credential_reference: str | None
    created_at: datetime | None
    updated_at: datetime | None

    _SUPPORTED_PROVIDER_TYPES: ClassVar[set[str]] = {
        "openai-compatible",
        "llama.cpp",
        "ollama",
    }

    @classmethod
    def create(
        cls,
        *,
        name: str,
        provider_type: str,
        endpoint: str,
        timeout_seconds: int = 30,
        max_retries: int = 0,
        retry_delay_seconds: float = 0.0,
        credential_reference: str | None = None,
    ) -> ProviderConnection:
        """Create and validate a new, unsaved ProviderConnection."""
        instance = cls(
            id=None,
            name=name,
            provider_type=provider_type,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            credential_reference=credential_reference,
            created_at=None,
            updated_at=None,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate all fields and raise ProviderConnectionError on failure."""
        if not self.name or not self.name.strip():
            raise ProviderConnectionError("Connection name is required.")

        if self.provider_type not in self._SUPPORTED_PROVIDER_TYPES:
            raise ProviderConnectionError(
                f"Unsupported provider type: {self.provider_type!r}. "
                f"Supported: {', '.join(sorted(self._SUPPORTED_PROVIDER_TYPES))}",
            )

        parsed = urllib.parse.urlparse(self.endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ProviderConnectionError("Endpoint must be an HTTP/HTTPS URL without userinfo.")
        try:
            parsed.port
        except ValueError as exc:
            raise ProviderConnectionError("Endpoint port is invalid.") from exc

        if self.timeout_seconds <= 0:
            raise ProviderConnectionError(
                f"timeout_seconds must be positive: {self.timeout_seconds}",
            )

        if self.max_retries < 0:
            raise ProviderConnectionError(
                f"max_retries must be non-negative: {self.max_retries}",
            )

        if self.retry_delay_seconds < 0:
            raise ProviderConnectionError(
                f"retry_delay_seconds must be non-negative: {self.retry_delay_seconds}",
            )

        if self.credential_reference is not None:
            self._validate_credential_reference(self.credential_reference)

    @staticmethod
    def _validate_credential_reference(reference: str) -> None:
        """Ensure the credential reference is a pointer, not a secret value."""
        if not reference:
            raise ProviderConnectionError(
                "credential_reference cannot be empty; use None to skip.",
            )
        if reference.startswith("env:"):
            var_name = reference[4:]
            if not var_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", var_name):
                raise ProviderConnectionError(
                    f"Invalid environment variable reference: {reference!r}",
                )
            return
        if reference.startswith("wincred:"):
            target = reference[8:]
            if not target or "/" not in target:
                raise ProviderConnectionError(
                    f"Invalid Windows Credential reference: {reference!r}",
                )
            return
        raise ProviderConnectionError(
            f"credential_reference must use 'env:' or 'wincred:' scheme: {reference!r}",
        )

    def with_updated_fields(
        self,
        *,
        name: str | None = None,
        provider_type: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        credential_reference: str | None = None,
    ) -> ProviderConnection:
        """Return a copy with selected fields replaced and re-validated."""
        updated = ProviderConnection(
            id=self.id,
            name=name if name is not None else self.name,
            provider_type=provider_type if provider_type is not None else self.provider_type,
            endpoint=endpoint if endpoint is not None else self.endpoint,
            timeout_seconds=timeout_seconds
            if timeout_seconds is not None
            else self.timeout_seconds,
            max_retries=max_retries if max_retries is not None else self.max_retries,
            retry_delay_seconds=retry_delay_seconds
            if retry_delay_seconds is not None
            else self.retry_delay_seconds,
            credential_reference=credential_reference
            if credential_reference is not None
            else self.credential_reference,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        updated.validate()
        return updated
