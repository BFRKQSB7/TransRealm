"""Product-facing, Qt-free boundary for one Job's translation lifecycle.

This facade delegates persistence and fencing to the existing application
services. A desktop worker owns one instance on its worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from transrealm.adapters.protocol import ModelAdapter
from transrealm.application.adapter_factory import compose_adapter
from transrealm.application.context import ContextManifest
from transrealm.application.context_composer import ContextComposer
from transrealm.application.exporter import (
    AssExporter,
    FidelityExporter,
    JsonExporter,
    SrtExporter,
    SsaExporter,
    TxtExporter,
    VttExporter,
)
from transrealm.application.glossary_context import build_glossary_candidates
from transrealm.application.glossary_service import GlossaryService
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_notes_service import ProjectNotesService
from transrealm.application.project_service import ProjectDeletionSummary, ProjectService
from transrealm.application.prompt_library_service import NamedPrompt, PromptLibraryService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.translation_service import TranslationService
from transrealm.application.workbench import SegmentProgress
from transrealm.domain.glossary_entry import GlossaryEntry
from transrealm.domain.model_profile import ModelProfile
from transrealm.domain.project import Project
from transrealm.domain.prompt_override import PromptOverride
from transrealm.domain.provider_connection import ProviderConnection
from transrealm.domain.segment import Segment, SourceDocument
from transrealm.domain.segment_attempt import SegmentAttempt
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.domain.translation_run import TranslationRun
from transrealm.infrastructure.repositories.segment_repository import SegmentRepository


class TranslationFacadeError(ValueError):
    """A requested Job operation cannot be performed safely."""


@dataclass(frozen=True)
class ActiveModel:
    """Credential-free active Provider/model/template summary for the workspace."""

    profile_id: int
    provider_name: str
    model_id: str
    template_version: str
    has_prompt_override: bool


_EXPORTERS: dict[str, type[FidelityExporter]] = {
    "txt": TxtExporter,
    "json": JsonExporter,
    "srt": SrtExporter,
    "vtt": VttExporter,
    "ass": AssExporter,
    "ssa": SsaExporter,
}


class TranslationFacade:
    """Expose the current Job and single-segment pipeline through one API."""

    def __init__(
        self, db_path: Path, *, app_version: str, adapter: ModelAdapter | None = None
    ) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self._runs = TranslationRunService(db_path, app_version=app_version)
        self._translation = (
            TranslationService(db_path, app_version=app_version, adapter=adapter)
            if adapter is not None
            else None
        )

    @staticmethod
    def adapter_for_profile(db_path: Path, app_version: str, profile_id: int) -> ModelAdapter:
        """Resolve the persisted Provider/Profile pair on the calling worker thread."""
        with ProviderConnectionService(db_path, app_version=app_version) as connections:
            with ModelProfileService(db_path, app_version=app_version) as profiles:
                profile = profiles.get_profile(profile_id)
                if profile is None:
                    raise TranslationFacadeError(f"ModelProfile {profile_id} does not exist.")
                connection = connections.get_connection(profile.provider_connection_id)
                if connection is None:
                    raise TranslationFacadeError(
                        f"ProviderConnection for profile {profile_id} does not exist."
                    )
        return compose_adapter(connection, profile)

    def create_job(self, *, name: str, source_language: str, target_language: str) -> Project:
        """Create a Job using the existing Project persistence contract."""
        with ProjectService(self._db_path, app_version=self._app_version) as service:
            return service.create_project(
                name=name, source_language=source_language, target_language=target_language
            )

    def open_job(self, project_id: int | None = None) -> Project | None:
        """Open a selected Job or the first existing Job."""
        with ProjectService(self._db_path, app_version=self._app_version) as service:
            if project_id is not None:
                return service.get_project(project_id)
            return service.open_project()

    def list_documents(self, project_id: int) -> list[SourceDocument]:
        return self._runs.list_source_documents(project_id=project_id)

    def list_jobs(self) -> list[Project]:
        with ProjectService(self._db_path, app_version=self._app_version) as service:
            return service.list_projects()

    def deletion_summary(self, project_id: int) -> ProjectDeletionSummary | None:
        with ProjectService(self._db_path, app_version=self._app_version) as service:
            return service.get_project_deletion_summary(project_id)

    def delete_job(self, project_id: int) -> Path | None:
        with ProjectService(self._db_path, app_version=self._app_version) as service:
            return service.delete_project(project_id)

    def available_models(self) -> list[ModelProfile]:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.list_profiles()

    def available_providers(self) -> list[ProviderConnection]:
        with ProviderConnectionService(self._db_path, app_version=self._app_version) as service:
            return service.list_connections()

    def available_prompts(self) -> list[NamedPrompt]:
        return PromptLibraryService(
            self._db_path, app_version=self._app_version
        ).list_templates()

    def select_prompt(self, profile_id: int, template_id: str | None) -> None:
        PromptLibraryService(self._db_path, app_version=self._app_version).apply(
            profile_id, template_id
        )

    def clear_active_profile(self, project_id: int) -> Project:
        with ProjectService(self._db_path, app_version=self._app_version) as service:
            return service.clear_active_profile(project_id)

    def list_segments(self, source_document_id: int) -> list[Segment]:
        repo = SegmentRepository.open(self._db_path)
        try:
            return repo.list_segments_by_document(source_document_id)
        finally:
            repo.close()

    def progress(self, source_document_id: int) -> list[SegmentProgress]:
        return self._runs.list_segment_progress(source_document_id=source_document_id)

    def import_document(
        self, project_id: int, file_path: Path, *, encoding: str = "utf-8"
    ) -> tuple[SourceDocument, list[Segment]]:
        with ImportService(self._db_path, app_version=self._app_version) as service:
            return service.import_file(project_id, file_path, encoding=encoding)

    def export_document(
        self, source_document_id: int, target_path: Path, *, apply_revisions: bool = True
    ) -> None:
        repo = SegmentRepository.open(self._db_path)
        try:
            document = repo.get_source_document_by_id(source_document_id)
        finally:
            repo.close()
        if document is None:
            raise TranslationFacadeError(f"SourceDocument {source_document_id} does not exist.")
        exporter_type = _EXPORTERS.get(document.format)
        if exporter_type is None:
            raise TranslationFacadeError(f"Unsupported export format: {document.format}.")
        with exporter_type(self._db_path, app_version=self._app_version) as exporter:
            exporter.export_document(
                source_document_id=source_document_id,
                target_path=target_path,
                apply_revisions=apply_revisions,
            )

    def active_profile(self, project_id: int) -> ModelProfile | None:
        project = self.open_job(project_id)
        if project is None:
            raise TranslationFacadeError(f"Job {project_id} does not exist.")
        if project.active_profile_id is None:
            return None
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.get_profile(project.active_profile_id)

    def select_active_profile(self, project_id: int, profile_id: int) -> Project:
        with ProjectService(self._db_path, app_version=self._app_version) as service:
            return service.select_active_profile(project_id, profile_id)

    def active_configuration(self, project_id: int) -> ActiveModel | None:
        profile = self.active_profile(project_id)
        if profile is None:
            return None
        assert profile.id is not None
        with ProviderConnectionService(self._db_path, app_version=self._app_version) as service:
            provider = service.get_connection(profile.provider_connection_id)
        if provider is None:
            raise TranslationFacadeError("Active Provider connection is missing.")
        return ActiveModel(
            profile_id=profile.id,
            provider_name=provider.name,
            model_id=profile.model_id,
            template_version=profile.template_version,
            has_prompt_override=self.prompt_override(profile.id) is not None,
        )

    def prompt_override(self, profile_id: int) -> PromptOverride | None:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.get_prompt_override(profile_id)

    def set_prompt_override(self, profile_id: int, template_text: str) -> PromptOverride:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.set_prompt_override(profile_id, template_text)

    def clear_prompt_override(self, profile_id: int) -> bool:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.clear_prompt_override(profile_id)

    def notes(self, project_id: int) -> str:
        with ProjectNotesService(self._db_path, app_version=self._app_version) as service:
            return service.get_notes(project_id)

    def set_notes(self, project_id: int, content: str) -> str:
        with ProjectNotesService(self._db_path, app_version=self._app_version) as service:
            return service.set_notes(project_id, content)

    def glossary(self, project_id: int) -> list[GlossaryEntry]:
        with GlossaryService(self._db_path, app_version=self._app_version) as service:
            return service.list_entries(project_id)

    def add_glossary_entry(
        self,
        project_id: int,
        source_term: str,
        target_term: str,
        *,
        scope: str = "project",
        is_locked: bool = False,
        priority: int = 50,
    ) -> GlossaryEntry:
        with GlossaryService(self._db_path, app_version=self._app_version) as service:
            return service.create_entry(
                project_id=project_id,
                source_term=source_term,
                target_term=target_term,
                scope=scope,
                is_locked=is_locked,
                priority=priority,
            )

    def update_glossary_entry(
        self,
        entry_id: int,
        source_term: str,
        target_term: str,
        *,
        scope: str,
        priority: int,
        is_locked: bool,
    ) -> GlossaryEntry:
        with GlossaryService(self._db_path, app_version=self._app_version) as service:
            return service.update_entry(
                entry_id,
                source_term=source_term,
                target_term=target_term,
                scope=scope,
                priority=priority,
                is_locked=is_locked,
            )

    def delete_glossary_entry(self, entry_id: int) -> bool:
        with GlossaryService(self._db_path, app_version=self._app_version) as service:
            return service.delete_entry(entry_id)

    def context_preview(self, segment_id: int, profile_id: int) -> ContextManifest:
        """Read the same budgeted context used by the pipeline without claiming work."""
        repo = SegmentRepository.open(self._db_path)
        try:
            segment = repo.get_by_id(segment_id)
            if segment is None:
                raise TranslationFacadeError("Select an existing segment.")
            document = repo.get_source_document_by_id(segment.source_document_id)
            neighbors = repo.list_segments_by_document(segment.source_document_id)
        finally:
            repo.close()
        if document is None:
            raise TranslationFacadeError("Selected source file is missing.")
        profile = next((model for model in self.available_models() if model.id == profile_id), None)
        if profile is None:
            raise TranslationFacadeError("Choose an available model in Providers.")
        budget = TranslationService.build_context_budget(profile)
        return ContextComposer().compose(
            profile_id=str(profile_id),
            template_version=profile.template_version,
            current=segment,
            neighbors=neighbors,
            notes=self.notes(document.project_id),
            glossary_candidates=build_glossary_candidates(
                [entry for entry in self.glossary(document.project_id) if entry.is_locked],
                estimate_method=budget.estimate_method,
            ),
            budget=budget,
        )

    def start_run(self, project_id: int) -> TranslationRun:
        """Recover only expired work, then begin a new auditable Run."""
        translation = self._require_translation()
        translation.recover_expired_leases()
        return translation.create_run(project_id=project_id)

    def resume(self, project_id: int) -> TranslationRun:
        """Resume remaining pending work in a fresh Run after safe recovery."""
        return self.start_run(project_id)

    async def translate_segment(
        self,
        *,
        run_id: int,
        segment_id: int,
        profile_id: int,
        extra_params: dict[str, object] | None = None,
    ) -> TranslationRevision:
        return await self._require_translation().translate_segment(
            run_id=run_id,
            segment_id=segment_id,
            profile_id=profile_id,
            extra_params=extra_params,
        )

    def finish_run(self, run_id: int, *, status: str) -> TranslationRun:
        """Persist completion or Stop only after the in-flight call settles."""
        self._runs.recover_expired_leases()
        if any(attempt.status == "created" for attempt in self._runs.list_attempts_for_run(run_id)):
            raise TranslationFacadeError(
                "An in-flight request must settle before this Run can stop."
            )
        return self._runs.finish_run(run_id=run_id, status=status)

    def stop(self, run_id: int) -> TranslationRun:
        """Persist a requested Stop after the current request has settled."""
        return self.finish_run(run_id, status="cancelled")

    def runs(self, project_id: int) -> list[TranslationRun]:
        return self._runs.list_runs_for_project(project_id)

    def attempts(self, run_id: int) -> list[SegmentAttempt]:
        return self._runs.list_attempts_for_run(run_id)

    def retry_failed(self, segment_id: int) -> Segment:
        return self._runs.retry_failed(segment_id=segment_id)

    def requeue_segment(self, segment_id: int) -> Segment:
        return self._runs.requeue_segment(segment_id=segment_id)

    def revisions(self, segment_id: int) -> list[TranslationRevision]:
        return self._runs.list_revisions_for_segment(segment_id=segment_id)

    def save_manual_revision(self, segment_id: int, text: str) -> TranslationRevision:
        return self._runs.append_user_revision(segment_id=segment_id, text=text)

    def select_revision(self, segment_id: int, revision_id: int) -> TranslationRevision:
        return self._runs.set_current_revision(segment_id=segment_id, revision_id=revision_id)

    def lock_current(self, segment_id: int) -> TranslationRevision:
        return self._runs.lock_current_revision(segment_id=segment_id)

    def unlock_current(self, segment_id: int) -> TranslationRevision:
        return self._runs.unlock_current_revision(segment_id=segment_id)

    def _require_translation(self) -> TranslationService:
        if self._translation is None:
            raise TranslationFacadeError("A model adapter is required to start translation.")
        return self._translation

    def close(self) -> None:
        if self._translation is not None:
            self._translation.close()
        self._runs.close()

    def __enter__(self) -> TranslationFacade:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
