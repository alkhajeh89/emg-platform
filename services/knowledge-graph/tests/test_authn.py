"""TenantServiceTokenValidator tests (ADR-026 Revision 2, Amendment 2,
Group D5).

Uses a locally-generated RSA keypair injected via `signing_key_resolver`
(the same pattern `services/identity/tests/test_service_token_validator.py`
uses) so these tests never require a live Keycloak/JWKS endpoint. Focused on
the new `classification_clearance` claim extraction into
`ServicePrincipal.attributes`, alongside the pre-existing `tenant_claim`
extraction it is modeled on — proving neither regresses the other.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_errors import AuthorizationError
from emg_knowledge_graph_api.authn import TenantServiceTokenValidator
from emg_knowledge_graph_api.config import Settings


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        keycloak_base_url="http://keycloak.test",
        keycloak_realm="emg-test",
        service_token_audience="emg-internal-services",
    )


@pytest.fixture
def validator(settings, rsa_keypair) -> TenantServiceTokenValidator:
    _, public_key = rsa_keypair
    return TenantServiceTokenValidator(settings, signing_key_resolver=lambda token: public_key)


def _issue_service_token(
    settings,
    private_key,
    *,
    client_id="emg-svc-identity",
    scope="svc-identity",
    roles=("service-account", "svc-identity"),
    tenant_id="tenant-a",
    exp_delta=300,
    classification_clearance=None,
):
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + exp_delta,
        "iss": settings.keycloak_issuer,
        "aud": settings.service_token_audience,
        "azp": client_id,
        "scope": scope,
        "realm_access": {"roles": list(roles)},
        "tenant_id": tenant_id,
    }
    if classification_clearance is not None:
        payload["classification_clearance"] = classification_clearance
    return jwt.encode(payload, private_key, algorithm="RS256")


def test_validate_extracts_classification_clearance_claim_into_attributes(
    settings, rsa_keypair, validator
):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, classification_clearance="CONFIDENTIAL")

    caller = validator.validate(token)

    assert caller.principal.attributes == {"classification_clearance": "CONFIDENTIAL"}


def test_validate_defaults_to_unclassified_when_claim_is_absent(settings, rsa_keypair, validator):
    """ADR-026 Revision 2 §8.4: an unresolved clearance is not an
    authentication failure — unlike a missing tenant_claim (still rejected
    below), the token is still accepted, resolved to the platform's lowest
    clearance, fail-closed."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key)  # no classification_clearance claim

    caller = validator.validate(token)

    assert caller.principal.attributes == {"classification_clearance": "UNCLASSIFIED"}


@pytest.mark.parametrize("bogus_value", ["banana", "SUPER_SECRET", "foobar"])
def test_validate_defaults_to_unclassified_when_claim_is_unrecognized(
    settings, rsa_keypair, validator, bogus_value
):
    """ADR-026 final blocker: an unrecognized `classification_clearance`
    claim value (not a `Classification` enum member) must resolve to
    `"UNCLASSIFIED"` — it must never survive normalization unchanged."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, classification_clearance=bogus_value)

    caller = validator.validate(token)

    assert caller.principal.attributes == {"classification_clearance": "UNCLASSIFIED"}


@pytest.mark.parametrize("valid_value", ["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"])
def test_validate_preserves_every_valid_classification_enum_member(
    settings, rsa_keypair, validator, valid_value
):
    """Every recognized `Classification` enum member must survive
    normalization completely unchanged, not just `"CONFIDENTIAL"` (covered
    above)."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, classification_clearance=valid_value)

    caller = validator.validate(token)

    assert caller.principal.attributes == {"classification_clearance": valid_value}


def test_validate_still_requires_tenant_claim(settings, rsa_keypair, validator):
    """The new classification_clearance extraction must not weaken the
    existing, required tenant_claim behavior (Sprint 7.4) — a token missing
    tenant_id is still rejected outright, regardless of clearance."""
    private_key, _ = rsa_keypair
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,
        "iss": settings.keycloak_issuer,
        "aud": settings.service_token_audience,
        "azp": "emg-svc-identity",
        "scope": "",
        "realm_access": {"roles": ["service-account", "svc-identity"]},
        "classification_clearance": "SECRET",
        # tenant_id deliberately omitted
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_still_resolves_tenant_and_roles(settings, rsa_keypair, validator):
    """The new `attributes` extraction is additive — tenant resolution and
    role extraction (pre-existing Sprint 7.4 behavior) are unaffected."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(
        settings,
        private_key,
        roles=("service-account", "svc-identity", "investigator"),
        tenant_id="tenant-b",
    )

    caller = validator.validate(token)

    assert caller.tenant.value == "tenant-b"
    assert "investigator" in caller.principal.roles
    assert caller.principal.client_id == "emg-svc-identity"


def test_validate_rejects_unknown_service_client(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(
        settings,
        private_key,
        client_id="emg-svc-unknown",
    )
    with pytest.raises(AuthorizationError, match="Unrecognized"):
        validator.validate(token)


def test_validate_rejects_missing_registered_role(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(
        settings,
        private_key,
        roles=("service-account",),
    )
    with pytest.raises(AuthorizationError, match="required registered roles"):
        validator.validate(token)
