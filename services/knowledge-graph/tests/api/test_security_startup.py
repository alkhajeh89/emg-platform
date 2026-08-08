from pathlib import Path

import pytest
from emg_knowledge_graph_api import dependencies
from emg_knowledge_graph_api.config import Settings, validate_secure_transport
from emg_knowledge_graph_api.main import create_app
from emg_knowledge_graph_infrastructure import SchemaCatalogValidationError
from emg_policy_engine import PolicyConfigurationError
from fastapi.testclient import TestClient
from pydantic import ValidationError


def _clear_startup_singletons() -> None:
    dependencies._settings_singleton.cache_clear()
    dependencies._policy_enforcement_point_singleton.cache_clear()
    dependencies._schema_components_singleton.cache_clear()


def test_unknown_knowledge_graph_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(store_backend="postgress")


@pytest.mark.parametrize(
    "overrides",
    [
        {"keycloak_base_url": "http://keycloak"},
        {"postgres_dsn": "postgresql://runtime@postgres/emg"},
        {"migration_postgres_dsn": "postgresql://migration@postgres/emg"},
    ],
)
def test_production_rejects_plaintext_transport(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "deployment_environment": "production",
        "store_backend": "postgres",
        "keycloak_base_url": "https://keycloak.example.gov",
        "postgres_dsn": "postgresql://runtime@postgres/emg?sslmode=verify-full",
        "migration_postgres_dsn": "postgresql://migration@postgres/emg?sslmode=verify-full",
    }
    values.update(overrides)
    with pytest.raises(RuntimeError, match="transport"):
        validate_secure_transport(Settings(**values))


def test_production_rejects_dev_placeholder_audit_producer_secret() -> None:
    """Final correction-sprint Finding 5: production startup must fail fast
    if the committed dev-placeholder audit-producer secret is still set."""
    settings = Settings(
        deployment_environment="production",
        store_backend="postgres",
        keycloak_base_url="https://keycloak.example.gov",
        audit_service_base_url="https://audit.example.gov",
        postgres_dsn="postgresql://runtime@postgres/emg?sslmode=verify-full",
        migration_postgres_dsn="postgresql://migration@postgres/emg?sslmode=verify-full",
        audit_producer_client_secret=(
            "emg_svc_knowledge_graph_writer_local_dev_secret_do_not_use_in_prod"
        ),
    )
    with pytest.raises(RuntimeError, match="dev placeholder"):
        validate_secure_transport(settings)


def test_production_accepts_non_placeholder_audit_producer_secret() -> None:
    settings = Settings(
        deployment_environment="production",
        store_backend="postgres",
        keycloak_base_url="https://keycloak.example.gov",
        audit_service_base_url="https://audit.example.gov",
        postgres_dsn="postgresql://runtime@postgres/emg?sslmode=verify-full",
        migration_postgres_dsn="postgresql://migration@postgres/emg?sslmode=verify-full",
        audit_producer_client_secret="a-real-production-secret",
    )
    validate_secure_transport(settings)  # must not raise


def test_production_rejects_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        deployment_environment="production",
        store_backend="memory",
        schema_catalog_path=Path("services/knowledge-graph/config/schema-catalog.json"),
    )
    monkeypatch.setattr(dependencies, "_settings_singleton", lambda: settings)

    with pytest.raises(RuntimeError, match="in-memory store backend"):
        dependencies.validate_schema_runtime_configuration()


def test_production_rejects_shared_runtime_and_migration_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_dsn = "postgresql://shared-role:secret@postgres:5432/emg"
    settings = Settings(
        deployment_environment="production",
        store_backend="postgres",
        postgres_dsn=shared_dsn,
        migration_postgres_dsn=shared_dsn,
        schema_catalog_path=Path("services/knowledge-graph/config/schema-catalog.json"),
    )
    monkeypatch.setattr(dependencies, "_settings_singleton", lambda: settings)

    with pytest.raises(RuntimeError, match="credentials must be distinct"):
        dependencies.validate_schema_runtime_configuration()


def test_policy_semantic_validation_is_a_startup_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - rule_id: unsafe\n"
        "    resource_type: knowledge-graph.entity\n"
        "    action: read\n",
        encoding="utf-8",
    )
    settings = Settings(
        deployment_environment="test",
        policy_config_path=policy,
        allow_unconfigured_schema_negotiation=True,
    )
    monkeypatch.setattr(dependencies, "_settings_singleton", lambda: settings)
    dependencies._policy_enforcement_point_singleton.cache_clear()

    with pytest.raises(PolicyConfigurationError, match="no conditions"):
        dependencies.validate_schema_runtime_configuration()

    dependencies._policy_enforcement_point_singleton.cache_clear()


@pytest.mark.parametrize(
    ("catalog_document", "expected_message"),
    [
        (None, "failed to read schema catalog"),
        (
            '{"generation":"invalid","canonical_version":"2.1.0","versions":[]}',
            "schema catalog must contain at least one version",
        ),
    ],
)
def test_missing_or_invalid_catalog_prevents_production_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    catalog_document: str | None,
    expected_message: str,
) -> None:
    catalog_path = tmp_path / "schema-catalog.json"
    if catalog_document is not None:
        catalog_path.write_text(catalog_document, encoding="utf-8")

    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("EMG_KNOWLEDGE_GRAPH_API_STORE_BACKEND", "postgres")
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_KEYCLOAK_BASE_URL",
        "https://keycloak.example.gov",
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_AUDIT_SERVICE_BASE_URL",
        "https://audit.example.gov",
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_AUDIT_PRODUCER_CLIENT_SECRET",
        "a-real-production-secret-not-the-dev-placeholder",
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN",
        "postgresql://runtime@postgres.example.gov/emg?sslmode=verify-full",
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_MIGRATION_POSTGRES_DSN",
        "postgresql://migration@postgres.example.gov/emg?sslmode=verify-full",
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_ALLOW_UNCONFIGURED_SCHEMA_NEGOTIATION",
        "false",
    )
    monkeypatch.setenv(
        "EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH",
        str(catalog_path),
    )
    _clear_startup_singletons()

    try:
        with (
            pytest.raises(SchemaCatalogValidationError, match=expected_message),
            TestClient(create_app()),
        ):
            pass
    finally:
        _clear_startup_singletons()
