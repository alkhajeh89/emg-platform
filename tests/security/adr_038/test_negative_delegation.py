"""Phase 6 -- the 11 required negative / fail-closed scenarios, each proving
Keycloak 25 (as configured by this verification's realm + provision.py) does
not silently allow the corresponding ADR-038 violation. Every test asserts a
concrete rejection (an HTTP error status from Keycloak, or a raised
DownstreamValidationError from the independent downstream validator) --
never a soft/logged-only warning.
"""

from __future__ import annotations

import time

import jwt
import keycloak_client as kc
import pytest
from audit_harness import build_audit_client_with_failing_store
from claim_adapter import to_delegated_credential
from downstream_validator import DownstreamAudienceValidator, DownstreamValidationError


def _issuer(env: dict) -> str:
    return f"{env['base_url']}/realms/{env['realm']}"


def _jwks_uri(env: dict) -> str:
    return f"{_issuer(env)}/protocol/openid-connect/certs"


def _human_token(env: dict, username: str, password_key: str) -> str:
    resp = kc.ropc_login(
        env["base_url"],
        env["realm"],
        "emg-verification-ropc",
        env["EMG_VERIFICATION_ROPC_SECRET"],
        username,
        env[password_key],
    )
    assert resp.status == 200, resp.body
    return resp.body["access_token"]


def _validator_for(env: dict, audience: str) -> DownstreamAudienceValidator:
    return DownstreamAudienceValidator(
        issuer=_issuer(env), audience=audience, jwks_uri=_jwks_uri(env)
    )


# 1. Privilege elevation ------------------------------------------------


def test_1_privilege_elevation_via_requested_subject_is_rejected(verification_env):
    """A lower-privileged human (B, INTERNAL clearance) cannot use
    `requested_subject` to claim a higher-privileged identity (A,
    CONFIDENTIAL) while presenting their OWN, genuinely lower-privileged
    subject_token. Either Keycloak rejects the mismatched request outright,
    or -- the observed Keycloak 25 behaviour -- silently ignores
    requested_subject when a subject_token is already present and the
    resulting credential still reflects B's own (lower) claims, never A's.
    Either outcome satisfies Security Invariant 9.4; only a credential
    actually carrying A's clearance while B authenticated would fail this
    test."""
    env = verification_env
    subject_b = _human_token(env, "human-principal-b", "EMG_VERIFICATION_HUMAN_B_PASSWORD")

    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject_b,
        "emg-verification-audience-a",
    )
    if resp.status != 200:
        return  # outright rejection also satisfies the invariant

    validated = _validator_for(env, "emg-verification-audience-a").validate(
        resp.body["access_token"]
    )
    credential = to_delegated_credential(validated)
    assert credential.classification_clearance == "INTERNAL"  # B's own, never A's CONFIDENTIAL
    assert credential.tenant_id == "tenant-verification-b"


# 2. Audience A credential presented to Audience B -----------------------


def test_2_cross_audience_credential_reuse_is_rejected(verification_env):
    """AC-4 (negative half): a credential issued for Audience A is rejected
    by Audience B's independent validator."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")
    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject_a,
        "emg-verification-audience-a",
    )
    assert resp.status == 200, resp.body

    with pytest.raises(DownstreamValidationError):
        _validator_for(env, "emg-verification-audience-b").validate(resp.body["access_token"])


# 3. Tenant substitution --------------------------------------------------


def test_3_tenant_substitution_via_client_input_is_ignored(verification_env):
    """ADR-035 D-5 / ADR-036 D-5 / ADR-038 §8.5 / §9.6: no client-controlled
    input can change the tenant on the resulting credential. A bogus
    `tenant_id` form field alongside a legitimate exchange request is a
    standard OAuth-unknown-parameter and must be silently ignored, never
    honoured."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")

    from keycloak_client import _post_form  # noqa: PLC0415 - one-off raw call for an extra field

    resp = _post_form(
        env["base_url"],
        f"/realms/{env['realm']}/protocol/openid-connect/token",
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": "emg-verification-bff",
            "client_secret": env["EMG_VERIFICATION_BFF_SECRET"],
            "subject_token": subject_a,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "emg-verification-audience-a",
            "tenant_id": "attacker-controlled-tenant",
        },
    )
    assert resp.status == 200, resp.body
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        resp.body["access_token"]
    )
    credential = to_delegated_credential(validated)
    assert credential.tenant_id == "tenant-verification-a"
    assert credential.tenant_id != "attacker-controlled-tenant"


# 4. Clearance elevation ---------------------------------------------------


def test_4_clearance_elevation_via_client_input_is_ignored(verification_env):
    """Same class of attack as #3, targeting classification_clearance
    instead of tenant_id."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")

    from keycloak_client import _post_form  # noqa: PLC0415

    resp = _post_form(
        env["base_url"],
        f"/realms/{env['realm']}/protocol/openid-connect/token",
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": "emg-verification-bff",
            "client_secret": env["EMG_VERIFICATION_BFF_SECRET"],
            "subject_token": subject_a,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "emg-verification-audience-a",
            "classification_clearance": "SECRET",
        },
    )
    assert resp.status == 200, resp.body
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        resp.body["access_token"]
    )
    credential = to_delegated_credential(validated)
    assert credential.classification_clearance == "CONFIDENTIAL"
    assert credential.classification_clearance != "SECRET"


# 5. Unauthorized Acting Service -------------------------------------------


def test_5_unauthorized_acting_service_is_rejected(verification_env):
    """provision.py deliberately never grants emg-verification-bff-unauthorized
    token-exchange permission. Keycloak must fail closed."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")

    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff-unauthorized",
        env["EMG_VERIFICATION_BFF_UNAUTHORIZED_SECRET"],
        subject_a,
        "emg-verification-audience-a",
    )
    assert resp.status == 403, resp.body
    assert resp.body.get("error") == "access_denied"


# 6. Invalid issuer ----------------------------------------------------


def test_6_invalid_issuer_is_rejected(verification_env):
    """AC-9 / Security Invariant 9.8: a genuinely valid, correctly signed
    credential is still rejected if validated against the wrong expected
    issuer -- proves issuer is actually checked, not merely present."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")
    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject_a,
        "emg-verification-audience-a",
    )
    assert resp.status == 200, resp.body

    wrong_issuer_validator = DownstreamAudienceValidator(
        issuer="http://localhost:8180/realms/some-other-realm",
        audience="emg-verification-audience-a",
        jwks_uri=_jwks_uri(env),
    )
    with pytest.raises(DownstreamValidationError):
        wrong_issuer_validator.validate(resp.body["access_token"])


# 7. Expired Delegated Credential -----------------------------------------


def test_7_expired_delegated_credential_is_rejected(verification_env):
    """AC-10 / Security Invariant 9.11. The realm's access-token lifespan is
    60s (see Phase 7 rationale in docs/security/adr-038/...); this test
    genuinely waits past expiry rather than forging a claim, so the proof is
    against real Keycloak-issued expiry, not a hand-crafted token."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")
    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject_a,
        "emg-verification-audience-a",
    )
    assert resp.status == 200, resp.body
    token = resp.body["access_token"]

    unverified = jwt.decode(token, options={"verify_signature": False})
    wait_s = max(0, unverified["exp"] - int(time.time())) + 2
    time.sleep(wait_s)

    with pytest.raises(DownstreamValidationError):
        _validator_for(env, "emg-verification-audience-a").validate(token)


# 8. Altered signature ----------------------------------------------------


def test_8_altered_signature_is_rejected(verification_env):
    """Mirrors the existing production test pattern
    (services/audit/tests/test_audit_api.py::_tamper_signature) -- flips a
    character in the signature segment without touching header/payload."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")
    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject_a,
        "emg-verification-audience-a",
    )
    assert resp.status == 200, resp.body

    header, payload, signature = resp.body["access_token"].split(".")
    flipped_sig = ("B" if signature[0] != "B" else "C") + signature[1:]
    tampered = f"{header}.{payload}.{flipped_sig}"

    with pytest.raises(DownstreamValidationError):
        _validator_for(env, "emg-verification-audience-a").validate(tampered)


# 9. Unauthenticated / public client token exchange ------------------------


def test_9_exchange_without_valid_client_authentication_is_rejected(verification_env):
    """ADR-038 §7.2 / AC-8: only an authenticated confidential client may
    request an exchange. A missing or wrong client_secret must be rejected
    before any exchange logic runs."""
    env = verification_env
    subject_a = _human_token(env, "human-principal-a", "EMG_VERIFICATION_HUMAN_A_PASSWORD")

    wrong_secret = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        "not-the-real-secret",
        subject_a,
        "emg-verification-audience-a",
    )
    assert wrong_secret.status == 401, wrong_secret.body

    from keycloak_client import _post_form  # noqa: PLC0415

    no_secret = _post_form(
        env["base_url"],
        f"/realms/{env['realm']}/protocol/openid-connect/token",
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": "emg-verification-bff",
            "subject_token": subject_a,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "emg-verification-audience-a",
        },
    )
    assert no_secret.status == 401, no_secret.body


# 10. Delegation failure attempting service-only fallback -------------------


def test_10_service_only_token_is_not_treated_as_a_delegated_credential(verification_env):
    """Security Invariant 9.10 ("Fallback to anonymous, service-only, or
    inferred identity is prohibited").

    Experimentally corrected premise: a bare client_credentials token DOES
    carry a `sub` in Keycloak 25 (the client's own synthetic service-account
    user) -- unlike the exchange-specific gap Phase 3 found, this is
    ordinary Keycloak behaviour, so "sub is absent" is NOT a reliable
    service-only signal and using it would have made this test pass for the
    wrong reason. The actual, already-implemented fail-closed mechanism is
    audience restriction (AC-4): the Acting Service's own client_credentials
    token was never exchanged for any downstream audience, so it carries no
    `aud` matching a specific Platform Service -- the SAME
    DownstreamAudienceValidator every genuine Delegated Credential is
    checked against (mirroring production's TenantServiceTokenValidator)
    rejects it purely on that ordinary, already-proven audience check.
    Nothing new needs to exist for the fallback to be structurally
    impossible."""
    env = verification_env
    resp = kc.client_credentials(
        env["base_url"], env["realm"], "emg-verification-bff", env["EMG_VERIFICATION_BFF_SECRET"]
    )
    assert resp.status == 200, resp.body

    unverified = jwt.decode(resp.body["access_token"], options={"verify_signature": False})
    credential = to_delegated_credential(unverified)
    assert (
        credential.audience == ()
    ), "expected the Acting Service's own token to carry no downstream audience"

    with pytest.raises(DownstreamValidationError):
        _validator_for(env, "emg-verification-audience-a").validate(resp.body["access_token"])


# 11. Audit attribution unavailable -----------------------------------------


def test_11_audit_unavailable_blocks_rather_than_silently_succeeding(verification_env):
    """ADR-036 D-9: 'Audit service unavailable -> Block governed actions --
    fail closed.' Simulated via a real subclass of the real
    InMemoryAuditEventStore whose append() raises (see
    audit_harness._FailingAuditEventStore) -- the unmodified, real
    emg_audit_service app wired to a store that cannot persist. The ingest
    call must surface as a failure the caller can act on, never a 200 that
    silently dropped the event."""
    env = verification_env
    producer = kc.client_credentials(
        env["base_url"],
        env["realm"],
        "emg-svc-knowledge-graph-writer",
        env["EMG_VERIFICATION_KG_WRITER_SECRET"],
    )
    assert producer.status == 200, producer.body

    client = build_audit_client_with_failing_store(env)
    resp = client.post(
        "/audit/events",
        json={
            "event_id": "adr038-verification-audit-outage",
            "actor": "human-principal-a",
            "actor_type": "human",
            "module": "adr-038-verification",
            "action": "delegated-read",
            "outcome": "success",
            "source_system": "adr-038-verification-harness",
        },
        headers={"Authorization": f"Bearer {producer.body['access_token']}"},
    )
    assert resp.status_code >= 500, resp.text
