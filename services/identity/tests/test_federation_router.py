"""HTTP-level tests for GET /federation/providers and GET /federation/health
(FEAT-02-4). Overrides `federation_config_dependency` with an in-test
FederationConfig — no config file or external directory is touched."""

from __future__ import annotations

from emg_identity.dependencies import federation_config_dependency, settings_dependency
from emg_identity.federation import (
    ClaimMapping,
    FederationConfig,
    FederationProviderConfig,
    FederationProviderType,
)
from emg_identity.main import create_app
from fastapi.testclient import TestClient


def _make_client(settings, config: FederationConfig) -> TestClient:
    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[federation_config_dependency] = lambda: config
    return TestClient(app)


def test_providers_endpoint_redacts_secret_shaped_connection_settings(settings):
    config = FederationConfig(
        providers=[
            FederationProviderConfig(
                name="corp-ldap",
                provider_type=FederationProviderType.LDAP,
                enabled=True,
                display_name="Corporate LDAP",
                connection_settings={
                    "url": "ldaps://ldap.example.internal",
                    "bind_password": "hunter2",
                },
                claim_mappings=[
                    ClaimMapping(external_claim="dept", emg_attribute="department"),
                ],
            )
        ]
    )
    client = _make_client(settings, config)

    response = client.get("/federation/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["local_fallback_enabled"] is True
    provider = body["providers"][0]
    assert provider["name"] == "corp-ldap"
    assert provider["connection_settings"]["url"] == "ldaps://ldap.example.internal"
    assert provider["connection_settings"]["bind_password"] == "***REDACTED***"


def test_health_endpoint_reports_valid_for_default_config(settings):
    from emg_identity.federation import default_federation_config

    client = _make_client(settings, default_federation_config())
    response = client.get("/federation/health")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["problems"] == []
    assert body["local_fallback_enabled"] is True


def test_health_endpoint_reports_problems_for_invalid_config(settings):
    config = FederationConfig(
        providers=[
            FederationProviderConfig(
                name="corp-ldap",
                provider_type=FederationProviderType.LDAP,
                enabled=True,  # enabled but no connection_settings -> invalid
            )
        ]
    )
    client = _make_client(settings, config)

    response = client.get("/federation/health")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert len(body["problems"]) >= 1
    assert body["provider_count"] == 1
    assert body["enabled_provider_count"] == 1
