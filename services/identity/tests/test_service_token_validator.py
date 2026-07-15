"""ServiceTokenValidator tests (FEAT-02-3).

Uses a locally-generated RSA keypair injected via `signing_key_resolver` so
these tests never require a live Keycloak/JWKS endpoint (see
service_token_validator.py's module docstring). Covers the Sprint 3 testing
requirements: successful Client Credentials-derived token validation,
invalid audience, invalid issuer, expired token, tampered token, and missing
required scope.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_errors import AuthorizationError
from emg_identity.service_token_validator import ServiceTokenValidator


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _issue_service_token(
    settings,
    private_key,
    *,
    client_id="emg-svc-authorization",
    scope="svc-authorization",
    audience=None,
    issuer=None,
    exp_delta=300,
):
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + exp_delta,
        "iss": issuer if issuer is not None else settings.keycloak_issuer,
        "aud": audience if audience is not None else settings.service_token_audience,
        "azp": client_id,
        "scope": scope,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture
def validator(settings, rsa_keypair) -> ServiceTokenValidator:
    _, public_key = rsa_keypair
    return ServiceTokenValidator(settings, signing_key_resolver=lambda token: public_key)


def test_validate_accepts_well_formed_service_token(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key)

    principal = validator.validate(token)

    assert principal.client_id == "emg-svc-authorization"
    assert principal.service_name == "authorization"
    assert "svc-authorization" in principal.roles


def test_validate_rejects_unregistered_client(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, client_id="not-a-registered-client")

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_rejects_wrong_audience(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, audience="some-other-audience")

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_rejects_wrong_issuer(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(
        settings, private_key, issuer="http://not-the-real-keycloak.test/realms/emg-test"
    )

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_rejects_expired_token(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, exp_delta=-500)

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_rejects_tampered_token(settings, rsa_keypair, validator):
    """Corrupts a middle character of the signature segment (see
    test_session.py's test_verify_rejects_tampered_signature docstring for
    why the last character is not a reliable choice)."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key)
    header_b64, payload_b64, signature_b64 = token.split(".")
    mid = len(signature_b64) // 2
    corrupted_char = "A" if signature_b64[mid] != "A" else "B"
    tampered_signature = signature_b64[:mid] + corrupted_char + signature_b64[mid + 1 :]
    tampered = f"{header_b64}.{payload_b64}.{tampered_signature}"

    with pytest.raises(AuthorizationError):
        validator.validate(tampered)


def test_validate_rejects_missing_required_scope(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, scope="")

    with pytest.raises(AuthorizationError):
        validator.validate(token, required_scope="svc-authorization-write")


def test_validate_accepts_scope_satisfied_by_registered_role(settings, rsa_keypair, validator):
    """A required scope that matches one of the client's registered
    least-privilege roles (service_registry.py) is accepted even if the
    token's own `scope` claim is empty — the registry is the authoritative
    allow-list, the token's self-declared scope is advisory on top of it."""
    private_key, _ = rsa_keypair
    token = _issue_service_token(settings, private_key, scope="")

    principal = validator.validate(token, required_scope="svc-authorization")

    assert principal.client_id == "emg-svc-authorization"
