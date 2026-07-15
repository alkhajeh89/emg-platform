import logging

import httpx
from emg_auth_client import Principal
from emg_identity.dependencies import (
    keycloak_client_dependency,
    session_manager_dependency,
    settings_dependency,
)
from emg_identity.keycloak_client import KeycloakClient
from emg_identity.main import create_app
from emg_identity.session import SessionManager
from fastapi.testclient import TestClient


def _make_client(settings, handler) -> TestClient:
    app = create_app()
    transport = httpx.MockTransport(handler)

    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[keycloak_client_dependency] = lambda: KeycloakClient(
        settings, transport=transport
    )
    app.dependency_overrides[session_manager_dependency] = lambda: SessionManager(settings)
    return TestClient(app)


def test_healthz(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Keycloak should not be called for /healthz")

    client = _make_client(settings, handler)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "identity"}


def test_login_success_returns_token_pair(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "kc-access",
                "refresh_token": "kc-refresh",
                "expires_in": 300,
                "realm_access": {"roles": ["platform-user", "investigator"]},
                "classification_clearance": ["INTERNAL"],
                "department": ["Investigations"],
            },
        )

    client = _make_client(settings, handler)
    response = client.post(
        "/auth/login", json={"username": "dev.investigator", "password": "dev_local_password_only"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_ttl_seconds
    assert "access_token" in body and "refresh_token" in body


def test_login_failure_returns_401_and_logs_denial(settings, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    client = _make_client(settings, handler)
    with caplog.at_level(logging.WARNING, logger="emg.identity"):
        response = client.post(
            "/auth/login", json={"username": "dev.investigator", "password": "wrong-password"}
        )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["error_code"] == "AUTHORIZATION_ERROR"
    assert any("login failed" in record.message for record in caplog.records)


def test_refresh_success(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Keycloak should not be called for /auth/refresh")

    client = _make_client(settings, handler)
    session_manager = SessionManager(settings)
    principal = Principal(subject="dev.investigator", roles=("platform-user",), attributes={})
    pair = session_manager.issue(principal)

    response = client.post("/auth/refresh", json={"refresh_token": pair.refresh_token})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] != pair.access_token


def test_refresh_invalid_token_returns_401_and_logs(settings, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Keycloak should not be called for /auth/refresh")

    client = _make_client(settings, handler)
    with caplog.at_level(logging.WARNING, logger="emg.identity"):
        response = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})

    assert response.status_code == 401
    assert any("token refresh failed" in record.message for record in caplog.records)


def test_session_endpoint_requires_bearer_token(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Keycloak should not be called for /auth/session")

    client = _make_client(settings, handler)
    response = client.get("/auth/session")
    assert response.status_code == 401


def test_session_endpoint_returns_principal_for_valid_token(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Keycloak should not be called for /auth/session")

    client = _make_client(settings, handler)
    session_manager = SessionManager(settings)
    principal = Principal(
        subject="dev.investigator",
        roles=("platform-user", "investigator"),
        attributes={"department": "Investigations"},
    )
    pair = session_manager.issue(principal)

    response = client.get("/auth/session", headers={"Authorization": f"Bearer {pair.access_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "dev.investigator"
    assert set(body["roles"]) == {"platform-user", "investigator"}
    assert body["attributes"]["department"] == "Investigations"


def test_correlation_id_header_echoed(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Keycloak should not be called for /healthz")

    client = _make_client(settings, handler)
    response = client.get("/healthz", headers={"X-Correlation-Id": "test-corr-id-123"})
    assert response.headers["x-correlation-id"] == "test-corr-id-123"


# --- Sprint 3: login rate-limiting readiness --------------------------------


def test_login_rate_limited_after_max_attempts_returns_429(settings):
    """Required Security Control: "Rate-limiting readiness for token
    requests." Every attempt fails credentials (Keycloak always returns 401)
    so the test isolates the rate limiter's own behavior: the Nth+1 attempt
    for the same username must be rejected with 429 *before* Keycloak is
    called at all."""
    from emg_identity.dependencies import login_rate_limiter_dependency
    from emg_identity.rate_limit import InMemoryRateLimiter

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, json={"error": "invalid_grant"})

    client = _make_client(settings, handler)
    limiter = InMemoryRateLimiter(max_attempts=2, window_seconds=60.0)
    client.app.dependency_overrides[login_rate_limiter_dependency] = lambda: limiter

    login_body = {"username": "dev.investigator", "password": "wrong-password"}
    assert client.post("/auth/login", json=login_body).status_code == 401
    assert client.post("/auth/login", json=login_body).status_code == 401

    response = client.post("/auth/login", json=login_body)

    assert response.status_code == 429
    assert call_count["n"] == 2  # third attempt never reached Keycloak
