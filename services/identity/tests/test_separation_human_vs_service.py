"""Structural separation between human sessions and service identities
(FEAT-02-3 Required Security Control: "Separation between human and machine
identities").

The separation is cryptographic, not a flag check: EMG session tokens are
HS256-signed by the identity service itself; Keycloak service-account tokens
are RS256-signed by the realm key. `jwt.decode(..., algorithms=[...])`
rejects a token signed with a different algorithm before any claim is even
inspected, so these tests assert the two verifiers are mutually exclusive by
construction, not just by convention.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_auth_client import Principal
from emg_errors import AuthorizationError
from emg_identity.service_token_validator import ServiceTokenValidator
from emg_identity.session import SessionManager


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def test_human_session_token_rejected_by_service_token_validator(settings, rsa_keypair):
    """A human EMG access token (HS256) presented where a service token
    (RS256) is required must be rejected — Testing Requirement: "Human token
    used where service token required."""
    _, public_key = rsa_keypair
    session_manager = SessionManager(settings)
    principal = Principal(subject="dev.investigator", roles=("platform-user",), attributes={})
    pair = session_manager.issue(principal)

    validator = ServiceTokenValidator(settings, signing_key_resolver=lambda token: public_key)

    with pytest.raises(AuthorizationError):
        validator.validate(pair.access_token)


def test_service_token_rejected_by_session_manager(settings, rsa_keypair):
    """A Keycloak service-account token (RS256) presented where a human
    session token (HS256) is required must be rejected — Testing
    Requirement: "Service token used where human session required."""
    private_key, _ = rsa_keypair
    now = int(time.time())
    service_token = jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": settings.service_token_audience,
            "azp": "emg-svc-authorization",
            "scope": "svc-authorization",
        },
        private_key,
        algorithm="RS256",
    )

    session_manager = SessionManager(settings)
    with pytest.raises(AuthorizationError):
        session_manager.verify(service_token, expected_type="access")
