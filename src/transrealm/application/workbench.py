"""Workbench read models and capability-aware parameter helpers.

P1-T03-M02 surfaces the workbench: real Segment/Attempt progress and the
active Profile, with a parameter surface that only presents/sends the
parameters the Profile's capability declares as supported. These helpers are
Qt-free so the parameter policy can be unit-tested without a GUI; the widget
rendering lives in ``ui/workbench.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from transrealm.domain.model_profile import ModelCapability


@dataclass(frozen=True)
class SegmentProgress:
    """A segment plus its latest attempt, as shown in the workbench."""

    segment_id: int
    stable_key: str
    source_text: str
    status: str
    current_revision_id: int | None
    attempt_status: str | None
    attempt_error: str | None
    revision_text: str | None = None
    revision_locked: bool = False


@dataclass(frozen=True)
class ParamSpec:
    """Presentation metadata for a known sampling parameter."""

    name: str
    kind: str  # "float" | "int" | "bool" | "text"
    default: object
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None


# Common OpenAI-compatible sampling parameters. The capability decides which
# are presented, not this table; unknown supported parameters fall back to a
# plain text control so a model is never assumed to share another's surface.
_PARAM_SPECS: dict[str, ParamSpec] = {
    "temperature": ParamSpec("temperature", "float", 0.7, 0.0, 2.0, 0.1),
    "top_p": ParamSpec("top_p", "float", 1.0, 0.0, 1.0, 0.05),
    "top_k": ParamSpec("top_k", "int", 40, 1, None, 1),
    "max_tokens": ParamSpec("max_tokens", "int", 2048, 1, None, 1),
    "frequency_penalty": ParamSpec("frequency_penalty", "float", 0.0, 0.0, 2.0, 0.1),
    "presence_penalty": ParamSpec("presence_penalty", "float", 0.0, 0.0, 2.0, 0.1),
}


def param_spec(name: str) -> ParamSpec | None:
    """Return the presentation spec for a known parameter, if any."""
    return _PARAM_SPECS.get(name)


def presented_parameters(capability: ModelCapability) -> tuple[str, ...]:
    """Return the capability's supported parameters in a stable order."""
    return tuple(sorted(capability.supported_parameters))


def initial_param_values(
    capability: ModelCapability,
    default_params: dict[str, object],
) -> dict[str, object]:
    """Return the initial value for each supported parameter.

    Values come from ``default_params`` when they fit the parameter's type;
    otherwise the spec default (or a stringified raw value for unknown
    parameters) is used. ``max_tokens`` is clamped to the capability's output
    limit so the workbench never suggests a request the adapter would reject.
    """
    values: dict[str, object] = {}
    for name in presented_parameters(capability):
        spec = param_spec(name)
        raw = default_params.get(name)
        if _fits_spec(raw, spec):
            value: object = raw
        elif spec is not None:
            value = spec.default
        else:
            value = str(raw) if raw is not None else ""
        if name == "max_tokens" and isinstance(value, (int, float)):
            value = min(int(value), capability.max_output_tokens)
        values[name] = value
    return values


def _fits_spec(value: object, spec: ParamSpec | None) -> bool:
    """Whether ``value`` can be used directly for ``spec``'s control."""
    if value is None or isinstance(value, bool):
        return False
    if spec is None:
        return isinstance(value, str)
    if spec.kind == "float":
        return isinstance(value, (int, float))
    if spec.kind == "int":
        return isinstance(value, int)
    if spec.kind == "bool":
        return isinstance(value, bool)
    return isinstance(value, str)
