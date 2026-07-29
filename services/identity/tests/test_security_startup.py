from pathlib import Path

import pytest
from emg_identity import dependencies
from emg_identity.config import (
    DEFAULT_KEYCLOAK_CLIENT_SECRET,
    DEFAULT_SERVICE_CLIENT_SECRET,
    DEFAULT_SESSION_SIGNING_KEY,
    Settings,
    validate_runtime_configuration,
)
from emg_policy_engine import PolicyConfigurationError

_PRODUCTION_KEY = "p" * 32


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "deployment_environment": "production",
        "session_signing_key": _PRODUCTION_KEY,
        "keycloak_client_secret": "production-keycloak-client-secret",
        "service_client_secret": "production-service-client-secret",
        "audit_forwarding_enabled": True,
        "refresh_token_store_backend": "postgres",
        "keycloak_base_url": "https://keycloak.example.gov",
        "audit_service_base_url": "https://audit.example.gov",
        "refresh_token_postgres_dsn": (
            "postgresql://identity@postgres.example.gov/emg?sslmode=verify-full"
        ),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("signing_key", [DEFAULT_SESSION_SIGNING_KEY, "", "   ", "short"])
def test_production_rejects_unsafe_session_signing_keys(signing_key: str) -> None:
    with pytest.raises(RuntimeError, match="session signing key"):
        validate_runtime_configuration(_production_settings(session_signing_key=signing_key))


@pytest.mark.parametrize(
    ("field_name", "development_value"),
    [
        ("keycloak_client_secret", DEFAULT_KEYCLOAK_CLIENT_SECRET),
        ("service_client_secret", DEFAULT_SERVICE_CLIENT_SECRET),
    ],
)
def test_production_rejects_known_development_credentials(
    field_name: str,
    development_value: str,
) -> None:
    with pytest.raises(RuntimeError, match="development credential"):
        validate_runtime_configuration(_production_settings(**{field_name: development_value}))


def test_production_requires_audit_forwarding() -> None:
    with pytest.raises(RuntimeError, match="requires durable audit forwarding"):
        validate_runtime_configuration(_production_settings(audit_forwarding_enabled=False))


@pytest.mark.parametrize("environment", ["development", "test"])
def test_non_production_retains_local_defaults(environment: str) -> None:
    validate_runtime_configuration(Settings(deployment_environment=environment))


def test_production_accepts_secure_runtime_configuration() -> None:
    validate_runtime_configuration(_production_settings())


@pytest.mark.parametrize(
    "overrides",
    [
        {"keycloak_base_url": "http://keycloak"},
        {"audit_service_base_url": "http://audit"},
        {"refresh_token_postgres_dsn": "postgresql://identity@postgres/emg"},
    ],
)
def test_production_rejects_plaintext_transport(overrides: dict[str, object]) -> None:
    with pytest.raises(RuntimeError, match="transport"):
        validate_runtime_configuration(_production_settings(**overrides))


def test_identity_startup_gate_rejects_semantically_unsafe_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - rule_id: unsafe\n"
        "    resource_type: identity.diagnostics\n"
        "    action: read\n",
        encoding="utf-8",
    )
    settings = Settings(policy_config_path=policy)
    monkeypatch.setattr(dependencies, "_settings_singleton", lambda: settings)
    dependencies._policy_enforcement_point_singleton.cache_clear()

    with pytest.raises(PolicyConfigurationError, match="no conditions"):
        dependencies.validate_identity_runtime_configuration()

    dependencies._policy_enforcement_point_singleton.cache_clear()
