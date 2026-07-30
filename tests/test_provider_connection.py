"""Tests for Provider Connection domain model, repository and service."""

from collections.abc import Generator
from pathlib import Path

import pytest

from transrealm.application.provider_connection_service import ProviderConnectionService
from transrealm.domain.provider_connection import ProviderConnection, ProviderConnectionError
from transrealm.infrastructure.database import create_database
from transrealm.infrastructure.repositories.provider_connection_repository import (
    ProviderConnectionRepository,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def service(db_path: Path) -> Generator[ProviderConnectionService, None, None]:
    """Return a service with migrations applied."""
    svc = ProviderConnectionService(db_path, app_version="0.1.0")
    try:
        yield svc
    finally:
        svc.close()


class TestProviderConnectionValidation:
    """Domain-level validation and secret boundary tests."""

    def test_create_minimal_connection(self) -> None:
        """A minimal valid connection can be created."""
        conn = ProviderConnection.create(
            name="local-llama",
            provider_type="llama.cpp",
            endpoint="http://localhost:8080/v1/chat/completions",
        )
        assert conn.id is None
        assert conn.name == "local-llama"
        assert conn.provider_type == "llama.cpp"
        assert conn.endpoint == "http://localhost:8080/v1/chat/completions"
        assert conn.timeout_seconds == 30
        assert conn.max_retries == 0
        assert conn.retry_delay_seconds == 0.0
        assert conn.credential_reference is None

    def test_create_with_env_credential_reference(self) -> None:
        """A connection may reference an environment variable."""
        conn = ProviderConnection.create(
            name="openai",
            provider_type="openai-compatible",
            endpoint="https://api.openai.com/v1",
            credential_reference="env:OPENAI_API_KEY",
        )
        assert conn.credential_reference == "env:OPENAI_API_KEY"

    def test_create_with_wincred_credential_reference(self) -> None:
        """A connection may reference Windows Credential Manager."""
        conn = ProviderConnection.create(
            name="work-openai",
            provider_type="openai-compatible",
            endpoint="https://api.openai.com/v1",
            credential_reference="wincred:TransRealm/Work/OpenAI",
        )
        assert conn.credential_reference == "wincred:TransRealm/Work/OpenAI"

    def test_create_rejects_empty_name(self) -> None:
        """Connection name is required."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
            )

    def test_create_rejects_whitespace_name(self) -> None:
        """Whitespace-only names are rejected."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="   ",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
            )

    def test_create_rejects_unsupported_provider(self) -> None:
        """Only supported provider types are accepted."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="x",
                provider_type="unknown-provider",
                endpoint="https://example.com/v1",
            )

    @pytest.mark.parametrize(
        "endpoint",
        [
            "ftp://api.openai.com/v1",
            "not-a-url",
            "http://",
            "https://",
            "",
        ],
    )
    def test_create_rejects_invalid_endpoint(self, endpoint: str) -> None:
        """Endpoint must be an HTTP/HTTPS URL with a host."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="x",
                provider_type="openai-compatible",
                endpoint=endpoint,
            )

    def test_create_rejects_non_positive_timeout(self) -> None:
        """Timeout must be positive."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="x",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
                timeout_seconds=0,
            )

    def test_create_rejects_negative_retries(self) -> None:
        """Retries must be non-negative."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="x",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
                max_retries=-1,
            )

    def test_create_rejects_negative_retry_delay(self) -> None:
        """Retry delay must be non-negative."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="x",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
                retry_delay_seconds=-0.5,
            )

    def test_create_rejects_empty_credential_reference(self) -> None:
        """Empty credential reference is treated as invalid."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="x",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
                credential_reference="",
            )

    @pytest.mark.parametrize(
        "reference",
        [
            "sk-1234567890abcdef",  # raw API key
            "Bearer sk-1234567890abcdef",
            "file:/secrets/key.txt",
            "env:",  # missing variable name
            "env:123_INVALID",
            "wincred:",  # missing target
            "wincred:NoSlash",
        ],
    )
    def test_create_rejects_secret_like_credential_reference(self, reference: str) -> None:
        """Raw secrets and malformed references are rejected at the boundary."""
        with pytest.raises(ProviderConnectionError):
            ProviderConnection.create(
                name="x",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
                credential_reference=reference,
            )


class TestProviderConnectionRepository:
    """Repository round-trip and constraint tests."""

    def test_save_inserts_new_connection(self, db_path: Path) -> None:
        """A new connection is inserted and returned with id/timestamps."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        repo = ProviderConnectionRepository(db)

        conn = ProviderConnection.create(
            name="local",
            provider_type="llama.cpp",
            endpoint="http://localhost:8080/v1",
            timeout_seconds=60,
            max_retries=2,
            retry_delay_seconds=1.5,
            credential_reference="env:LLAMA_API_KEY",
        )
        saved = repo.save(conn)

        assert saved.id is not None
        assert saved.name == "local"
        assert saved.created_at is not None
        assert saved.updated_at is not None

        loaded = repo.get_by_id(saved.id)
        assert loaded is not None
        assert loaded.name == "local"
        assert loaded.provider_type == "llama.cpp"
        assert loaded.endpoint == "http://localhost:8080/v1"
        assert loaded.timeout_seconds == 60
        assert loaded.max_retries == 2
        assert loaded.retry_delay_seconds == 1.5
        assert loaded.credential_reference == "env:LLAMA_API_KEY"
        repo.close()

    def test_save_updates_existing_connection(self, db_path: Path) -> None:
        """Saving a connection with an id updates it."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        repo = ProviderConnectionRepository(db)

        saved = repo.save(
            ProviderConnection.create(
                name="conn",
                provider_type="ollama",
                endpoint="http://localhost:11434/v1",
            ),
        )
        assert saved.id is not None
        updated = saved.with_updated_fields(endpoint="http://127.0.0.1:11434/v1")
        re_saved = repo.save(updated)

        assert re_saved.id == saved.id
        assert re_saved.endpoint == "http://127.0.0.1:11434/v1"
        assert re_saved.updated_at is not None
        assert saved.updated_at is not None
        assert re_saved.updated_at >= saved.updated_at
        repo.close()

    def test_unique_name_constraint(self, db_path: Path) -> None:
        """Duplicate connection names are rejected by the database."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        repo = ProviderConnectionRepository(db)

        repo.save(
            ProviderConnection.create(
                name="dup",
                provider_type="ollama",
                endpoint="http://localhost:11434/v1",
            ),
        )
        with pytest.raises(Exception):  # IntegrityError wrapped by our layer
            repo.save(
                ProviderConnection.create(
                    name="dup",
                    provider_type="openai-compatible",
                    endpoint="https://api.openai.com/v1",
                ),
            )
        repo.close()

    def test_get_by_name(self, db_path: Path) -> None:
        """Connections can be fetched by name."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        repo = ProviderConnectionRepository(db)

        repo.save(
            ProviderConnection.create(
                name="by-name",
                provider_type="llama.cpp",
                endpoint="http://localhost:8080/v1",
            ),
        )
        found = repo.get_by_name("by-name")
        assert found is not None
        assert found.name == "by-name"
        assert repo.get_by_name("missing") is None
        repo.close()

    def test_delete_connection(self, db_path: Path) -> None:
        """Delete removes the connection and returns True iff a row existed."""
        migrations_dir = Path(__file__).parents[1] / "src" / "transrealm" / "migrations"
        from transrealm.infrastructure.migrations.runner import run_migrations

        run_migrations(db_path, migrations_dir, app_version="0.1.0")
        db = create_database(db_path)
        repo = ProviderConnectionRepository(db)

        saved = repo.save(
            ProviderConnection.create(
                name="to-delete",
                provider_type="ollama",
                endpoint="http://localhost:11434/v1",
            ),
        )
        assert saved.id is not None
        assert repo.delete(saved.id) is True
        assert repo.get_by_id(saved.id) is None
        assert repo.delete(9999) is False
        repo.close()


class TestProviderConnectionService:
    """Application service integration tests."""

    def test_service_creates_and_reopens_connection(
        self,
        service: ProviderConnectionService,
    ) -> None:
        """A connection created by the service can be reopened."""
        created = service.create_connection(
            name="svc-conn",
            provider_type="openai-compatible",
            endpoint="https://api.openai.com/v1",
            timeout_seconds=45,
            max_retries=3,
            retry_delay_seconds=2.0,
            credential_reference="env:SVC_API_KEY",
        )
        assert created.id is not None

        service.close()
        new_service = ProviderConnectionService(
            service._db_path,
            app_version="0.1.0",
        )
        try:
            loaded = new_service.get_connection_by_name("svc-conn")
            assert loaded is not None
            assert loaded.provider_type == "openai-compatible"
            assert loaded.timeout_seconds == 45
            assert loaded.max_retries == 3
            assert loaded.retry_delay_seconds == 2.0
            assert loaded.credential_reference == "env:SVC_API_KEY"
        finally:
            new_service.close()

    def test_service_update_connection(self, service: ProviderConnectionService) -> None:
        """The service can update a persisted connection."""
        created = service.create_connection(
            name="update-me",
            provider_type="ollama",
            endpoint="http://localhost:11434/v1",
        )
        assert created.id is not None
        updated = service.update_connection(
            created.id,
            endpoint="http://127.0.0.1:11434/v1",
            max_retries=1,
        )
        assert updated.endpoint == "http://127.0.0.1:11434/v1"
        assert updated.max_retries == 1
        assert updated.provider_type == "ollama"

    def test_service_update_missing_connection_raises(
        self,
        service: ProviderConnectionService,
    ) -> None:
        """Updating a non-existent connection raises an error."""
        with pytest.raises(ProviderConnectionError):
            service.update_connection(9999, endpoint="http://example.com/v1")

    def test_service_list_and_delete(self, service: ProviderConnectionService) -> None:
        """List returns all connections; delete removes one."""
        a = service.create_connection(
            name="a",
            provider_type="ollama",
            endpoint="http://localhost:11434/v1",
        )
        assert a.id is not None
        service.create_connection(
            name="b",
            provider_type="llama.cpp",
            endpoint="http://localhost:8080/v1",
        )
        assert {c.name for c in service.list_connections()} == {"a", "b"}

        assert service.delete_connection(a.id) is True
        assert {c.name for c in service.list_connections()} == {"b"}
        assert service.delete_connection(a.id) is False

    def test_service_validates_on_create(self, service: ProviderConnectionService) -> None:
        """Invalid input is rejected before touching the database."""
        with pytest.raises(ProviderConnectionError):
            service.create_connection(
                name="bad",
                provider_type="openai-compatible",
                endpoint="not-a-url",
            )

    def test_service_validates_secret_boundary(self, service: ProviderConnectionService) -> None:
        """Raw secrets are rejected by the service boundary."""
        with pytest.raises(ProviderConnectionError):
            service.create_connection(
                name="leak",
                provider_type="openai-compatible",
                endpoint="https://api.openai.com/v1",
                credential_reference="sk-live-1234567890abcdef",
            )
