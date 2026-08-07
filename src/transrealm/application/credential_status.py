"""Read-only credential availability report for imported Projects (P1-T02-M05).

An imported Project keeps only opaque credential references (``env:`` /
``wincred:``) — the secret value never enters the archive, the database, or the
installed target. On the target machine the referenced credential may be
absent, so ``04`` §7 requires an actionable hint. This module reports, for each
connection that carries a credential reference, whether that reference resolves
on the current machine and, when missing, what the user must do. It never
returns secret values.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from transrealm.adapters.credential_resolvers import credential_reference_is_available
from transrealm.domain.provider_connection import ProviderConnection

__all__ = [
    "CredentialStatus",
    "report_credential_availability",
]


@dataclass(frozen=True)
class CredentialStatus:
    """Availability of one connection's credential reference on this machine."""

    connection_name: str
    credential_reference: str
    available: bool
    hint: str | None


def report_credential_availability(
    connections: Iterable[ProviderConnection],
) -> list[CredentialStatus]:
    """Report, per credentialed connection, whether its reference resolves here.

    Connections without a credential reference are skipped. A missing reference
    carries an actionable hint naming the environment variable or Windows
    Credential entry to provide; the secret value is never resolved or returned.
    """
    statuses: list[CredentialStatus] = []
    for connection in connections:
        reference = connection.credential_reference
        if reference is None:
            continue
        available = credential_reference_is_available(reference)
        statuses.append(
            CredentialStatus(
                connection_name=connection.name,
                credential_reference=reference,
                available=available,
                hint=None if available else _hint_for(reference),
            ),
        )
    return statuses


def _hint_for(reference: str) -> str:
    """Return an actionable hint for a missing credential reference."""
    if reference.startswith("env:"):
        var = reference[len("env:"):]
        return f"Set the environment variable {var!r} on this machine."
    if reference.startswith("wincred:"):
        target = reference[len("wincred:"):]
        return f"Create the Windows Credential Manager entry {target!r} on this machine."
    return f"Provide the credential referenced by {reference!r} on this machine."
