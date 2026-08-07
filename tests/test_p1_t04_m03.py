"""P1-T04-M03: deterministic locked-glossary injection into context.

The use case must query only the current project's locked glossary entries,
map them to existing ``ContextCandidate`` values, and let the ContextComposer
select them by priority/stable order before neighbor segments. The manifest
records selected/pruned, and a budget too small for the current segment still
raises ``ContextBudgetError`` instead of truncating source text.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from transrealm.adapters.dto import AdapterRequest, AdapterResponse, AdapterUsage
from transrealm.application.context import (
    BudgetEstimate,
    ContextBudget,
    ContextCandidate,
    ContextSource,
    EstimateMethod,
)
from transrealm.application.context_composer import (
    ContextBudgetError,
    ContextComposer,
)
from transrealm.application.glossary_context import (
    GLOSSARY_REASON,
    build_glossary_candidates,
)
from transrealm.application.glossary_service import GlossaryService
from transrealm.application.import_service import ImportService
from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.project_service import ProjectService
from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.application.translation_run_service import TranslationRunService
from transrealm.application.translation_service import TranslationService
from transrealm.domain.glossary_entry import GlossaryEntry
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.segment import Segment

APP_VERSION = "0.0.0-test"

DEFAULT_BUDGET: dict[str, object] = {
    "total": 4096,
    "reserved_output": 512,
    "reserved_prompt": 512,
}


class FakeAdapter:
    """In-memory ModelAdapter that captures the rendered prompt."""

    def __init__(self, response: AdapterResponse | Exception) -> None:
        self.response = response
        self.calls = 0
        self.last_request: AdapterRequest | None = None

    def get_capabilities(self) -> ModelCapability:
        return ModelCapability(
            context_window=128000,
            max_output_tokens=4096,
            supports_streaming=False,
            supports_structured_output=False,
            supported_parameters={"temperature", "max_tokens"},
        )

    def filter_params(self, params: dict[str, object]) -> dict[str, object]:
        return params

    async def chat_completion(self, request: AdapterRequest) -> AdapterResponse:
        self.calls += 1
        self.last_request = request
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    @property
    def last_prompt(self) -> str:
        assert self.last_request is not None
        return self.last_request.messages[0].content


def _create_project(path: Path, name: str) -> int:
    with ProjectService(path, app_version=APP_VERSION) as service:
        project = service.create_project(
            name=name,
            source_language="ja",
            target_language="zh",
        )
        assert project.id is not None
        return project.id


def _import_txt(path: Path, project_id: int, content: str) -> list[Segment]:
    txt_path = path.parent / "source.txt"
    txt_path.write_text(content, encoding="utf-8")
    with ImportService(path, app_version=APP_VERSION) as service:
        _document, segments = service.import_txt(project_id, txt_path, name="source.txt")
    return segments


def _ids(segments: list[Segment]) -> list[int]:
    ids: list[int] = []
    for segment in segments:
        assert segment.id is not None
        ids.append(segment.id)
    return ids


def _create_profile(
    path: Path,
    *,
    context_budget: dict[str, object] | None = None,
) -> ModelProfile:
    budget = context_budget if context_budget is not None else DEFAULT_BUDGET
    with ProviderConnectionService(path, app_version=APP_VERSION) as conn_service:
        connection = conn_service.create_connection(
            name="local",
            provider_type="openai-compatible",
            endpoint="http://localhost:8080/v1",
            timeout_seconds=30,
            max_retries=0,
            retry_delay_seconds=0.0,
            credential_reference="env:OPENAI_API_KEY",
        )
        assert connection.id is not None
        with ModelProfileService(path, app_version=APP_VERSION) as profile_service:
            profile = profile_service.create_profile(
                name="general",
                provider_connection_id=connection.id,
                model_id="gpt-4o-mini",
                template_version="1.0.0",
                output_protocol="json",
                context_budget=budget,
                default_params={"temperature": 0.3},
                capability=ModelCapability(
                    context_window=128000,
                    max_output_tokens=4096,
                    supports_streaming=False,
                    supports_structured_output=False,
                    supported_parameters={"temperature", "max_tokens"},
                ),
            )
    assert profile.id is not None
    return profile


def _add_glossary(
    path: Path,
    project_id: int,
    entries: list[tuple[str, str, int, bool]],
) -> None:
    """Add (source_term, target_term, priority, is_locked) entries to a project."""
    with GlossaryService(path, app_version=APP_VERSION) as service:
        for source, target, priority, is_locked in entries:
            service.create_entry(
                project_id=project_id,
                source_term=source,
                target_term=target,
                scope="proper-noun",
                priority=priority,
                is_locked=is_locked,
            )


def _valid_response(stable_key: str, translation: str = "こんにちは") -> AdapterResponse:
    content = json.dumps(
        {"items": [{"segment_id": stable_key, "translation": translation}]},
        ensure_ascii=False,
    )
    return AdapterResponse(
        content=content,
        finish_reason="stop",
        usage=AdapterUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        request_id="req-m03",
        raw_response=None,
    )


def _run(coro: Any) -> Any:
    """Run a coroutine in a temporary event loop for tests."""
    return asyncio.run(coro)


def _attempt_summary(path: Path, run_id: int) -> dict[str, object]:
    with TranslationRunService(path, app_version=APP_VERSION) as audit:
        attempts = audit.list_attempts_for_run(run_id)
        assert len(attempts) == 1
        return attempts[0].context_summary


def _entry(
    *,
    source_term: str,
    target_term: str,
    priority: int,
    entry_id: int | None = None,
) -> GlossaryEntry:
    return GlossaryEntry(
        id=entry_id,
        project_id=1,
        source_term=source_term,
        target_term=target_term,
        scope="proper-noun",
        priority=priority,
        is_locked=True,
        origin="user",
        created_at=None,
        updated_at=None,
    )


class TestBuildGlossaryCandidates:
    """The pure mapper produces deterministic, order-preserving candidates."""

    def test_maps_entry_to_candidate(self) -> None:
        candidates = build_glossary_candidates(
            [_entry(source_term="Apple", target_term="苹果", priority=90)],
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.source == ContextSource.LOCKED_GLOSSARY
        assert candidate.segment_id == "glossary:Apple"
        assert candidate.content == "Apple -> 苹果"
        assert candidate.reason == GLOSSARY_REASON
        assert candidate.priority == 90

    def test_preserves_input_order(self) -> None:
        candidates = build_glossary_candidates(
            [
                _entry(source_term="High", target_term="甲", priority=90),
                _entry(source_term="Low", target_term="乙", priority=10),
            ],
        )
        assert [c.content for c in candidates] == ["High -> 甲", "Low -> 乙"]

    def test_empty_entries_returns_empty_list(self) -> None:
        assert build_glossary_candidates([]) == []

    def test_estimate_uses_default_estimator(self) -> None:
        candidates = build_glossary_candidates(
            [_entry(source_term="Apple", target_term="苹果", priority=90)],
            estimate_method=EstimateMethod.CHARACTER,
        )
        content = "Apple -> 苹果"
        estimate = candidates[0].estimate
        assert estimate.char_count == len(content)
        assert estimate.token_count == max(1, len(content) // 4)

    def test_custom_estimator_and_method_respected(self) -> None:
        def estimator(_content: str, method: EstimateMethod) -> BudgetEstimate:
            return BudgetEstimate(
                token_count=7 if method == EstimateMethod.TOKEN else 3,
                char_count=3,
            )

        candidates = build_glossary_candidates(
            [_entry(source_term="Apple", target_term="苹果", priority=90)],
            estimate_method=EstimateMethod.TOKEN,
            estimator=estimator,
        )
        assert candidates[0].estimate.token_count == 7

    def test_metadata_carries_entry_fields(self) -> None:
        candidates = build_glossary_candidates(
            [_entry(source_term="Apple", target_term="苹果", priority=42, entry_id=7)],
        )
        metadata = candidates[0].metadata
        assert metadata["entry_id"] == 7
        assert metadata["source_term"] == "Apple"
        assert metadata["target_term"] == "苹果"
        assert metadata["scope"] == "proper-noun"
        assert metadata["priority"] == 42
        assert metadata["origin"] == "user"


class TestDeterministicInjection:
    """TranslationService injects only the current project's locked glossary."""

    def _setup(self, tmp_path: Path) -> tuple[Path, int, list[Segment], ModelProfile]:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path, name="A")
        segments = _import_txt(path, project_id, "First line.\nSecond line here.\n")
        profile = _create_profile(path)
        assert profile.id is not None
        return path, project_id, segments, profile

    def test_injects_locked_glossary_before_neighbors(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_a = _create_project(path, name="A")
        project_b = _create_project(path, name="B")
        segments = _import_txt(path, project_a, "First line.\nSecond line here.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None

        # Project A: two locked entries (distinct priorities) + one unlocked.
        _add_glossary(
            path,
            project_a,
            [
                ("Alpha", "阿尔法", 90, True),
                ("Beta", "贝塔", 50, True),
                ("Gamma", "伽马", 80, False),
            ],
        )
        # Project B: a locked entry that must never leak into A's prompt.
        _add_glossary(path, project_b, [("Delta", "德尔塔", 90, True)])

        fake = FakeAdapter(_valid_response(segments[0].stable_key))
        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_a)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )

        prompt = fake.last_prompt
        glossary_high = "[locked glossary] Alpha -> 阿尔法"
        glossary_low = "[locked glossary] Beta -> 贝塔"
        neighbor = "[neighbor segment (1 away)] Second line here."
        assert glossary_high in prompt
        assert glossary_low in prompt
        assert prompt.index(glossary_high) < prompt.index(glossary_low)
        assert prompt.index(glossary_low) < prompt.index(neighbor)
        assert "First line." in prompt
        # Unlocked and cross-project entries are not injected.
        assert "Gamma" not in prompt
        assert "Delta" not in prompt

        summary = _attempt_summary(path, run.id)
        selected = summary.get("selected_sources")
        assert isinstance(selected, list)
        assert selected == [
            "CURRENT_SEGMENT",
            "LOCKED_GLOSSARY",
            "LOCKED_GLOSSARY",
            "NEIGHBOR_SEGMENT",
        ]
        assert summary.get("pruned_count") == 0

    def test_same_priority_orders_by_id(self, tmp_path: Path) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path, name="A")
        segments = _import_txt(path, project_id, "First line.\n")
        ids = _ids(segments)
        profile = _create_profile(path)
        assert profile.id is not None
        # Same priority; the stable tiebreak is the creation (id) order.
        _add_glossary(
            path,
            project_id,
            [
                ("Tau", "甲", 50, True),
                ("Upsilon", "乙", 50, True),
            ],
        )

        fake = FakeAdapter(_valid_response(segments[0].stable_key))
        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )

        prompt = fake.last_prompt
        assert prompt.index("[locked glossary] Tau -> 甲") < prompt.index(
            "[locked glossary] Upsilon -> 乙",
        )

    def test_no_locked_entries_adds_no_glossary_source(self, tmp_path: Path) -> None:
        path, project_id, segments, profile = self._setup(tmp_path)
        ids = _ids(segments)
        assert profile.id is not None
        fake = FakeAdapter(_valid_response(segments[0].stable_key))
        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )
        summary = _attempt_summary(path, run.id)
        selected = summary.get("selected_sources")
        assert isinstance(selected, list)
        assert "LOCKED_GLOSSARY" not in selected


class TestBudgetBehavior:
    """Glossary pruning keeps the current segment intact."""

    def test_budget_prunes_low_priority_glossary_without_truncating_current(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path, name="A")
        segments = _import_txt(path, project_id, "Alpha.\n")
        ids = _ids(segments)
        # available = 10 - 2 - 2 = 6. Current "Alpha." estimates 1 token; the
        # high-priority entry fits, the long low-priority entry is pruned.
        profile = _create_profile(
            path,
            context_budget={"total": 10, "reserved_output": 2, "reserved_prompt": 2},
        )
        assert profile.id is not None
        _add_glossary(
            path,
            project_id,
            [
                ("X", "甲", 90, True),
                ("VeryLongTermThatConsumesManyTokens", "乙", 10, True),
            ],
        )

        fake = FakeAdapter(_valid_response(segments[0].stable_key))
        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            revision = _run(
                service.translate_segment(
                    run_id=run.id,
                    segment_id=ids[0],
                    profile_id=profile.id,
                ),
            )
            assert revision.text == "こんにちは"

        prompt = fake.last_prompt
        assert "[locked glossary] X -> 甲" in prompt
        assert "VeryLongTermThatConsumesManyTokens" not in prompt
        assert "Alpha." in prompt

        summary = _attempt_summary(path, run.id)
        selected = summary.get("selected_sources")
        assert isinstance(selected, list)
        assert selected == ["CURRENT_SEGMENT", "LOCKED_GLOSSARY"]
        assert summary.get("pruned_count") == 1

    def test_oversized_current_raises_with_glossary_present(
        self,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "project.sqlite"
        project_id = _create_project(path, name="A")
        segments = _import_txt(
            path,
            project_id,
            "This is a fairly long source line that cannot fit a zero budget.\n",
        )
        ids = _ids(segments)
        profile = _create_profile(
            path,
            context_budget={"total": 4, "reserved_output": 2, "reserved_prompt": 2},
        )
        assert profile.id is not None
        _add_glossary(path, project_id, [("Alpha", "阿尔法", 90, True)])

        fake = FakeAdapter(_valid_response(segments[0].stable_key))
        with TranslationService(path, app_version=APP_VERSION, adapter=fake) as service:
            run = service.create_run(project_id=project_id)
            assert run.id is not None
            with pytest.raises(ContextBudgetError):
                _run(
                    service.translate_segment(
                        run_id=run.id,
                        segment_id=ids[0],
                        profile_id=profile.id,
                    ),
                )
            assert fake.calls == 0


class TestComposerGlossaryNeighborTie:
    """Glossary wins the priority tie against a distance-0 neighbor."""

    def test_glossary_before_same_priority_neighbor(self) -> None:
        current = Segment.create(
            source_document_id=1,
            stable_key="seg-2",
            source_text="B",
            sequence=2,
        )
        same_distance = Segment.create(
            source_document_id=1,
            stable_key="seg-3",
            source_text="C",
            sequence=2,
        )
        glossary = ContextCandidate(
            source=ContextSource.LOCKED_GLOSSARY,
            segment_id="glossary:Alpha",
            content="Alpha -> 阿尔法",
            priority=50,
            reason="locked glossary",
            estimate=BudgetEstimate(char_count=1),
        )
        budget = ContextBudget(
            total_budget=10,
            reserved_output=1,
            reserved_prompt=1,
            estimate_method=EstimateMethod.CHARACTER,
        )
        manifest = ContextComposer().compose(
            profile_id="general",
            template_version="v1",
            current=current,
            neighbors=[same_distance],
            glossary_candidates=[glossary],
            budget=budget,
        )
        sources = [c.source for c in manifest.selected]
        assert sources == [
            ContextSource.CURRENT_SEGMENT,
            ContextSource.LOCKED_GLOSSARY,
            ContextSource.NEIGHBOR_SEGMENT,
        ]
