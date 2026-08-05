"""Segment attempt domain model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime


class SegmentAttemptError(ValueError):
    """Invalid segment attempt state or configuration."""


@dataclass
class SegmentAttempt:
    """A single attempt to translate a segment within a run.

    The attempt records the claim generation (claim_version + lease_owner),
    the model profile snapshot, prompt hash and context/validator summaries
    needed to explain the attempt after restart. Secrets must never appear in
    any persisted field.
    """

    id: int | None
    run_id: int
    segment_id: int
    claim_version: int
    lease_owner: str
    idempotency_key: str
    model_profile_id: int
    profile_snapshot: dict[str, object]
    prompt_hash: str
    context_summary: dict[str, object]
    validator_summary: dict[str, object]
    request_id: str | None
    status: str
    retryable: bool
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    error_type: str | None
    error_message: str | None
    created_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        run_id: int,
        segment_id: int,
        claim_version: int,
        lease_owner: str,
        idempotency_key: str,
        model_profile_id: int,
        profile_snapshot: dict[str, object],
        prompt_hash: str,
        context_summary: dict[str, object],
        validator_summary: dict[str, object],
    ) -> SegmentAttempt:
        """Create a new, unsaved segment attempt in the 'created' state."""
        instance = cls(
            id=None,
            run_id=run_id,
            segment_id=segment_id,
            claim_version=claim_version,
            lease_owner=lease_owner,
            idempotency_key=idempotency_key,
            model_profile_id=model_profile_id,
            profile_snapshot=profile_snapshot,
            prompt_hash=prompt_hash,
            context_summary=context_summary,
            validator_summary=validator_summary,
            request_id=None,
            status="created",
            retryable=False,
            input_tokens=None,
            output_tokens=None,
            latency_ms=None,
            error_type=None,
            error_message=None,
            created_at=None,
            finished_at=None,
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate fields and raise SegmentAttemptError on failure."""
        if not isinstance(self.run_id, int) or self.run_id <= 0:
            raise SegmentAttemptError("run_id must be a positive integer.")

        if not isinstance(self.segment_id, int) or self.segment_id <= 0:
            raise SegmentAttemptError("segment_id must be a positive integer.")

        if not isinstance(self.claim_version, int) or self.claim_version <= 0:
            raise SegmentAttemptError("claim_version must be a positive integer.")

        if not self.lease_owner or not self.lease_owner.strip():
            raise SegmentAttemptError("lease_owner is required.")

        if not self.idempotency_key or not self.idempotency_key.strip():
            raise SegmentAttemptError("idempotency_key is required.")

        if not isinstance(self.model_profile_id, int) or self.model_profile_id <= 0:
            raise SegmentAttemptError("model_profile_id must be a positive integer.")

        for field_name in ("profile_snapshot", "context_summary", "validator_summary"):
            value = getattr(self, field_name)
            if not isinstance(value, dict):
                raise SegmentAttemptError(f"{field_name} must be a JSON object.")
            try:
                json.dumps(value)
            except TypeError as exc:
                raise SegmentAttemptError(
                    f"{field_name} must be JSON-serializable: {exc}",
                ) from exc

        if not self.prompt_hash or not self.prompt_hash.strip():
            raise SegmentAttemptError("prompt_hash is required.")

        if self.status not in {"created", "succeeded", "failed", "cancelled"}:
            raise SegmentAttemptError(f"Invalid attempt status: {self.status!r}")

        if not isinstance(self.retryable, bool):
            raise SegmentAttemptError("retryable must be a boolean.")
