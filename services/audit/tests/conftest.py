"""Test fixtures for the audit service.

Uses the in-memory store and an injected local RSA keypair validator — the
same pattern services/identity/tests/test_service_auth_router.py uses — so no
Docker, PostgreSQL, or live Keycloak is required. Token / event builder
helpers are defined inside the test modules (not here) to keep this conftest
free of cross-module coupling.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_audit_pipeline import InMemoryAuditEventStore, InMemoryCustodyEventStore
from emg_audit_service.authn import (
    ServiceTokenValidator,
    service_token_validator_dependency,
    settings_dependency,
)
from emg_audit_service.config import Settings
from emg_audit_service.main import create_app
from emg_audit_service.store import custody_store_dependency, store_dependency
from fastapi.testclient import TestClient


@pytest.fixture
def settings() -> Settings:
    return Settings(
        store_backend="memory",
        keycloak_base_url="http://keycloak.test",
        keycloak_realm="emg-test",
        service_token_audience="emg-internal-services",
    )


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def store() -> InMemoryAuditEventStore:
    return InMemoryAuditEventStore()


@pytest.fixture
def custody_store() -> InMemoryCustodyEventStore:
    return InMemoryCustodyEventStore()


@pytest.fixture
def client(settings, rsa_keypair, store, custody_store) -> TestClient:
    _, public_key = rsa_keypair
    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[service_token_validator_dependency] = lambda: ServiceTokenValidator(
        settings, signing_key_resolver=lambda token: public_key
    )
    app.dependency_overrides[store_dependency] = lambda: store
    app.dependency_overrides[custody_store_dependency] = lambda: custody_store
    return TestClient(app)
