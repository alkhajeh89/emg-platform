from __future__ import annotations

import json

import pytest
from audit_projector_helpers import settings
from emg_audit_projector.config import Settings, validate_runtime_configuration
from pydantic import ValidationError


def test_requires_unique_tenants_and_clients() -> None:
    duplicated = json.dumps(
        [
            {"tenant_id": "tenant-a", "client_id": "client-a", "client_secret": "a"},
            {"tenant_id": "tenant-b", "client_id": "client-a", "client_secret": "b"},
        ]
    )
    configured = Settings(deployment_environment="test", tenant_credentials_json=duplicated)

    with pytest.raises(ValueError, match="distinct logical client"):
        _ = configured.tenant_credentials


def test_rejects_drain_longer_than_lease() -> None:
    with pytest.raises(ValidationError, match="drain_timeout_seconds"):
        settings(lease_seconds=10.0, drain_timeout_seconds=11.0)


def test_production_requires_encrypted_transports() -> None:
    configured = settings(deployment_environment="production")

    with pytest.raises(RuntimeError, match="Keycloak transport"):
        validate_runtime_configuration(configured)


def test_production_accepts_required_transport_posture() -> None:
    configured = settings(
        deployment_environment="production",
        keycloak_base_url="https://keycloak.example",
        audit_service_base_url="https://audit.example",
        postgres_dsn="postgresql://projector@postgres/emg?sslmode=verify-full",
    )

    validate_runtime_configuration(configured)


def test_production_rejects_credentials_divergent_from_inventory() -> None:
    configured = settings(
        deployment_environment="production",
        keycloak_base_url="https://keycloak.example",
        audit_service_base_url="https://audit.example",
        postgres_dsn="postgresql://projector@postgres/emg?sslmode=verify-full",
        identity_inventory_json=json.dumps(
            {
                "version": 1,
                "projector_identities": [{"tenant_id": "tenant-b", "client_id": "projector-b"}],
            }
        ),
    )

    with pytest.raises(ValueError, match="exactly match"):
        validate_runtime_configuration(configured)
