import time

import jwt
import pytest
from emg_auth_client import Principal
from emg_errors import AuthorizationError
from emg_identity.session import SessionManager


@pytest.fixture
def manager(settings) -> SessionManager:
    return SessionManager(settings)


@pytest.fixture
def principal() -> Principal:
    return Principal(
        subject="dev.investigator",
        roles=("platform-user", "investigator"),
        attributes={"classification_clearance": "INTERNAL", "department": "Investigations"},
    )


def test_issue_returns_access_and_refresh_tokens(manager, principal):
    pair = manager.issue(principal)
    assert pair.access_token != pair.refresh_token
    assert pair.access_expires_in == 900
    assert pair.refresh_expires_in == 43200


def test_verify_access_token_roundtrips_principal_claims(manager, principal):
    pair = manager.issue(principal)
    claims = manager.verify(pair.access_token, expected_type="access")
    assert claims.subject == principal.subject
    assert claims.roles == principal.roles
    assert claims.attributes == principal.attributes
    assert claims.token_type == "access"


def test_verify_rejects_wrong_token_type(manager, principal):
    pair = manager.issue(principal)
    with pytest.raises(AuthorizationError):
        manager.verify(pair.refresh_token, expected_type="access")


def test_verify_rejects_tampered_signature(manager, principal, settings):
    pair = manager.issue(principal)
    tampered = pair.access_token[:-1] + ("A" if pair.access_token[-1] != "A" else "B")
    with pytest.raises(AuthorizationError):
        manager.verify(tampered, expected_type="access")


def test_verify_rejects_expired_token(manager, principal, settings):
    # Mint a token that already expired, bypassing SessionManager's TTL.
    now = time.time()
    payload = {
        "sub": principal.subject,
        "roles": list(principal.roles),
        "attributes": dict(principal.attributes),
        "token_type": "access",
        "jti": "expired-token",
        "iat": int(now) - 1000,
        "exp": int(now) - 500,
        "iss": settings.token_issuer,
        "aud": settings.token_audience,
    }
    expired = jwt.encode(
        payload, settings.session_signing_key, algorithm=settings.session_signing_algorithm
    )
    with pytest.raises(AuthorizationError):
        manager.verify(expired, expected_type="access")


def test_verify_rejects_wrong_issuer(manager, principal, settings):
    now = time.time()
    payload = {
        "sub": principal.subject,
        "roles": [],
        "attributes": {},
        "token_type": "access",
        "jti": "bad-issuer",
        "iat": int(now),
        "exp": int(now) + 900,
        "iss": "not-emg-identity-service",
        "aud": settings.token_audience,
    }
    forged = jwt.encode(
        payload, settings.session_signing_key, algorithm=settings.session_signing_algorithm
    )
    with pytest.raises(AuthorizationError):
        manager.verify(forged, expected_type="access")


def test_refresh_rotates_tokens_and_preserves_claims(manager, principal):
    pair1 = manager.issue(principal)
    pair2 = manager.refresh(pair1.refresh_token)
    assert pair2.access_token != pair1.access_token
    assert pair2.refresh_token != pair1.refresh_token
    claims = manager.verify(pair2.access_token, expected_type="access")
    assert claims.subject == principal.subject
    assert claims.roles == principal.roles


def test_refresh_rejects_access_token_presented_as_refresh(manager, principal):
    pair = manager.issue(principal)
    with pytest.raises(AuthorizationError):
        manager.refresh(pair.access_token)
