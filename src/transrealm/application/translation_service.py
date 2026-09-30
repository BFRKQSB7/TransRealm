"""No-UI translation use case: compose -> render -> call -> validate -> finalize.

This service wires the Phase 0 components (ContextComposer, PromptRenderer,
OutputParser, a ModelAdapter and the P0-T07 TranslationRunService) into a
single vertical slice: translating one pending segment produces a persisted,
reopenable TranslationRevision. It is transport-agnostic: a ModelAdapter is
injected, so P0-T08-M02 can introduce production HTTP without changing the
use case.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from transrealm.adapters.dto import AdapterMessage, AdapterRequest
from transrealm.adapters.errors import AdapterContextOverflowError, AdapterError
from transrealm.adapters.protocol import ModelAdapter
from transrealm.application.context import (
    ContextBudget,
    ContextManifest,
    ContextSource,
    EstimateMethod,
)
from transrealm.application.context_composer import ContextComposer
from transrealm.application.glossary_context import build_glossary_candidates
from transrealm.application.output_parser import (
    IssueCategory,
    OutputParser,
    ParseIssue,
    ValidationReport,
)
from transrealm.application.preset_templates import current_preset, resolve_override_template
from transrealm.application.prompt_renderer import PromptRenderer, RenderedPrompt
from transrealm.application.translation_run_service import (
    BUILTIN_GENERAL_TRANSLATION_WORKFLOW,
    TranslationRunService,
    TranslationRunServiceError,
)
from transrealm.domain.model_profile import ModelProfile
from transrealm.domain.prompt_override import PromptOverride
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.domain.translation_run import TranslationRun
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.glossary_entry_repository import (
    GlossaryEntryRepository,
)
from transrealm.infrastructure.repositories.model_profile_repository import (
    ModelProfileRepository,
)
from transrealm.infrastructure.repositories.project_notes_repository import ProjectNotesRepository
from transrealm.infrastructure.repositories.project_repository import ProjectRepository
from transrealm.infrastructure.repositories.prompt_override_repository import (
    PromptOverrideRepository,
)
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository
from transrealm.infrastructure.repositories.translation_workflow_repository import (
    WorkflowDefinitionRepository,
)


class TranslationServiceError(RuntimeError):
    """Invalid translation use case operation or configuration."""


class TranslationService:
    """Translate a pending segment end to end with no UI.

    The use case owns a read connection plus a :class:`TranslationRunService`
    for P0-T07 persistence. The injected adapter is called only after the
    context budget is satisfied and the attempt is claimed; empty segments,
    missing profiles and unusable budgets never reach the adapter.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        app_version: str,
        adapter: ModelAdapter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._run_service = TranslationRunService(
            db_path,
            app_version=app_version,
            clock=clock,
        )
        self._db = create_database(db_path)
        self._segment_repository = SegmentRepository(self._db)
        self._profile_repository = ModelProfileRepository(self._db)
        self._override_repository = PromptOverrideRepository(self._db)
        self._project_repository = ProjectRepository(self._db)
        self._notes_repository = ProjectNotesRepository(self._db)
        self._workflow_repository = WorkflowDefinitionRepository(self._db)
        self._glossary_repository = GlossaryEntryRepository(self._db)
        self._adapter = adapter
        self._clock = clock or (lambda: datetime.now(UTC))
        self._composer = ContextComposer()
        self._renderer = PromptRenderer()
        self._parser = OutputParser()

    def create_run(self, *, project_id: int) -> TranslationRun:
        """Create a translation run against the seeded built-in workflow."""
        workflow = self._workflow_repository.get_by_name_and_version(
            BUILTIN_GENERAL_TRANSLATION_WORKFLOW.name,
            BUILTIN_GENERAL_TRANSLATION_WORKFLOW.version,
        )
        if workflow is None or workflow.id is None:
            raise TranslationServiceError(
                "Seeded built-in workflow is missing; cannot create a run.",
            )
        return self._run_service.create_run(
            project_id=project_id,
            workflow_id=workflow.id,
        )

    async def translate_segment(
        self,
        *,
        run_id: int,
        segment_id: int,
        profile_id: int,
        lease_duration_seconds: int = 60,
        max_repair_attempts: int = 1,
        max_context_reductions: int = 3,
        extra_params: dict[str, object] | None = None,
    ) -> TranslationRevision:
        """Translate one segment end to end and return the persisted revision.

        The run must be ``running``. The segment must exist with non-empty
        source text, the profile must exist, and the current segment must fit
        the profile's context budget. Any of these failing raises before an
        attempt is claimed and before the adapter is called.

        When the model output fails validation but the first issue is marked
        repairable by the OutputParser, the segment is re-translated once (up
        to ``max_repair_attempts``) as a fresh attempt with a new idempotency
        key. Non-repairable output, or output still invalid after the repair
        budget is exhausted, is finalized as a permanent failure.

        ``extra_params`` are the request parameters captured for this attempt
        (the workbench draft, or the profile defaults when not provided). Each
        attempt snapshots them, so changing the workbench parameters affects
        only attempts claimed afterwards — completed attempts and revisions are
        never rewritten. The adapter filters the parameters against the
        capability before sending, so unsupported parameters are never sent.

        Raises:
            TranslationServiceError: For missing run/segment/profile, empty
                source text, an unusable budget, an adapter failure, or output
                that fails validation without a successful repair.
            ContextBudgetError: If the current segment cannot fit the budget.
        """
        if max_repair_attempts < 0:
            raise TranslationServiceError(
                f"max_repair_attempts must be non-negative: {max_repair_attempts}.",
            )
        if max_context_reductions < 0:
            raise TranslationServiceError("max_context_reductions must be non-negative.")

        run = self._run_service.get_run(run_id)
        if run is None:
            raise TranslationServiceError(
                f"TranslationRun with id {run_id} does not exist.",
            )
        if run.status != "running":
            raise TranslationServiceError(
                f"Cannot translate: run {run_id} status is {run.status!r}.",
            )

        segment = self._segment_repository.get_by_id(segment_id)
        if segment is None:
            raise TranslationServiceError(
                f"Segment with id {segment_id} does not exist.",
            )
        if not segment.source_text:
            raise TranslationServiceError(
                f"Segment {segment_id} has empty source text; nothing to translate.",
            )

        source_document = self._segment_repository.get_source_document_by_id(
            segment.source_document_id,
        )
        if source_document is None:
            raise TranslationServiceError(
                f"SourceDocument with id {segment.source_document_id} does not exist.",
            )
        if source_document.project_id != run.project_id:
            raise TranslationServiceError(
                f"Segment {segment_id} does not belong to run {run_id}'s project.",
            )

        profile = self._profile_repository.get_by_id(profile_id)
        if profile is None:
            raise TranslationServiceError(
                f"ModelProfile with id {profile_id} does not exist.",
            )
        assert profile.id is not None

        project = self._project_repository.get_by_id(run.project_id)
        if project is None:
            raise TranslationServiceError(
                f"Project with id {run.project_id} does not exist.",
            )

        budget = self.build_context_budget(profile)
        neighbors = self._segment_repository.list_segments_by_document(
            segment.source_document_id,
        )
        glossary_candidates = build_glossary_candidates(
            self._glossary_repository.list_locked_by_project(run.project_id),
            estimate_method=budget.estimate_method,
        )
        notes = self._notes_repository.get(run.project_id)
        manifest = self._composer.compose(
            profile_id=str(profile.id),
            template_version=profile.template_version,
            current=segment,
            neighbors=neighbors,
            glossary_candidates=glossary_candidates,
            notes=notes,
            budget=budget,
        )
        override = self._override_repository.get_by_profile(profile.id)
        template = None
        if override is not None:
            # Fail-closed before any attempt is claimed: a stale override
            # (parent preset version changed) is rejected without a request.
            template = resolve_override_template(override, current_preset())
        rendered = self._renderer.render(
            profile_id=str(profile.id),
            template_version=profile.template_version,
            template=template,
            manifest=manifest,
            source_language=project.source_language,
            target_language=project.target_language,
            output_protocol=profile.output_protocol,
        )

        claim_segment = segment
        repairs_used = 0
        reductions_used = 0
        repair_reason: str | None = None
        request_params = dict(profile.default_params if extra_params is None else extra_params)
        while True:
            attempt = self._run_service.start_attempt(
                run_id=run_id,
                segment=claim_segment,
                profile=profile,
                prompt_hash=rendered.prompt_hash,
                context_summary=self._context_summary(
                    manifest,
                    rendered,
                    override=override,
                    overflow_reductions=reductions_used,
                ),
                validator_summary=self._validator_summary(
                    rendered,
                    repairs_used=repairs_used,
                    repair_reason=repair_reason,
                ),
                lease_duration_seconds=lease_duration_seconds,
                request_params=request_params,
            )
            assert attempt.id is not None

            started = self._clock()
            try:
                response = await self._adapter.chat_completion(
                    self._build_adapter_request(profile, rendered, extra_params=request_params),
                )
            except AdapterError as exc:
                if isinstance(exc, AdapterContextOverflowError):
                    reduced = self._reduce_optional_context(manifest)
                    next_rendered = None
                    if reduced is not None and reductions_used < max_context_reductions:
                        next_rendered = self._renderer.render(
                            profile_id=str(profile.id),
                            template_version=profile.template_version,
                            template=template,
                            manifest=reduced,
                            source_language=project.source_language,
                            target_language=project.target_language,
                            output_protocol=profile.output_protocol,
                        )
                        if next_rendered.prompt_hash == rendered.prompt_hash:
                            next_rendered = None
                    self._run_service.finalize_failure(
                        attempt_id=attempt.id,
                        error_type=exc.category,
                        error_message=exc.safe_message,
                        retryable=next_rendered is not None,
                    )
                    if next_rendered is not None:
                        assert reduced is not None
                        claim_segment = self._run_service.retry_failed(segment_id=segment_id)
                        manifest = reduced
                        rendered = next_rendered
                        reductions_used += 1
                        continue
                    raise TranslationServiceError(
                        "Provider context overflow persists after optional context reduction."
                    ) from exc
                self._run_service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type=exc.category,
                    error_message=exc.safe_message,
                    retryable=exc.is_retryable,
                )
                raise TranslationServiceError(
                    f"Model call failed: {exc.category}: {exc.safe_message}",
                ) from exc
            except Exception as exc:
                if type(exc).__name__ == "SimulatedCrashError":
                    raise
                self._run_service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="unexpected_adapter_error",
                    error_message=f"Model call failed: {type(exc).__name__}",
                    retryable=False,
                )
                raise TranslationServiceError(
                    f"Model call failed unexpectedly: {type(exc).__name__}",
                ) from exc
            latency_ms = max(0, int((self._clock() - started).total_seconds() * 1000))

            if rendered.output_protocol == "text":
                report = self._parser.parse_text(
                    response.content,
                    output_contract=rendered.output_contract,
                    source_text=segment.source_text,
                    prompt_text=rendered.prompt_text,
                    finish_reason=response.finish_reason,
                    raw_response=response.raw_response,
                )
            elif response.finish_reason not in (None, "stop"):
                report = ValidationReport(
                    candidates=(),
                    issues=(
                        ParseIssue(
                            IssueCategory.TRUNCATED, "Provider output did not finish normally."
                        ),
                    ),
                )
            else:
                report = self._parser.parse(
                    response.content,
                    output_contract=rendered.output_contract,
                    raw_response=response.raw_response,
                )
            if report.is_valid:
                candidate = report.candidates[0]
                try:
                    _, revision = self._run_service.finalize_success(
                        attempt_id=attempt.id,
                        translated_text=candidate.translation,
                        expected_current_revision_id=claim_segment.current_revision_id,
                        request_id=response.request_id or "",
                        input_tokens=response.usage.prompt_tokens if response.usage else 0,
                        output_tokens=response.usage.completion_tokens if response.usage else 0,
                        latency_ms=latency_ms,
                    )
                except TranslationRunServiceError:
                    # The response is fenced out. If our lease is still valid,
                    # release it without creating a Revision. Expired claims
                    # are handled only by the existing recovery path.
                    try:
                        self._run_service.cancel_attempt(
                            attempt_id=attempt.id,
                            reason="Provider result rejected by finalization fencing.",
                        )
                    except TranslationRunServiceError:
                        self._run_service.recover_expired_leases()
                    raise
                return revision

            first = report.issues[0]
            if repairs_used < max_repair_attempts and first.repairable:
                self._run_service.finalize_failure(
                    attempt_id=attempt.id,
                    error_type="validation_error",
                    error_message=first.message,
                    retryable=True,
                )
                claim_segment = self._run_service.retry_failed(
                    segment_id=segment_id,
                )
                repairs_used += 1
                repair_reason = first.message
                continue

            self._run_service.finalize_failure(
                attempt_id=attempt.id,
                error_type="validation_error",
                error_message=first.message,
                retryable=False,
            )
            raise TranslationServiceError(
                f"Model output failed validation: {first.category.name}: {first.message}",
            )

    def recover_expired_leases(self) -> int:
        """Converge stale leases before a desktop worker begins new work."""
        return self._run_service.recover_expired_leases()

    @staticmethod
    def _reduce_optional_context(manifest: ContextManifest) -> ContextManifest | None:
        """Remove the farthest selected neighbor; retain target, glossary and Notes."""
        selected = list(manifest.selected)
        for index in range(len(selected) - 1, -1, -1):
            if selected[index].source == ContextSource.NEIGHBOR_SEGMENT:
                removed = selected.pop(index)
                return replace(
                    manifest,
                    selected=tuple(selected),
                    pruned=(removed, *manifest.pruned),
                )
        return None

    def finish_run(self, *, run_id: int, status: str) -> TranslationRun:
        """Persist the terminal status for a desktop translation run."""
        return self._run_service.finish_run(run_id=run_id, status=status)

    @classmethod
    def build_context_budget(cls, profile: ModelProfile) -> ContextBudget:
        """Build the ContextBudget declared by a profile, or raise."""
        raw = profile.context_budget
        if "total" not in raw:
            raise TranslationServiceError(
                f"Profile {profile.id} has an invalid context_budget: {raw!r}.",
            )
        total = cls._budget_int(raw["total"], "total", profile.id)
        reserved_output = cls._budget_int(
            raw.get("reserved_output", 0),
            "reserved_output",
            profile.id,
        )
        reserved_prompt = cls._budget_int(
            raw.get("reserved_prompt", 0),
            "reserved_prompt",
            profile.id,
        )
        try:
            return ContextBudget(
                total_budget=total,
                reserved_output=reserved_output,
                reserved_prompt=reserved_prompt,
                estimate_method=EstimateMethod.TOKEN,
            )
        except ValueError as exc:
            raise TranslationServiceError(
                f"Profile {profile.id} has an invalid context_budget: {exc}",
            ) from exc

    @staticmethod
    def _budget_int(value: object, field: str, profile_id: int | None) -> int:
        """Coerce a budget value to int, raising a clear error otherwise."""
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise TranslationServiceError(
                f"Profile {profile_id} context_budget.{field} must be an integer.",
            )
        try:
            return int(value)
        except ValueError as exc:
            raise TranslationServiceError(
                f"Profile {profile_id} context_budget.{field} must be an integer.",
            ) from exc

    def _build_adapter_request(
        self,
        profile: ModelProfile,
        rendered: RenderedPrompt,
        *,
        extra_params: dict[str, object] | None = None,
    ) -> AdapterRequest:
        """Build a normalized adapter request from the rendered prompt.

        ``extra_params`` are the parameters captured for this attempt (the
        workbench draft, or the profile defaults when not provided); the
        adapter still filters them against the capability before sending.
        """
        return AdapterRequest(
            model_id=profile.model_id,
            messages=(AdapterMessage(role="user", content=rendered.prompt_text),),
            extra_params=dict(profile.default_params if extra_params is None else extra_params),
            structured_output=(
                rendered.output_protocol == "json"
                and profile.get_capability().supports_structured_output
            ),
        )

    def _context_summary(
        self,
        manifest: ContextManifest,
        rendered: RenderedPrompt,
        *,
        override: PromptOverride | None = None,
        overflow_reductions: int = 0,
    ) -> dict[str, object]:
        """Build the T07 attempt audit record for context selection."""
        summary: dict[str, object] = {
            "selected_count": len(manifest.selected),
            "pruned_count": len(manifest.pruned),
            "selected_sources": [candidate.source.name for candidate in manifest.selected],
            "prompt_hash": rendered.prompt_hash,
            "overflow_reductions": overflow_reductions,
        }
        notes = next(
            (
                candidate.content
                for candidate in manifest.selected
                if candidate.source == ContextSource.JOB_NOTES
            ),
            "",
        )
        summary["notes"] = {
            "present": bool(notes),
            "characters": len(notes),
            "sha256": hashlib.sha256(notes.encode("utf-8")).hexdigest() if notes else None,
        }
        if override is not None:
            summary["override_parent_version"] = override.parent_template_version
        return summary

    def _validator_summary(
        self,
        rendered: RenderedPrompt,
        *,
        repairs_used: int = 0,
        repair_reason: str | None = None,
    ) -> dict[str, object]:
        """Build the T07 attempt audit record for the expected output.

        A repair attempt additionally records the repair-layer budget so the
        repair is independently accountable and cannot multiply unboundedly
        with adapter transport retries.
        """
        summary: dict[str, object] = {
            "output_contract_items": len(rendered.output_contract.items),
            "status": "pending",
            "output_protocol": rendered.output_protocol,
        }
        if repairs_used > 0:
            summary["repair_attempt"] = repairs_used
        if repair_reason is not None:
            summary["repair_reason"] = repair_reason
        return summary

    def close(self) -> None:
        """Close the run service and the read connection."""
        self._run_service.close()
        self._glossary_repository.close()
        self._workflow_repository.close()
        self._project_repository.close()
        self._override_repository.close()
        self._profile_repository.close()
        self._segment_repository.close()

    def __enter__(self) -> TranslationService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
