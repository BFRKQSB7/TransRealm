"""Consistency acceptance tests for P0-T03-M03.

Covers timeout/retry policy boundaries, complex JSON configuration persistence,
and close/reopen consistency across ProviderConnection and ModelProfile.
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.provider_connection_service import (
    ProviderConnectionService,
)
from transrealm.domain.model_profile import ModelCapability, ModelProfile
from transrealm.domain.provider_connection import ProviderConnection
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.model_profile_repository import (
    ModelProfileRepository,
)
from transrealm.infrastructure.repositories.provider_connection_repository import (
    ProviderConnectionRepository,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def connection_service(db_path: Path) -> Generator[ProviderConnectionService, None, None]:
    """Return a connection service with migrations applied."""
    svc = ProviderConnectionService(db_path, app_version="0.1.0")
    try:
        yield svc
    finally:
        svc.close()


class TestTimeoutRetryPolicy:
    """ProviderConnection timeout/retry policy boundary tests."""

    def test_zero_retries_and_delay_allowed(self) -> None:
        """Zero retries and zero delay are valid defaults."""
        conn = ProviderConnection.create(
            name="no-retry",
            provider_type="openai-compatible",
            endpoint="https://api.example.com/v1",
            timeout_seconds=30,
            max_retries=0,
            retry_delay_seconds=0.0,
        )
        assert conn.max_retries == 0
        assert conn.retry_delay_seconds == 0.0

    def test_large_timeout_and_retries_allowed(self) -> None:
        """Large but positive timeout and retry counts are accepted."""
        conn = ProviderConnection.create(
            name="large-policy",
            provider_type="openai-compatible",
            endpoint="https://api.example.com/v1",
            timeout_seconds=3600,
            max_retries=100,
            retry_delay_seconds=60.5,
        )
        assert conn.timeout_seconds == 3600
        assert conn.max_retries == 100
        assert conn.retry_delay_seconds == 60.5

    def test_service_persists_retry_policy(self, db_path: Path) -> None:
        """Retry policy survives close/reopen via the service."""
        svc = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            created = svc.create_connection(
                name="persist-policy",
                provider_type="ollama",
                endpoint="http://localhost:11434/v1",
                timeout_seconds=120,
                max_retries=5,
                retry_delay_seconds=2.5,
            )
            assert created.id is not None
            created_id: int = created.id
        finally:
            svc.close()

        svc2 = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            loaded = svc2.get_connection(created_id)
            assert loaded is not None
            assert loaded.timeout_seconds == 120
            assert loaded.max_retries == 5
            assert loaded.retry_delay_seconds == 2.5
        finally:
            svc2.close()

    def test_update_retry_policy(self, connection_service: ProviderConnectionService) -> None:
        """Retry policy can be updated independently."""
        created = connection_service.create_connection(
            name="update-policy",
            provider_type="openai-compatible",
            endpoint="https://api.example.com/v1",
            timeout_seconds=30,
            max_retries=0,
        )
        assert created.id is not None
        created_id: int = created.id
        updated = connection_service.update_connection(
            created_id,
            timeout_seconds=60,
            max_retries=3,
            retry_delay_seconds=1.0,
        )
        assert updated.timeout_seconds == 60
        assert updated.max_retries == 3
        assert updated.retry_delay_seconds == 1.0


class TestJsonConfigurationPersistence:
    """ModelProfile JSON field persistence boundaries."""

    COMPLEX_BUDGET: dict[str, object] = {
        "max_context_tokens": 4096,
        "reserved_output_tokens": 512,
        "nested": {
            "enabled": True,
            "ratio": 0.75,
            "tags": ["system", "user"],
        },
        "items": [
            {"priority": 1, "source": "current_segment", "required": True},
            {"priority": 2, "source": "glossary", "required": False, "meta": None},
        ],
        "flag": False,
        "null_value": None,
    }

    COMPLEX_PARAMS: dict[str, object] = {
        "temperature": 0.3,
        "max_tokens": 256,
        "top_p": 0.95,
        "extra": {
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "stop": ["\n", "###"],
        },
    }

    def _create_connection(self, db_path: Path) -> int:
        """Create a provider connection and return its id."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        repo = ProviderConnectionRepository(db)
        saved = repo.save(
            ProviderConnection.create(
                name="json-conn",
                provider_type="openai-compatible",
                endpoint="https://api.example.com/v1",
            ),
        )
        repo.close()
        assert saved.id is not None
        return saved.id

    def test_complex_json_round_trip(self, db_path: Path) -> None:
        """Nested JSON values survive persistence unchanged."""
        connection_id = self._create_connection(db_path)
        db = create_database(db_path)
        repo = ModelProfileRepository(db)

        cap = ModelCapability(
            context_window=8192,
            max_output_tokens=1024,
            supports_streaming=True,
            supports_structured_output=False,
            supported_parameters={"temperature", "max_tokens", "top_p"},
        )
        profile = ModelProfile.create(
            name="complex-json",
            provider_connection_id=connection_id,
            model_id="model-x",
            template_version="1.0",
            output_protocol="json",
            context_budget=self.COMPLEX_BUDGET,
            default_params=self.COMPLEX_PARAMS,
            capability=cap,
        )
        saved = repo.save(profile)
        assert saved.id is not None
        saved_id: int = saved.id
        assert saved.context_budget == self.COMPLEX_BUDGET
        assert saved.default_params == self.COMPLEX_PARAMS
        assert saved.capability_snapshot == cap.to_snapshot()

        loaded = repo.get_by_id(saved_id)
        assert loaded is not None
        assert loaded.context_budget == self.COMPLEX_BUDGET
        assert loaded.default_params == self.COMPLEX_PARAMS
        params = loaded.get_capability().supported_parameters
        assert params == {"temperature", "max_tokens", "top_p"}
        repo.close()

    def test_partial_json_update_does_not_lose_other_fields(self, db_path: Path) -> None:
        """Updating one JSON field preserves the others."""
        connection_id = self._create_connection(db_path)
        db = create_database(db_path)
        repo = ModelProfileRepository(db)

        saved = repo.save(
            ModelProfile.create(
                name="partial-update",
                provider_connection_id=connection_id,
                model_id="model-a",
                template_version="1.0",
                output_protocol="json",
                context_budget={"max_context": 2048},
                default_params={"temperature": 0.3},
            ),
        )
        updated = saved.with_updated_fields(default_params={"temperature": 0.5})
        re_saved = repo.save(updated)

        assert re_saved.context_budget == {"max_context": 2048}
        assert re_saved.default_params == {"temperature": 0.5}
        repo.close()


class TestCloseReopenConsistency:
    """Cross-service close/reopen consistency acceptance."""

    def test_connection_and_profile_survive_reopen(self, db_path: Path) -> None:
        """A connection and its referenced profile are consistent after reopen."""
        conn_svc = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            conn = conn_svc.create_connection(
                name="reopen-conn",
                provider_type="llama.cpp",
                endpoint="http://localhost:8080/v1",
                timeout_seconds=90,
                max_retries=2,
                retry_delay_seconds=1.0,
            )
            assert conn.id is not None
            conn_id: int = conn.id
        finally:
            conn_svc.close()

        profile_svc = ModelProfileService(db_path, app_version="0.1.0")
        try:
            cap = ModelCapability(
                context_window=4096,
                max_output_tokens=512,
                supports_streaming=False,
                supports_structured_output=True,
                supported_parameters={"temperature"},
            )
            profile = profile_svc.create_profile(
                name="reopen-profile",
                provider_connection_id=conn_id,
                model_id="model-y",
                template_version="2.0",
                output_protocol="json",
                context_budget={"max_context": 2048},
                default_params={"temperature": 0.2},
                capability=cap,
            )
            assert profile.id is not None
            profile_id: int = profile.id
        finally:
            profile_svc.close()

        conn_svc2 = ProviderConnectionService(db_path, app_version="0.1.0")
        profile_svc2 = ModelProfileService(db_path, app_version="0.1.0")
        try:
            loaded_conn = conn_svc2.get_connection(conn_id)
            loaded_profile = profile_svc2.get_profile(profile_id)
            assert loaded_conn is not None
            assert loaded_profile is not None
            assert loaded_conn.name == "reopen-conn"
            assert loaded_conn.timeout_seconds == 90
            assert loaded_conn.max_retries == 2
            assert loaded_conn.retry_delay_seconds == 1.0
            assert loaded_profile.name == "reopen-profile"
            assert loaded_profile.provider_connection_id == conn_id
            assert loaded_profile.model_id == "model-y"
            assert loaded_profile.template_version == "2.0"
            assert loaded_profile.context_budget == {"max_context": 2048}
            assert loaded_profile.default_params == {"temperature": 0.2}
            assert loaded_profile.get_capability().context_window == 4096
        finally:
            conn_svc2.close()
            profile_svc2.close()

    def test_connection_update_preserves_profile_reference(self, db_path: Path) -> None:
        """Updating a connection does not break profiles that reference it."""
        conn_svc = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            conn = conn_svc.create_connection(
                name="stable-ref",
                provider_type="openai-compatible",
                endpoint="https://api.example.com/v1",
                timeout_seconds=30,
            )
            assert conn.id is not None
            conn_id: int = conn.id
        finally:
            conn_svc.close()

        profile_svc = ModelProfileService(db_path, app_version="0.1.0")
        try:
            profile = profile_svc.create_profile(
                name="stable-profile",
                provider_connection_id=conn_id,
                model_id="model-z",
                template_version="1.0",
                output_protocol="json",
            )
            assert profile.id is not None
            profile_id: int = profile.id
        finally:
            profile_svc.close()

        conn_svc2 = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            conn_svc2.update_connection(conn_id, timeout_seconds=60)
        finally:
            conn_svc2.close()

        profile_svc2 = ModelProfileService(db_path, app_version="0.1.0")
        try:
            loaded = profile_svc2.get_profile(profile_id)
            assert loaded is not None
            assert loaded.provider_connection_id == conn_id
            assert loaded.model_id == "model-z"
        finally:
            profile_svc2.close()

        conn_svc3 = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            assert conn_svc3.get_connection(conn_id) is not None
        finally:
            conn_svc3.close()

    def test_multiple_profiles_share_one_connection(self, db_path: Path) -> None:
        """Many profiles can reference the same connection."""
        conn_svc = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            conn = conn_svc.create_connection(
                name="shared",
                provider_type="ollama",
                endpoint="http://localhost:11434/v1",
            )
            assert conn.id is not None
            conn_id: int = conn.id
        finally:
            conn_svc.close()

        profile_svc = ModelProfileService(db_path, app_version="0.1.0")
        try:
            profile_svc.create_profile(
                name="shared-a",
                provider_connection_id=conn_id,
                model_id="model-a",
                template_version="1.0",
                output_protocol="json",
            )
            profile_svc.create_profile(
                name="shared-b",
                provider_connection_id=conn_id,
                model_id="model-b",
                template_version="1.0",
                output_protocol="json",
            )
            names = {p.name for p in profile_svc.list_profiles_by_connection(conn_id)}
            assert names == {"shared-a", "shared-b"}
        finally:
            profile_svc.close()

        profile_svc2 = ModelProfileService(db_path, app_version="0.1.0")
        try:
            loaded = profile_svc2.list_profiles_by_connection(conn_id)
            assert {p.name for p in loaded} == {"shared-a", "shared-b"}
        finally:
            profile_svc2.close()

    def test_profile_update_refreshes_capability_snapshot(self, db_path: Path) -> None:
        """Updating a profile with a new capability refreshes the snapshot."""
        conn_svc = ProviderConnectionService(db_path, app_version="0.1.0")
        try:
            conn = conn_svc.create_connection(
                name="cap-snapshot-conn",
                provider_type="openai-compatible",
                endpoint="https://api.example.com/v1",
            )
            assert conn.id is not None
            conn_id: int = conn.id
        finally:
            conn_svc.close()

        profile_svc = ModelProfileService(db_path, app_version="0.1.0")
        try:
            cap1 = ModelCapability(
                context_window=4096,
                max_output_tokens=512,
                supports_streaming=False,
                supports_structured_output=False,
                supported_parameters=set(),
            )
            created = profile_svc.create_profile(
                name="cap-snapshot",
                provider_connection_id=conn_id,
                model_id="model",
                template_version="1.0",
                output_protocol="json",
                capability=cap1,
            )
            cap2 = ModelCapability(
                context_window=8192,
                max_output_tokens=1024,
                supports_streaming=True,
                supports_structured_output=True,
                supported_parameters={"temperature"},
            )
            assert created.id is not None
            created_id: int = created.id
            updated = profile_svc.update_profile(
                created_id,
                capability=cap2,
            )
            assert updated.get_capability().context_window == 8192
            assert updated.get_capability().supported_parameters == {"temperature"}
        finally:
            profile_svc.close()
