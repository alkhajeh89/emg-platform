"""Phase 5 -- positive capability evidence for the EMG Delegation Profile
(ADR-038 §6.3 / Chapter XV AC-1..AC-11), executed against the real, isolated
verification Keycloak. Every assertion here is evidence for exactly one row
of docs/security/adr-038/03_CAPABILITY_MATRIX.md; each test docstring names
the property it proves.
"""

from __future__ import annotations

import jwt
import keycloak_client as kc
from claim_adapter import to_delegated_credential
from downstream_validator import DownstreamAudienceValidator


def _issuer(env: dict) -> str:
    return f"{env['base_url']}/realms/{env['realm']}"


def _jwks_uri(env: dict) -> str:
    return f"{_issuer(env)}/protocol/openid-connect/certs"


def _human_a_token(env: dict) -> str:
    resp = kc.ropc_login(
        env["base_url"],
        env["realm"],
        "emg-verification-ropc",
        env["EMG_VERIFICATION_ROPC_SECRET"],
        "human-principal-a",
        env["EMG_VERIFICATION_HUMAN_A_PASSWORD"],
    )
    assert resp.status == 200, resp.body
    return resp.body["access_token"]


def _exchange_for(env: dict, audience: str) -> dict:
    subject = _human_a_token(env)
    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject,
        audience,
    )
    assert resp.status == 200, resp.body
    return resp.body


def _validator_for(env: dict, audience: str) -> DownstreamAudienceValidator:
    return DownstreamAudienceValidator(
        issuer=_issuer(env), audience=audience, jwks_uri=_jwks_uri(env)
    )


def test_human_subject_preserved(verification_env):
    """AC-2 / property 1: the exchanged token's sub matches the originating
    Human Principal's own subject, verified end-to-end via the real
    downstream validator (not just decoded)."""
    env = verification_env
    subject_token = _human_a_token(env)
    original_claims = jwt.decode(subject_token, options={"verify_signature": False})

    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )
    credential = to_delegated_credential(validated)

    assert credential.human_subject == original_claims["sub"]


def test_acting_service_independently_identifiable(verification_env):
    """AC-3 / property 2: Acting Service identity (azp) is present,
    cryptographically bound (it's inside the signed token), and distinct
    from the human_subject field."""
    env = verification_env
    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )
    credential = to_delegated_credential(validated)

    assert credential.acting_service == "emg-verification-bff"
    assert credential.acting_service != credential.human_subject


def test_audience_a_accepts_its_own_credential(verification_env):
    """AC-4 (positive half) / property 3: a credential issued for Audience A
    validates successfully against Audience A's own independent validator."""
    env = verification_env
    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )
    assert validated["aud"] == "emg-verification-audience-a"


def test_audience_b_accepts_its_own_credential(verification_env):
    """AC-4 (positive half) / property 3, second audience -- proves the
    profile isn't accidentally hardcoded to one audience."""
    env = verification_env
    exchanged = _exchange_for(env, "emg-verification-audience-b")
    validated = _validator_for(env, "emg-verification-audience-b").validate(
        exchanged["access_token"]
    )
    assert validated["aud"] == "emg-verification-audience-b"


def test_tenant_unchanged(verification_env):
    """AC-6 / property 5: tenant_id in the exchanged credential matches the
    originating Human Principal's tenant exactly."""
    env = verification_env
    subject_token = _human_a_token(env)
    original = jwt.decode(subject_token, options={"verify_signature": False})

    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )
    credential = to_delegated_credential(validated)

    assert credential.tenant_id == original["tenant_id"] == "tenant-verification-a"


def test_clearance_unchanged(verification_env):
    """AC-7 / property 6: classification_clearance in the exchanged
    credential matches the originating Human Principal's clearance exactly."""
    env = verification_env
    subject_token = _human_a_token(env)
    original = jwt.decode(subject_token, options={"verify_signature": False})

    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )
    credential = to_delegated_credential(validated)

    assert (
        credential.classification_clearance
        == original["classification_clearance"]
        == "CONFIDENTIAL"
    )


def test_scope_equal_or_reduced(verification_env):
    """Principle 8 / AC-5 (positive half) / property 7 / Security Invariant
    9.4 ("Delegation SHALL never increase: permissions; roles; clearance;
    tenant access"). Tested directly against roles, since that is this
    platform's actual privilege unit (production authn.py reads
    realm_access.roles for RBAC) -- the Keycloak OAuth `scope` string in
    this realm names which claim-projecting client-scopes ran, which is a
    mechanical/structural concept, not a privilege ceiling, so asserting on
    it directly would conflate the two. The exchanged credential's roles
    must be a subset of the ORIGINATING HUMAN PRINCIPAL's own roles."""
    env = verification_env
    subject_token = _human_a_token(env)
    original = jwt.decode(subject_token, options={"verify_signature": False})
    human_roles = set(original["realm_access"]["roles"])

    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )
    exchanged_roles = set(validated.get("realm_access", {}).get("roles", []))

    assert exchanged_roles, "expected the exchanged credential to carry roles at all"
    assert exchanged_roles.issubset(human_roles), (exchanged_roles, human_roles)


def test_credential_lifetime_bounded(verification_env):
    """AC-10 / property 9: the exchanged credential carries an exp strictly
    greater than iat and no larger than the realm's configured 60s access
    token lifespan (see docs/security/adr-038/... Phase 7 for the dedicated
    expiry-enforcement and reuse-cannot-extend proofs)."""
    env = verification_env
    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )

    lifetime = validated["exp"] - validated["iat"]
    assert 0 < lifetime <= 60, lifetime


def test_downstream_validation_is_independent_per_audience(verification_env):
    """AC-9 / property 8: Audience A's validator and Audience B's validator
    are separate objects with no shared state, each independently verifying
    signature/issuer/audience/expiry against the same JWKS -- proven by
    successfully validating two DIFFERENT credentials (issued for two
    different audiences) with two DIFFERENTLY-CONFIGURED validator
    instances, and by test_negative_delegation.py's cross-audience-rejection
    tests showing neither validator accepts the other's credential."""
    env = verification_env
    cred_a = _exchange_for(env, "emg-verification-audience-a")
    cred_b = _exchange_for(env, "emg-verification-audience-b")

    validator_a = _validator_for(env, "emg-verification-audience-a")
    validator_b = _validator_for(env, "emg-verification-audience-b")

    assert validator_a.validate(cred_a["access_token"])["aud"] == "emg-verification-audience-a"
    assert validator_b.validate(cred_b["access_token"])["aud"] == "emg-verification-audience-b"


def test_delegated_credential_carries_both_identities_for_audit(verification_env):
    """AC-11 (structural half) / property 10: the mapped DelegatedCredential
    exposes BOTH the Human Principal (human_subject) and the Acting Service
    (acting_service) as independent, non-null fields -- the precondition for
    complete audit attribution. The full audit-service integration proof
    (posting and reading back a real audit event carrying both identities)
    is in test_audit_attribution.py."""
    env = verification_env
    exchanged = _exchange_for(env, "emg-verification-audience-a")
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        exchanged["access_token"]
    )
    credential = to_delegated_credential(validated)

    assert credential.human_subject is not None
    assert credential.acting_service is not None
    assert credential.human_subject != credential.acting_service
