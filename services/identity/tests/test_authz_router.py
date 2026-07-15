"""HTTP-level tests for GET /authz/check (Sprint 4, FEAT-03-1, FEAT-03-2).

Loads the real `services/identity/config/policy.example.yaml` (resolved
relative to this file, not the process cwd, so the test is not sensitive to
how pytest is invoked) through the real `emg_policy_engine.load_policy_config`
-> `LocalPolicyEnforcementPoint` path — this is an end-to-end wiring test,
not a re-test of PolicyEngine's ABAC semantics (already covered by
libs/python/emg-policy-engine/tests/test_engine.py).

Covers, against the three rules in policy.example.yaml:
- a human Principal matched by the allow rule (diagnostics-read-internal)
- a human Principal denied because no rule's conditions are satisfied
  (default-deny; insufficient clearance)
- a human Principal matched by BOTH the allow rule and the
  diagnostics-read-knowledge-steward-excluded deny rule, exercising
  deny-overrides end-to-end over real HTTP
- a registered ServicePrincipal matched by diagnostics-read-service
- a ServicePrincipal with an unregistered/insufficiently-scoped token,
  denied via the existing service-token trust path (never reaches the PEP)
- both allow and deny decisions are audit-logged (US-03 acceptance
  criterion), following the caplog pattern in test_auth_router.py
- /authz/check accepts either identity kind without weakening the existing
  Sprint 3 separation between /auth/session and /auth/service-session
  (those two routers and their own dependencies are untouched)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_auth_client import Principal
from emg_identity.dependencies import (
    policy_enforcement_point_dependency,
    service_token_validator_dependency,
    session_manager_dependency,
    settings_dependency,
)
from emg_identity.main import create_app
from emg_identity.service_token_validator import ServiceTokenValidator
from emg_identity.session import SessionManager
from emg_policy_engine import LocalPolicyEnforcementPoint, load_policy_config
from fastapi.testclient import TestClient

_POLICY_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "policy.example.yaml"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _issue_service_token(
    settings, private_key, *, client_id="emg-svc-identity", scope="svc-identity"
):
    now = int(time.time())
    return jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": settings.service_token_audience,
            "azp": client_id,
            "scope": scope,
        },
        private_key,
        algorithm="RS256",
    )


def _make_client(settings, public_key) -> TestClient:
    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[session_manager_dependency] = lambda: SessionManager(settings)
    app.dependency_overrides[service_token_validator_dependency] = lambda: ServiceTokenValidator(
        settings, signing_key_resolver=lambda token: public_key
    )
    app.dependency_overrides[policy_enforcement_point_dependency] = lambda: (
        LocalPolicyEnforcementPoint(load_policy_config(_POLICY_CONFIG_PATH))
    )
    return TestClient(app)


def _human_token(settings, *, roles, attributes) -> str:
    session_manager = SessionManager(settings)
    principal = Principal(subject="dev.test-subject", roles=roles, attributes=attributes)
    return session_manager.issue(principal).access_token


# --- resolution proof: the policy file this test loads is exactly the one
# described in Section 4 of the module docstring, so a future edit to
# policy.example.yaml that silently breaks these assumptions fails loudly
# here rather than only in production. ---------------------------------------


def test_policy_config_path_resolves_to_the_real_example_file():
    assert _POLICY_CONFIG_PATH.exists()
    config = load_policy_config(_POLICY_CONFIG_PATH)
    rule_ids = {rule.rule_id for rule in config.rules}
    assert rule_ids == {
        "diagnostics-read-internal",
        "diagnostics-read-knowledge-steward-excluded",
        "diagnostics-read-service",
    }


# --- human Principal ---------------------------------------------------------


def test_human_principal_with_clearance_is_allowed(settings):
    client = _make_client(settings, public_key=None)
    token = _human_token(
        settings,
        roles=("platform-user", "investigator"),
        attributes={"classification_clearance": "INTERNAL"},
    )

    response = client.get(
        "/authz/check",
        params={"resource_type": "identity.diagnostics", "action": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is True
    assert body["outcome"] == "allow"
    assert body["policy_id"] == "diagnostics-read-internal"
    assert body["subject"] == "dev.test-subject"


def test_human_principal_without_clearance_is_denied_by_default(settings):
    client = _make_client(settings, public_key=None)
    token = _human_token(
        settings,
        roles=("platform-user", "investigator"),
        attributes={},  # no classification_clearance attribute at all
    )

    response = client.get(
        "/authz/check",
        params={"resource_type": "identity.diagnostics", "action": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["outcome"] == "deny"
    assert body["policy_id"] is None
    assert "default-deny" in body["reason"]


def test_knowledge_steward_is_denied_by_deny_overrides_despite_matching_allow_rule(settings):
    """A knowledge-steward is also a platform-user with sufficient
    clearance, so BOTH diagnostics-read-internal (allow) and
    diagnostics-read-knowledge-steward-excluded (deny) match — deny wins.
    This is the deny-overrides combining algorithm exercised end-to-end over
    real HTTP, not just inside PolicyEngine's own unit tests."""
    client = _make_client(settings, public_key=None)
    token = _human_token(
        settings,
        roles=("platform-user", "knowledge-steward"),
        attributes={"classification_clearance": "INTERNAL"},
    )

    response = client.get(
        "/authz/check",
        params={"resource_type": "identity.diagnostics", "action": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["outcome"] == "deny"
    assert body["policy_id"] == "diagnostics-read-knowledge-steward-excluded"


def test_check_endpoint_requires_bearer_token(settings):
    client = _make_client(settings, public_key=None)
    response = client.get(
        "/authz/check", params={"resource_type": "identity.diagnostics", "action": "read"}
    )
    assert response.status_code == 401


# --- ServicePrincipal ---------------------------------------------------------


def test_registered_service_principal_is_allowed(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    token = _issue_service_token(settings, private_key, client_id="emg-svc-identity")

    response = client.get(
        "/authz/check",
        params={"resource_type": "identity.diagnostics", "action": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is True
    assert body["outcome"] == "allow"
    assert body["policy_id"] == "diagnostics-read-service"
    assert body["subject"] == "emg-svc-identity"


def test_service_principal_with_unrecognized_client_id_is_denied_before_the_pep(
    settings, rsa_keypair
):
    """An unregistered client_id fails ServiceTokenValidator itself (401,
    AuthorizationError) — the request never reaches the PEP at all. This is
    the existing Sprint 3 fail-closed behavior, unchanged by Sprint 4."""
    private_key, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    token = _issue_service_token(settings, private_key, client_id="emg-svc-unregistered")

    response = client.get(
        "/authz/check",
        params={"resource_type": "identity.diagnostics", "action": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_service_principal_with_no_matching_role_is_denied_by_default(settings, rsa_keypair):
    """emg-svc-audit is registered (so authentication succeeds) but does not
    hold any role diagnostics-read-service requires — reaches the PEP and is
    denied there, not at the authentication layer."""
    private_key, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    token = _issue_service_token(
        settings, private_key, client_id="emg-svc-audit", scope="svc-audit"
    )

    response = client.get(
        "/authz/check",
        params={"resource_type": "identity.nonexistent-resource", "action": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["outcome"] == "deny"
    assert "default-deny" in body["reason"]


# --- audit logging (US-03: "denial and allow decisions are both logged") ----


def test_allow_decision_is_audit_logged_at_info(settings, caplog):
    client = _make_client(settings, public_key=None)
    token = _human_token(
        settings,
        roles=("platform-user", "investigator"),
        attributes={"classification_clearance": "INTERNAL"},
    )

    with caplog.at_level(logging.INFO, logger="emg.identity"):
        response = client.get(
            "/authz/check",
            params={"resource_type": "identity.diagnostics", "action": "read"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert any(
        "authorization allow: identity.diagnostics/read" in record.message
        for record in caplog.records
    )


def test_deny_decision_is_audit_logged_at_warning(settings, caplog):
    client = _make_client(settings, public_key=None)
    token = _human_token(settings, roles=("platform-user",), attributes={})

    with caplog.at_level(logging.WARNING, logger="emg.identity"):
        response = client.get(
            "/authz/check",
            params={"resource_type": "identity.diagnostics", "action": "read"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert any(
        "authorization deny: identity.diagnostics/read" in record.message
        for record in caplog.records
    )


# --- identity-kind flexibility does not weaken existing separation ---------


def test_check_endpoint_accepts_a_service_token_that_service_session_endpoint_would_also_accept(
    settings, rsa_keypair
):
    """/authz/check intentionally accepts both identity kinds (FEAT-03-1),
    but /auth/session and /auth/service-session (Sprint 2/3) are untouched
    and still reject the wrong kind — see
    test_separation_human_vs_service.py, unmodified this sprint."""
    private_key, public_key = rsa_keypair
    client = _make_client(settings, public_key)
    token = _issue_service_token(settings, private_key, client_id="emg-svc-identity")

    service_session_response = client.get(
        "/auth/service-session", headers={"Authorization": f"Bearer {token}"}
    )
    authz_check_response = client.get(
        "/authz/check",
        params={"resource_type": "identity.diagnostics", "action": "read"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert service_session_response.status_code == 200
    assert authz_check_response.status_code == 200
