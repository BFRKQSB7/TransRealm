"""Tests for Model Capability and Model Profile domain model, repository and service."""

from collections.abc import Generator
from pathlib import Path

import pytest

from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.provider_connection_service import (
    ProviderConnectionService,
)
from transrealm.domain.model_profile import (
    ModelCapability,
    ModelCapabilityError,
    ModelProfile,
    ModelProfileError,
)
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.model_profile_repository import (
    ModelProfileRepository,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def profile_service(db_path: Path) -> Generator[ModelProfileService, None, None]:
    """Return a profile service with migrations applied."""
    svc = ModelProfileService(db_path, app_version="0.1.0")
    try:
        yield svc
    finally:
        svc.close()


@pytest.fixture
def connection_service(db_path: Path) -> Generator[ProviderConnectionService, None, None]:
    """Return a connection service with migrations applied."""
    svc = ProviderConnectionService(db_path, app_version="0.1.0")
    try:
        yield svc
    finally:
        svc.close()


class TestModelCapability:
    """Domain-level capability tests."""

    def test_create_minimal_capability(self) -> None:
        """A minimal capability can be created."""
        cap = ModelCapability(
            context_window=4096,
            max_output_tokens=512,
            supports_streaming=False,
            supports_structured_output=True,
        )
        assert cap.context_window == 4096
        assert cap.max_output_tokens == 512
        assert cap.supports_streaming is False
        assert cap.supports_structured_output is True
        assert cap.supported_parameters == set()

    def test_create_with_supported_parameters(self) -> None:
        """Supported parameters are stored as a set."""
        cap = ModelCapability(
            context_window=8192,
            max_output_tokens=1024,
            supports_streaming=True,
            supports_structured_output=False,
            supported_parameters={"temperature", "max_tokens"},
        )
        assert cap.supported_parameters == {"temperature", "max_tokens"}

    def test_rejects_non_positive_context_window(self) -> None:
        """Context window must be positive."""
        with pytest.raises(ModelCapabilityError):
            ModelCapability(
                context_window=0,
                max_output_tokens=512,
                supports_streaming=False,
                supports_structured_output=False,
            )

    def test_rejects_non_positive_max_output_tokens(self) -> None:
        """Max output tokens must be positive."""
        with pytest.raises(ModelCapabilityError):
            ModelCapability(
                context_window=4096,
                max_output_tokens=-1,
                supports_streaming=False,
                supports_structured_output=False,
            )

    def test_rejects_non_boolean_streaming(self) -> None:
        """Streaming flag must be a boolean."""
        with pytest.raises(ModelCapabilityError):
            ModelCapability(
                context_window=4096,
                max_output_tokens=512,
                supports_streaming="yes",  # type: ignore[arg-type]
                supports_structured_output=False,
            )

    def test_snapshot_round_trip(self) -> None:
        """Snapshot serializes and deserializes correctly."""
        cap = ModelCapability(
            context_window=4096,
            max_output_tokens=512,
            supports_streaming=True,
            supports_structured_output=True,
            supported_parameters={"temperature", "top_p"},
        )
        snapshot = cap.to_snapshot()
        restored = ModelCapability.from_snapshot(snapshot)
        assert restored.context_window == cap.context_window
        assert restored.max_output_tokens == cap.max_output_tokens
        assert restored.supports_streaming == cap.supports_streaming
        assert restored.supports_structured_output == cap.supports_structured_output
        assert restored.supported_parameters == cap.supported_parameters

    def test_from_snapshot_rejects_non_object(self) -> None:
        """Snapshot must be a dict."""
        with pytest.raises(ModelCapabilityError):
            ModelCapability.from_snapshot("invalid")


class TestModelProfileValidation:
    """Domain-level profile validation tests."""

    def test_create_minimal_profile(self) -> None:
        """A minimal valid profile can be created."""
        profile = ModelProfile.create(
            name="general",
            provider_connection_id=1,
            model_id="gpt-4o-mini",
            template_version="1.0",
            output_protocol="json",
        )
        assert profile.id is None
        assert profile.name == "general"
        assert profile.provider_connection_id == 1
        assert profile.model_id == "gpt-4o-mini"
        assert profile.template_version == "1.0"
        assert profile.output_protocol == "json"
        assert profile.context_budget == {}
        assert profile.default_params == {}
        assert profile.capability_snapshot == {}

    def test_create_with_capability(self) -> None:
        """Capability is embedded as a snapshot."""
        cap = ModelCapability(
            context_window=8192,
            max_output_tokens=1024,
            supports_streaming=True,
            supports_structured_output=False,
            supported_parameters={"temperature"},
        )
        profile = ModelProfile.create(
            name="sakura",
            provider_connection_id=2,
            model_id="sakura-v1",
            template_version="2.1",
            output_protocol="json",
            capability=cap,
        )
        assert profile.capability_snapshot == cap.to_snapshot()
        assert profile.get_capability().context_window == 8192

    def test_get_capability_requires_non_empty_snapshot(self) -> None:
        """get_capability raises when no capability snapshot was stored."""
        profile = ModelProfile.create(
            name="no-cap",
            provider_connection_id=1,
            model_id="x",
            template_version="1.0",
            output_protocol="json",
        )
        with pytest.raises(ModelCapabilityError):
            profile.get_capability()

    def test_create_rejects_empty_name(self) -> None:
        """Profile name is required."""
        with pytest.raises(ModelProfileError):
            ModelProfile.create(
                name="",
                provider_connection_id=1,
                model_id="x",
                template_version="1.0",
                output_protocol="json",
            )

    def test_create_rejects_invalid_connection_id(self) -> None:
        """Provider connection id must be a positive integer."""
        with pytest.raises(ModelProfileError):
            ModelProfile.create(
                name="x",
                provider_connection_id=0,
                model_id="x",
                template_version="1.0",
                output_protocol="json",
            )

    def test_create_rejects_empty_model_id(self) -> None:
        """Model id is required."""
        with pytest.raises(ModelProfileError):
            ModelProfile.create(
                name="x",
                provider_connection_id=1,
                model_id="   ",
                template_version="1.0",
                output_protocol="json",
            )

    def test_create_rejects_empty_template_version(self) -> None:
        """Template version is required."""
        with pytest.raises(ModelProfileError):
            ModelProfile.create(
                name="x",
                provider_connection_id=1,
                model_id="x",
                template_version="",
                output_protocol="json",
            )

    def test_create_rejects_empty_output_protocol(self) -> None:
        """Output protocol is required."""
        with pytest.raises(ModelProfileError):
            ModelProfile.create(
                name="x",
                provider_connection_id=1,
                model_id="x",
                template_version="1.0",
                output_protocol="",
            )

    def test_create_rejects_non_dict_json_fields(self) -> None:
        """JSON fields must be dicts."""
        with pytest.raises(ModelProfileError):
            ModelProfile.create(
                name="x",
                provider_connection_id=1,
                model_id="x",
                template_version="1.0",
                output_protocol="json",
                context_budget="invalid",  # type: ignore[arg-type]
            )

    def test_create_rejects_non_serializable_json_fields(self) -> None:
        """JSON fields must be serializable."""
        with pytest.raises(ModelProfileError):
            ModelProfile.create(
                name="x",
                provider_connection_id=1,
                model_id="x",
                template_version="1.0",
                output_protocol="json",
                default_params={"obj": object()},  # type: ignore[dict-item]
            )


class TestModelProfileRepository:
    """Repository round-trip and constraint tests."""

    def _create_connection(self, db_path: Path) -> int:
        """Create a provider connection and return its id."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        from transrealm.domain.provider_connection import ProviderConnection
        from transrealm.infrastructure.repositories.provider_connection_repository import (
            ProviderConnectionRepository,
        )

        repo = ProviderConnectionRepository(db)
        saved = repo.save(
            ProviderConnection.create(
                name="conn",
                provider_type="openai-compatible",
                endpoint="https://api.example.com/v1",
            ),
        )
        repo.close()
        assert saved.id is not None
        return saved.id

    def test_save_inserts_new_profile(self, db_path: Path) -> None:
        """A new profile is inserted and returned with id/timestamps."""
        connection_id = self._create_connection(db_path)
        db = create_database(db_path)
        repo = ModelProfileRepository(db)

        cap = ModelCapability(
            context_window=4096,
            max_output_tokens=512,
            supports_streaming=False,
            supports_structured_output=True,
            supported_parameters={"temperature"},
        )
        profile = ModelProfile.create(
            name="general",
            provider_connection_id=connection_id,
            model_id="gpt-4o-mini",
            template_version="1.0",
            output_protocol="json",
            context_budget={"max_context": 2048},
            default_params={"temperature": 0.3},
            capability=cap,
        )
        saved = repo.save(profile)

        assert saved.id is not None
        assert saved.name == "general"
        assert saved.provider_connection_id == connection_id
        assert saved.model_id == "gpt-4o-mini"
        assert saved.template_version == "1.0"
        assert saved.output_protocol == "json"
        assert saved.context_budget == {"max_context": 2048}
        assert saved.default_params == {"temperature": 0.3}
        assert saved.capability_snapshot == cap.to_snapshot()
        assert saved.created_at is not None
        assert saved.updated_at is not None

        loaded = repo.get_by_id(saved.id)
        assert loaded is not None
        assert loaded.name == "general"
        assert loaded.get_capability().supported_parameters == {"temperature"}
        repo.close()

    def test_save_updates_existing_profile(self, db_path: Path) -> None:
        """Saving a profile with an id updates it."""
        connection_id = self._create_connection(db_path)
        db = create_database(db_path)
        repo = ModelProfileRepository(db)

        saved = repo.save(
            ModelProfile.create(
                name="profile",
                provider_connection_id=connection_id,
                model_id="model-a",
                template_version="1.0",
                output_protocol="json",
            ),
        )
        updated = saved.with_updated_fields(model_id="model-b")
        re_saved = repo.save(updated)

        assert re_saved.id == saved.id
        assert re_saved.model_id == "model-b"
        assert saved.updated_at is not None
        assert re_saved.updated_at is not None
        assert re_saved.updated_at >= saved.updated_at
        repo.close()

    def test_foreign_key_enforced(self, db_path: Path) -> None:
        """Profiles cannot reference non-existent provider connections."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        repo = ModelProfileRepository(db)

        profile = ModelProfile.create(
            name="orphan",
            provider_connection_id=9999,
            model_id="x",
            template_version="1.0",
            output_protocol="json",
        )
        with pytest.raises(Exception):  # IntegrityError wrapped by our layer
            repo.save(profile)
        repo.close()

    def test_delete_profile(self, db_path: Path) -> None:
        """Delete removes the profile and returns True iff a row existed."""
        connection_id = self._create_connection(db_path)
        db = create_database(db_path)
        repo = ModelProfileRepository(db)

        saved = repo.save(
            ModelProfile.create(
                name="to-delete",
                provider_connection_id=connection_id,
                model_id="x",
                template_version="1.0",
                output_protocol="json",
            ),
        )
        assert saved.id is not None
        assert repo.delete(saved.id) is True
        assert repo.get_by_id(saved.id) is None
        assert repo.delete(9999) is False
        repo.close()


class TestModelProfileService:
    """Application service integration tests."""

    def test_service_creates_and_reopens_profile(
        self,
        db_path: Path,
        connection_service: ProviderConnectionService,
    ) -> None:
        """A profile created by the service can be reopened."""
        conn = connection_service.create_connection(
            name="svc-conn",
            provider_type="openai-compatible",
            endpoint="https://api.example.com/v1",
        )
        assert conn.id is not None
        conn_id: int = conn.id

        profile_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            cap = ModelCapability(
                context_window=4096,
                max_output_tokens=512,
                supports_streaming=False,
                supports_structured_output=True,
                supported_parameters={"temperature"},
            )
            created = profile_service.create_profile(
                name="svc-profile",
                provider_connection_id=conn_id,
                model_id="gpt-4o-mini",
                template_version="1.0",
                output_protocol="json",
                context_budget={"max_context": 2048},
                default_params={"temperature": 0.3},
                capability=cap,
            )
            assert created.id is not None
            created_id: int = created.id
        finally:
            profile_service.close()

        new_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            loaded = new_service.get_profile(created_id)
            assert loaded is not None
            assert loaded.name == "svc-profile"
            assert loaded.provider_connection_id == conn_id
            assert loaded.model_id == "gpt-4o-mini"
            assert loaded.context_budget == {"max_context": 2048}
            assert loaded.default_params == {"temperature": 0.3}
            assert loaded.get_capability().supported_parameters == {"temperature"}
        finally:
            new_service.close()

    def test_service_update_profile(
        self,
        db_path: Path,
        connection_service: ProviderConnectionService,
    ) -> None:
        """The service can update a persisted profile."""
        conn = connection_service.create_connection(
            name="update-conn",
            provider_type="ollama",
            endpoint="http://localhost:11434/v1",
        )
        assert conn.id is not None
        conn_id: int = conn.id
        profile_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            created = profile_service.create_profile(
                name="update-me",
                provider_connection_id=conn_id,
                model_id="model-a",
                template_version="1.0",
                output_protocol="json",
            )
            assert created.id is not None
            created_id: int = created.id
            updated = profile_service.update_profile(
                created_id,
                model_id="model-b",
                default_params={"temperature": 0.5},
            )
            assert updated.model_id == "model-b"
            assert updated.default_params == {"temperature": 0.5}
            assert updated.name == "update-me"
        finally:
            profile_service.close()

    def test_service_update_missing_profile_raises(
        self,
        db_path: Path,
        connection_service: ProviderConnectionService,
    ) -> None:
        """Updating a non-existent profile raises an error."""
        profile_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            with pytest.raises(ModelProfileError):
                profile_service.update_profile(9999, model_id="x")
        finally:
            profile_service.close()

    def test_service_rejects_missing_connection(
        self,
        db_path: Path,
    ) -> None:
        """Creating a profile referencing a missing connection raises an error."""
        profile_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            with pytest.raises(ModelProfileError):
                profile_service.create_profile(
                    name="orphan",
                    provider_connection_id=9999,
                    model_id="x",
                    template_version="1.0",
                    output_protocol="json",
                )
        finally:
            profile_service.close()

    def test_service_list_and_delete(
        self,
        db_path: Path,
        connection_service: ProviderConnectionService,
    ) -> None:
        """List returns all profiles; delete removes one."""
        conn = connection_service.create_connection(
            name="list-conn",
            provider_type="llama.cpp",
            endpoint="http://localhost:8080/v1",
        )
        assert conn.id is not None
        conn_id: int = conn.id
        profile_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            a = profile_service.create_profile(
                name="a",
                provider_connection_id=conn_id,
                model_id="model-a",
                template_version="1.0",
                output_protocol="json",
            )
            assert a.id is not None
            a_id: int = a.id
            profile_service.create_profile(
                name="b",
                provider_connection_id=conn_id,
                model_id="model-b",
                template_version="1.0",
                output_protocol="json",
            )
            assert {p.name for p in profile_service.list_profiles()} == {"a", "b"}

            assert profile_service.delete_profile(a_id) is True
            assert {p.name for p in profile_service.list_profiles()} == {"b"}
            assert profile_service.delete_profile(a_id) is False
        finally:
            profile_service.close()

    def test_service_blocks_connection_delete_when_referenced(
        self,
        db_path: Path,
        connection_service: ProviderConnectionService,
    ) -> None:
        """Deleting a referenced connection is blocked by the foreign key."""
        conn = connection_service.create_connection(
            name="referenced",
            provider_type="openai-compatible",
            endpoint="https://api.example.com/v1",
        )
        assert conn.id is not None
        conn_id: int = conn.id
        profile_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            profile_service.create_profile(
                name="bound",
                provider_connection_id=conn_id,
                model_id="x",
                template_version="1.0",
                output_protocol="json",
            )
            with pytest.raises(Exception):
                connection_service.delete_connection(conn_id)
        finally:
            profile_service.close()

    def test_service_validates_on_create(
        self,
        db_path: Path,
        connection_service: ProviderConnectionService,
    ) -> None:
        """Invalid input is rejected before touching the database."""
        conn = connection_service.create_connection(
            name="validate-conn",
            provider_type="openai-compatible",
            endpoint="https://api.example.com/v1",
        )
        assert conn.id is not None
        conn_id: int = conn.id
        profile_service = ModelProfileService(db_path, app_version="0.1.0")
        try:
            with pytest.raises(ModelProfileError):
                profile_service.create_profile(
                    name="bad",
                    provider_connection_id=conn_id,
                    model_id="",
                    template_version="1.0",
                    output_protocol="json",
                )
        finally:
            profile_service.close()
