"""Model Capability and Model Profile domain models.

A Model Capability describes what a model can do (context window, output
limits, supported parameters, etc.). A Model Profile captures a reusable
configuration for translation tasks, including a snapshot of capability
information and a reference to a persisted ProviderConnection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


class ModelCapabilityError(ValueError):
    """Invalid model capability configuration."""


class ModelProfileError(ValueError):
    """Invalid model profile configuration."""


@dataclass
class ModelCapability:
    """Describes the runtime capabilities of a model/provider endpoint."""

    context_window: int
    max_output_tokens: int
    supports_streaming: bool
    supports_structured_output: bool
    supported_parameters: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        """Validate fields after dataclass construction."""
        self.validate()

    def validate(self) -> None:
        """Validate capability fields and raise ModelCapabilityError on failure."""
        if self.context_window <= 0:
            raise ModelCapabilityError(
                f"context_window must be positive: {self.context_window}",
            )
        if self.max_output_tokens <= 0:
            raise ModelCapabilityError(
                f"max_output_tokens must be positive: {self.max_output_tokens}",
            )
        if not isinstance(self.supports_streaming, bool):
            raise ModelCapabilityError("supports_streaming must be a boolean.")
        if not isinstance(self.supports_structured_output, bool):
            raise ModelCapabilityError(
                "supports_structured_output must be a boolean.",
            )
        if not isinstance(self.supported_parameters, set):
            raise ModelCapabilityError("supported_parameters must be a set.")

    def to_snapshot(self) -> dict[str, object]:
        """Return a JSON-serializable snapshot dict."""
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_streaming": self.supports_streaming,
            "supports_structured_output": self.supports_structured_output,
            "supported_parameters": sorted(self.supported_parameters),
        }

    @classmethod
    def from_snapshot(cls, snapshot: object) -> ModelCapability:
        """Restore a capability from a JSON-deserialized snapshot."""
        if not isinstance(snapshot, dict):
            raise ModelCapabilityError("capability snapshot must be a JSON object.")
        params = snapshot.get("supported_parameters", [])
        if not isinstance(params, list):
            raise ModelCapabilityError("supported_parameters must be a list.")
        return cls(
            context_window=int(snapshot["context_window"]),
            max_output_tokens=int(snapshot["max_output_tokens"]),
            supports_streaming=bool(snapshot["supports_streaming"]),
            supports_structured_output=bool(snapshot["supports_structured_output"]),
            supported_parameters=set(str(p) for p in params),
        )


@dataclass
class ModelProfile:
    """A reusable model configuration referencing a ProviderConnection."""

    id: int | None
    name: str
    provider_connection_id: int
    model_id: str
    template_version: str
    output_protocol: str
    context_budget: dict[str, object]
    default_params: dict[str, object]
    capability_snapshot: dict[str, object]
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        provider_connection_id: int,
        model_id: str,
        template_version: str,
        output_protocol: str,
        context_budget: dict[str, object] | None = None,
        default_params: dict[str, object] | None = None,
        capability: ModelCapability | None = None,
    ) -> ModelProfile:
        """Create and validate a new, unsaved ModelProfile."""
        instance = cls(
            id=None,
            name=name,
            provider_connection_id=provider_connection_id,
            model_id=model_id,
            template_version=template_version,
            output_protocol=output_protocol,
            context_budget=context_budget if context_budget is not None else {},
            default_params=default_params if default_params is not None else {},
            capability_snapshot=capability.to_snapshot() if capability else {},
            created_at=None,
            updated_at=None,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate all fields and raise ModelProfileError on failure."""
        if not self.name or not self.name.strip():
            raise ModelProfileError("Profile name is required.")

        if not isinstance(self.provider_connection_id, int) or self.provider_connection_id <= 0:
            raise ModelProfileError(
                "provider_connection_id must be a positive integer.",
            )

        if not self.model_id or not self.model_id.strip():
            raise ModelProfileError("model_id is required.")

        if not self.template_version or not self.template_version.strip():
            raise ModelProfileError("template_version is required.")

        if not self.output_protocol or not self.output_protocol.strip():
            raise ModelProfileError("output_protocol is required.")

        for field_name in ("context_budget", "default_params", "capability_snapshot"):
            value = getattr(self, field_name)
            if not isinstance(value, dict):
                raise ModelProfileError(f"{field_name} must be a JSON object.")
            try:
                json.dumps(value)
            except TypeError as exc:
                raise ModelProfileError(
                    f"{field_name} must be JSON-serializable: {exc}",
                ) from exc

    def with_updated_fields(
        self,
        *,
        name: str | None = None,
        provider_connection_id: int | None = None,
        model_id: str | None = None,
        template_version: str | None = None,
        output_protocol: str | None = None,
        context_budget: dict[str, object] | None = None,
        default_params: dict[str, object] | None = None,
        capability: ModelCapability | None = None,
    ) -> ModelProfile:
        """Return a copy with selected fields replaced and re-validated."""
        updated = ModelProfile(
            id=self.id,
            name=name if name is not None else self.name,
            provider_connection_id=provider_connection_id
            if provider_connection_id is not None
            else self.provider_connection_id,
            model_id=model_id if model_id is not None else self.model_id,
            template_version=template_version
            if template_version is not None
            else self.template_version,
            output_protocol=output_protocol
            if output_protocol is not None
            else self.output_protocol,
            context_budget=context_budget
            if context_budget is not None
            else self.context_budget,
            default_params=default_params
            if default_params is not None
            else self.default_params,
            capability_snapshot=capability.to_snapshot()
            if capability
            else self.capability_snapshot,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        updated.validate()
        return updated

    def get_capability(self) -> ModelCapability:
        """Restore the embedded capability snapshot."""
        if not self.capability_snapshot:
            raise ModelCapabilityError(
                "Profile has no capability snapshot. Provide a ModelCapability first.",
            )
        return ModelCapability.from_snapshot(self.capability_snapshot)
