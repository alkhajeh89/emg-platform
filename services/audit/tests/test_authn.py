"""ServiceTokenValidator tests for the audit service (ADR-026 Revision 2,
Amendment 2, Group D5).

Uses a locally-generated RSA keypair injected via `signing_key_resolver`
(the same pattern `services/identity/tests/test_service_token_validator.py`
uses) so these tests never require a live Keycloak/JWKS endpoint. Focused on
the new `classification_clearance` claim extraction into
`ServicePrincipal.attributes`; the pre-existing client-recognition/scope
behavior is already covered by `test_audit_api.py` et al. and is not
duplicated here.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_audit_service.authn import ServiceTokenValidator
from emg_errors import AuthorizationError


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _issue_service_token(
    settings,
    private_key,
    *,
    client_id="emg-svc-audit",
    scope="svc-audit",
    exp_delta=300,
    classification_clearance=None,
    tenant_id="tenant-a",
    token_roles=None,
):
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + exp_delta,
        "iss": settings.keycloak_issuer,
        "aud": settings.service_token_audience,
        "azp": client_id,
        "scope": scope,
        "tenant_id": tenant_id,
        "realm_access": {
            "roles": (["service-account", scope] if token_roles is None else list(token_roles))
        },
    }
    if classification_clearance is not None:
        payload["classification_clearance"] = classification_clearance
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture
def validator(settings, rsa_keypair) -> ServiceTokenValidator:
    _, public_key = rsa_keypair
    return ServiceTokenValidator(settings, signing_key_resolver=lambda token: public_key)


def test_validate_extracts_classification_clearance_claim_into_attributes(
    settings, rsa_keypair, validator
):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, classification_clearance="SECRET")

    principal = validator.validate(token)

    assert principal.attributes == {"classification_clearance": "SECRET"}


def test_validate_rejects_missing_tenant(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, tenant_id=None)
    with pytest.raises(AuthorizationError, match="tenant_id"):
        validator.validate(token)


def test_validate_rejects_missing_registered_role(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(
        settings,
        private_key,
        token_roles=("service-account",),
    )
    with pytest.raises(AuthorizationError, match="required registered roles"):
        validator.validate(token)


def test_validate_defaults_to_unclassified_when_claim_is_absent(settings, rsa_keypair, validator):
    """ADR-026 Revision 2 §8.4: an unresolved clearance is not an
    authentication failure — the token is still accepted, resolved to the
    platform's lowest clearance, fail-closed."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key)  # no classification_clearance claim

    principal = validator.validate(token)

    assert principal.attributes == {"classification_clearance": "UNCLASSIFIED"}


@pytest.mark.parametrize("bogus_value", ["banana", "SUPER_SECRET", "foobar"])
def test_validate_defaults_to_unclassified_when_claim_is_unrecognized(
    settings, rsa_keypair, validator, bogus_value
):
    """ADR-026 final blocker: an unrecognized `classification_clearance`
    claim value (not a `Classification` enum member) must resolve to
    `"UNCLASSIFIED"` — it must never survive normalization unchanged."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, classification_clearance=bogus_value)

    principal = validator.validate(token)

    assert principal.attributes == {"classification_clearance": "UNCLASSIFIED"}


@pytest.mark.parametrize("valid_value", ["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"])
def test_validate_preserves_every_valid_classification_enum_member(
    settings, rsa_keypair, validator, valid_value
):
    """Every recognized `Classification` enum member must survive
    normalization completely unchanged, not just `"SECRET"`/`"INTERNAL"`
    (covered above)."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, classification_clearance=valid_value)

    principal = validator.validate(token)

    assert principal.attributes == {"classification_clearance": valid_value}


def test_validate_still_populates_roles_and_service_name(settings, rsa_keypair, validator):
    """The new `attributes` extraction is additive — client recognition,
    service_name, and roles resolution (pre-existing behavior) are
    unaffected."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, classification_clearance="INTERNAL")

    principal = validator.validate(token)

    assert principal.client_id == "emg-svc-audit"
    assert principal.service_name == "audit"
    assert "svc-audit" in principal.roles


def test_explicit_projector_client_is_recognized(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    projector_id = "emg-svc-audit-projector-tenant-a"
    configured = settings.model_copy(update={"projector_client_ids": (projector_id,)})
    validator = ServiceTokenValidator(configured, signing_key_resolver=lambda token: public_key)
    token = _issue_service_token(
        configured,
        private_key,
        client_id=projector_id,
        scope="svc-audit-projector",
    )

    principal = validator.validate(token)

    assert principal.client_id == projector_id
    assert principal.service_name == "audit-projector"
    assert principal.tenant_id == "tenant-a"


def test_unconfigured_projector_client_is_rejected(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(
        settings,
        private_key,
        client_id="emg-svc-audit-projector-tenant-a",
        scope="svc-audit-projector",
    )

    with pytest.raises(AuthorizationError, match="Unrecognized service client"):
        validator.validate(token)
