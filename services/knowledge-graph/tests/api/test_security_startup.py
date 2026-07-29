from pathlib import Path

import pytest
from emg_knowledge_graph_api import dependencies
from emg_knowledge_graph_api.config import Settings
from emg_policy_engine import PolicyConfigurationError
from pydantic import ValidationError


def test_unknown_knowledge_graph_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(store_backend="postgress")


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
