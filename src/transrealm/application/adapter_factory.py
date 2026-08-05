"""Compose persisted connection/profile configuration into a ModelAdapter.

The adapter layer stays transport- and persistence-agnostic; this factory is
the one place that maps a persisted :class:`ProviderConnection` and
:class:`ModelProfile` onto a concrete :class:`OpenAICompatibleAdapter` with a
real transport and the right credential resolver. It is a pure function and
owns no state.
"""

from __future__ import annotations

from transrealm.adapters.credential_resolvers import build_resolver
from transrealm.adapters.http_transport import StdlibHttpTransport
from transrealm.adapters.openai_adapter import OpenAICompatibleAdapter
from transrealm.adapters.protocol import CredentialResolver, Transport
from transrealm.domain.model_profile import ModelCapabilityError, ModelProfile
from transrealm.domain.provider_connection import ProviderConnection


class AdapterCompositionError(ValueError):
    """Invalid connection/profile configuration for adapter composition."""


def compose_adapter(
    connection: ProviderConnection,
    profile: ModelProfile,
    *,
    transport: Transport | None = None,
    credential_resolver: CredentialResolver | None = None,
) -> OpenAICompatibleAdapter:
    """Build an OpenAI-compatible adapter from a persisted connection/profile.

    The connection contributes the endpoint, timeout, retry policy and
    credential reference; the profile contributes the model id and capability
    snapshot. The default transport is :class:`StdlibHttpTransport` rooted at
    the connection endpoint; the default resolver is chosen from the
    credential reference scheme (``env:``/``wincred:``). Callers may inject
    either to keep composition testable without a network.
    """
    try:
        connection.validate()
    except ValueError as exc:
        raise AdapterCompositionError(
            f"Connection {connection.name!r} has invalid configuration.",
        ) from exc
    if connection.provider_type not in {
        "openai-compatible",
        "ollama",
        "llama.cpp",
    }:
        raise AdapterCompositionError(
            f"Connection {connection.name!r} has unsupported provider type "
            f"{connection.provider_type!r}.",
        )
    try:
        capability = profile.get_capability()
    except ModelCapabilityError as exc:
        raise AdapterCompositionError(
            f"Profile {profile.name!r} has no usable capability snapshot.",
        ) from exc
    try:
        resolver = credential_resolver or build_resolver(
            connection.credential_reference,
        )
    except ValueError as exc:
        raise AdapterCompositionError(
            f"Connection {connection.name!r} has an unsupported "
            "credential reference.",
        ) from exc
    return OpenAICompatibleAdapter(
        endpoint=connection.endpoint,
        model_id=profile.model_id,
        capability=capability,
        credential_reference=connection.credential_reference,
        credential_resolver=resolver,
        transport=transport or StdlibHttpTransport(base_url=connection.endpoint),
        timeout_seconds=connection.timeout_seconds,
        max_retries=connection.max_retries,
        retry_delay_seconds=connection.retry_delay_seconds,
    )
