"""HTTP-level tests for GET /auth/service-session (FEAT-02-3).

Overrides `service_token_validator_dependency` with a validator wired to a
locally-generated RSA keypair, the same pattern test_auth_router.py uses for
`keycloak_client_dependency` — no live Keycloak/JWKS endpoint is required.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_identity.dependencies import service_token_validator_dependency, settings_dependency
from emg_identity.main import create_app
from emg_identity.service_token_validator import ServiceTokenValidator
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _issue_service_token(settings, private_key, *, exp_delta=300, audience=None):
    now = int(time.time())
    return jwt.encode(
        {
            "iat": now,
            "exp": now + exp_delta,
            "iss": settings.keycloak_issuer,
            "aud": audience if audience is not None else settings.service_token_audience,
            "azp": "emg-svc-authorization",
            "scope": "svc-authorization",
            "tenant_id": "tenant-a",
            "realm_access": {"roles": ["service-account", "svc-authorization"]},
        },
        private_key,
        algorithm="RS256",
    )


def _make_client(settings, public_key) -> TestClient:
    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[service_token_validator_dependency] = lambda: ServiceTokenValidator(
        settings, signing_key_resolver=lambda token: public_key
    )
    return TestClient(app)


def test_service_session_endpoint_requires_bearer_token(settings, rsa_keypair):
    _, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    response = client.get("/auth/service-session")
    assert response.status_code == 401


def test_service_session_endpoint_returns_service_principal_for_valid_token(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    token = _issue_service_token(settings, private_key)

    response = client.get("/auth/service-session", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["client_id"] == "emg-svc-authorization"
    assert body["service_name"] == "authorization"
    assert "svc-authorization" in body["roles"]


def test_service_session_endpoint_rejects_invalid_audience(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    token = _issue_service_token(settings, private_key, audience="wrong-audience")

    response = client.get("/auth/service-session", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_service_session_endpoint_rejects_expired_token(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    token = _issue_service_token(settings, private_key, exp_delta=-100)

    response = client.get("/auth/service-session", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_service_session_endpoint_rejects_human_session_token(settings, rsa_keypair):
    """Testing Requirement: "Human token used where service token
    required," exercised end-to-end through the HTTP layer."""
    from emg_auth_client import Principal
    from emg_identity.session import SessionManager

    _, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    session_manager = SessionManager(settings)
    pair = session_manager.issue(
        Principal(subject="dev.investigator", roles=("platform-user",), attributes={})
    )

    response = client.get(
        "/auth/service-session", headers={"Authorization": f"Bearer {pair.access_token}"}
    )

    assert response.status_code == 401
