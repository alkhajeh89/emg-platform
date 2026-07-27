import logging
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_auth_client import AuthorizationRequest, Principal
from emg_identity.dependencies import (
    keycloak_client_dependency,
    session_manager_dependency,
    settings_dependency,
)
from emg_identity.keycloak_client import KeycloakClient
from emg_identity.main import create_app
from emg_identity.routers.auth import _claims_to_principal
from emg_identity.session import SessionManager
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _kc_access_token(settings, private_key, *, exp_delta=300, **extra_claims) -> str:
    """Mint a real, signed RS256 access token carrying the given claims —
    Group D Phase 1 Remediation (Blocking Fix 1): the login flow now decodes
    and verifies this token via JWKS, so a bare placeholder string (as
    earlier tests used) is no longer a valid stand-in for what Keycloak
    actually issues."""
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + exp_delta,
        "iss": settings.keycloak_issuer,
        "sub": "dev.investigator",
        **extra_claims,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def _make_client(settings, handler, *, public_key=None) -> TestClient:
    app = create_app()
    transport = httpx.MockTransport(handler)
    resolver = (lambda token: public_key) if public_key is not None else None

    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[keycloak_client_dependency] = lambda: KeycloakClient(
        settings, transport=transport, signing_key_resolver=resolver
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


def test_login_success_returns_token_pair(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(
        settings,
        private_key,
        realm_access={"roles": ["platform-user", "investigator"]},
        classification_clearance=["INTERNAL"],
        department=["Investigations"],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": access_token, "refresh_token": "kc-refresh", "expires_in": 300},
        )

    client = _make_client(settings, handler, public_key=public_key)
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


# --- Group D Phase 1 Remediation (Blocking Fix 1): human classification ----
# provisioning. Covers the full verified path Keycloak -> access-token
# claims -> _claims_to_principal -> Principal.attributes, its explicit
# fail-closed defaulting, and its preservation through session issuance and
# refresh.


def _login_and_get_session_attributes(client, username="dev.investigator"):
    login = client.post(
        "/auth/login", json={"username": username, "password": "dev_local_password_only"}
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]
    session = client.get("/auth/session", headers={"Authorization": f"Bearer {access_token}"})
    assert session.status_code == 200
    return session.json(), refresh_token


def test_login_extracts_present_classification_clearance_claim(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(settings, private_key, classification_clearance=["SECRET"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client)
    assert body["attributes"]["classification_clearance"] == "SECRET"


def test_login_defaults_to_unclassified_when_clearance_claim_missing(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    # No classification_clearance claim at all.
    access_token = _kc_access_token(settings, private_key)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client)
    assert body["attributes"]["classification_clearance"] == "UNCLASSIFIED"


def test_login_defaults_to_unclassified_when_clearance_claim_empty_string(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(settings, private_key, classification_clearance="")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client)
    assert body["attributes"]["classification_clearance"] == "UNCLASSIFIED"


def test_login_defaults_to_unclassified_when_clearance_claim_non_string(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    # A malformed/unexpected claim shape: neither a string nor a
    # non-empty list-of-string (the only two shapes _extract_human_attributes
    # accepts) -- an int, exactly like the machine-token equivalent test.
    access_token = _kc_access_token(settings, private_key, classification_clearance=12345)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client)
    assert body["attributes"]["classification_clearance"] == "UNCLASSIFIED"


@pytest.mark.parametrize("bogus_value", ["banana", "SUPER_SECRET", "foobar"])
def test_login_defaults_to_unclassified_when_clearance_claim_unrecognized(
    settings, rsa_keypair, bogus_value
):
    """ADR-026 final blocker: an unrecognized `classification_clearance`
    claim value (not a `Classification` enum member) must resolve to
    `"UNCLASSIFIED"` on human login, exactly like a missing/blank/non-string
    claim -- it must never survive normalization unchanged.

    Uses a distinct username per case (rather than the module's shared
    "dev.investigator" default) so this test does not consume the
    process-wide login rate limiter's budget shared with every other test in
    this module (`InMemoryRateLimiter` is an `@lru_cache` singleton keyed by
    username, per-process, for the whole test session)."""
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(settings, private_key, classification_clearance=[bogus_value])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client, username=f"dev.bogus.{bogus_value}")
    assert body["attributes"]["classification_clearance"] == "UNCLASSIFIED"


@pytest.mark.parametrize("valid_value", ["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"])
def test_login_preserves_every_valid_classification_enum_member(settings, rsa_keypair, valid_value):
    """Every recognized `Classification` enum member must survive human
    login normalization completely unchanged, not just `"SECRET"` (covered
    above). Uses a distinct username per case for the same rate-limiter
    budget reason documented above."""
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(settings, private_key, classification_clearance=[valid_value])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client, username=f"dev.valid.{valid_value}")
    assert body["attributes"]["classification_clearance"] == valid_value


def test_login_preserves_department_when_valid_string(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(settings, private_key, department=["Executive"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client)
    assert body["attributes"]["department"] == "Executive"


def test_login_omits_department_when_missing(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(settings, private_key)  # no department claim

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client)
    assert "department" not in body["attributes"]


def test_login_omits_department_when_invalid_shape(settings, rsa_keypair):
    """An empty list (Keycloak's shape for "attribute configured but no
    value set") must not surface as an empty-string department -- omitted,
    same as a fully missing claim."""
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(settings, private_key, department=[])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    body, _ = _login_and_get_session_attributes(client)
    assert "department" not in body["attributes"]


def test_login_session_refresh_preserves_principal_attributes(settings, rsa_keypair):
    """Full path: Keycloak -> verified access-token claims -> Principal ->
    EMG session issuance -> /auth/session -> /auth/refresh -> /auth/session
    again. classification_clearance and department must survive the EMG
    refresh grant unchanged (SessionManager.refresh round-trips
    Principal.attributes verbatim -- this proves that holds true starting
    from a real Keycloak-derived Principal, not just a hand-built one)."""
    private_key, public_key = rsa_keypair
    access_token = _kc_access_token(
        settings,
        private_key,
        realm_access={"roles": ["platform-user", "decision-maker"]},
        classification_clearance=["CONFIDENTIAL"],
        department=["Executive"],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": access_token, "refresh_token": "r", "expires_in": 300}
        )

    client = _make_client(settings, handler, public_key=public_key)
    first_session, refresh_token = _login_and_get_session_attributes(client)
    assert first_session["attributes"]["classification_clearance"] == "CONFIDENTIAL"
    assert first_session["attributes"]["department"] == "Executive"

    refreshed = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    new_access_token = refreshed.json()["access_token"]

    second_session = client.get(
        "/auth/session", headers={"Authorization": f"Bearer {new_access_token}"}
    )
    assert second_session.status_code == 200
    body = second_session.json()
    assert body["attributes"]["classification_clearance"] == "CONFIDENTIAL"
    assert body["attributes"]["department"] == "Executive"
    assert set(body["roles"]) == {"platform-user", "decision-maker"}


# --- Policy-rule proof: no privilege elevation when the claim is absent ----


def _identity_policy_engine():
    from pathlib import Path

    from emg_policy_engine import load_policy_config
    from emg_policy_engine.engine import PolicyEngine

    policy_path = Path(__file__).resolve().parent.parent / "config" / "policy.example.yaml"
    return PolicyEngine(load_policy_config(policy_path))


def test_policy_rule_requiring_clearance_allows_cleared_caller(settings, rsa_keypair):
    """services/identity/config/policy.example.yaml's real, shipped
    `diagnostics-read-internal` rule requires
    required_attributes.classification_clearance in
    [INTERNAL, CONFIDENTIAL, SECRET]. A caller whose verified claim resolves
    to INTERNAL is allowed."""
    private_key, _ = rsa_keypair
    verified_claims = jwt.decode(
        _kc_access_token(
            settings,
            private_key,
            realm_access={"roles": ["platform-user"]},
            classification_clearance=["INTERNAL"],
        ),
        private_key.public_key(),
        algorithms=["RS256"],
        issuer=settings.keycloak_issuer,
        options={"verify_aud": False},
    )
    principal = _claims_to_principal("dev.investigator", verified_claims)

    decision = _identity_policy_engine().evaluate(
        AuthorizationRequest(
            principal=principal, resource_type="identity.diagnostics", action="read"
        )
    )
    assert decision.outcome == "allow"
    assert decision.policy_id == "diagnostics-read-internal"


def test_no_privilege_elevation_when_clearance_claim_is_absent(settings, rsa_keypair):
    """The central fail-closed guarantee this fix restores: a caller whose
    token carries no classification_clearance claim resolves to
    UNCLASSIFIED (Blocking Fix 1), which is not in
    `diagnostics-read-internal`'s allow-list -- so the caller is denied,
    not silently granted access via some absent-attribute-matches-anything
    behavior. This is the human-side counterpart to
    emg-policy-engine's existing service-principal equivalent test."""
    private_key, _ = rsa_keypair
    verified_claims = jwt.decode(
        _kc_access_token(
            settings, private_key, realm_access={"roles": ["platform-user"]}
        ),  # no classification_clearance claim at all
        private_key.public_key(),
        algorithms=["RS256"],
        issuer=settings.keycloak_issuer,
        options={"verify_aud": False},
    )
    principal = _claims_to_principal("dev.uncleared", verified_claims)
    assert principal.attributes["classification_clearance"] == "UNCLASSIFIED"

    decision = _identity_policy_engine().evaluate(
        AuthorizationRequest(
            principal=principal, resource_type="identity.diagnostics", action="read"
        )
    )
    assert decision.outcome == "deny"
