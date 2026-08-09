import json

import pytest
from emg_audit_service.config import Settings, validate_runtime_configuration
from pydantic import ValidationError

_PROJECTOR_INVENTORY = json.dumps(
    {
        "version": 1,
        "projector_identities": [
            {"tenant_id": "tenant-a", "client_id": "emg-svc-audit-projector-tenant-a"}
        ],
    }
)


def test_unknown_audit_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(store_backend="postgress")


def test_production_rejects_memory_storage() -> None:
    with pytest.raises(RuntimeError, match="in-memory store backend"):
        validate_runtime_configuration(
            Settings(deployment_environment="production", store_backend="memory")
        )


@pytest.mark.parametrize("environment", ["development", "test"])
def test_non_production_accepts_memory_storage(environment: str) -> None:
    validate_runtime_configuration(
        Settings(deployment_environment=environment, store_backend="memory")
    )


def test_production_accepts_postgres_storage() -> None:
    validate_runtime_configuration(
        Settings(
            deployment_environment="production",
            store_backend="postgres",
            keycloak_base_url="https://keycloak.example.gov",
            postgres_dsn="postgresql://audit:production-password@postgres.example.gov/emg?sslmode=verify-full",
            projector_identity_inventory_json=_PROJECTOR_INVENTORY,
        )
    )


def test_production_rejects_missing_projector_identity_inventory() -> None:
    with pytest.raises(RuntimeError, match="identity inventory"):
        validate_runtime_configuration(
            Settings(
                deployment_environment="production",
                store_backend="postgres",
                keycloak_base_url="https://keycloak.example.gov",
                postgres_dsn=(
                    "postgresql://audit:production-password@postgres.example.gov/"
                    "emg?sslmode=verify-full"
                ),
            )
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"keycloak_base_url": "http://keycloak"},
        {"postgres_dsn": "postgresql://audit@postgres/emg"},
    ],
)
def test_production_rejects_plaintext_transport(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "deployment_environment": "production",
        "store_backend": "postgres",
        "keycloak_base_url": "https://keycloak.example.gov",
        "postgres_dsn": "postgresql://audit:production-password@postgres/emg?sslmode=verify-full",
        "projector_identity_inventory_json": _PROJECTOR_INVENTORY,
    }
    values.update(overrides)
    with pytest.raises(RuntimeError, match="transport"):
        validate_runtime_configuration(Settings(**values))
