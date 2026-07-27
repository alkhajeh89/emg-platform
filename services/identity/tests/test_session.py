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
    """Regression-safe tamper test (Sprint 3 fix): flipping only the final
    base64url character of a JWT is not a reliable tamper, because the last
    character of a base64url-encoded 32-byte HMAC digest carries 2
    "don't-care" padding bits — roughly 1 signature in 4 decodes to the
    identical bytes after that specific character is flipped, making the
    original test flaky (observed failing during Sprint 3 verification).
    Corrupting a character in the middle of the signature segment instead
    is deterministic: any single-character change there always changes the
    decoded signature bytes.
    """
    pair = manager.issue(principal)
    header_b64, payload_b64, signature_b64 = pair.access_token.split(".")
    mid = len(signature_b64) // 2
    corrupted_char = "A" if signature_b64[mid] != "A" else "B"
    tampered_signature = signature_b64[:mid] + corrupted_char + signature_b64[mid + 1 :]
    tampered = f"{header_b64}.{payload_b64}.{tampered_signature}"

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


# --- Group D Phase 1 Remediation: Legacy Session Normalization -------------
#
# A legacy EMG session token is one minted before this remediation existed,
# whose own `attributes` claim was persisted as `{}` (or missing
# classification_clearance) at issuance time. `SessionManager.issue()`
# writes whatever `principal.attributes` it is given verbatim (_mint does
# not normalize at write time -- only verify() does, at read time), so
# `manager.issue(Principal(..., attributes={}))` below is the exact,
# real-code-path way to reproduce a legacy token for these tests, not a
# simulation of one.


def test_legacy_session_with_empty_attributes_normalizes_on_verify(manager):
    legacy_principal = Principal(subject="dev.legacy", roles=("platform-user",), attributes={})
    pair = manager.issue(legacy_principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "UNCLASSIFIED"


def test_legacy_refresh_token_normalizes_new_session(manager):
    legacy_principal = Principal(subject="dev.legacy", roles=("platform-user",), attributes={})
    pair = manager.issue(legacy_principal)

    refreshed = manager.refresh(pair.refresh_token)
    claims = manager.verify(refreshed.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "UNCLASSIFIED"


def test_legacy_refresh_rotated_refresh_token_also_normalizes(manager):
    """The rotated refresh token itself (not just the paired access token)
    must also carry the normalized value once re-minted, since
    SessionManager.refresh() re-issues from the now-normalized Principal."""
    legacy_principal = Principal(subject="dev.legacy", roles=("platform-user",), attributes={})
    pair = manager.issue(legacy_principal)

    refreshed = manager.refresh(pair.refresh_token)
    refresh_claims = manager.verify(refreshed.refresh_token, expected_type="refresh")

    assert refresh_claims.attributes["classification_clearance"] == "UNCLASSIFIED"


def test_valid_clearance_survives_normalization_unchanged(manager, principal):
    """principal already carries a valid classification_clearance
    ("INTERNAL") -- normalization must not alter it."""
    pair = manager.issue(principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "INTERNAL"


def test_empty_string_clearance_normalizes_to_unclassified(manager):
    principal = Principal(
        subject="dev.blank",
        roles=("platform-user",),
        attributes={"classification_clearance": ""},
    )
    pair = manager.issue(principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "UNCLASSIFIED"


def test_whitespace_only_clearance_normalizes_to_unclassified(manager):
    principal = Principal(
        subject="dev.whitespace",
        roles=("platform-user",),
        attributes={"classification_clearance": "   "},
    )
    pair = manager.issue(principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "UNCLASSIFIED"


def test_non_string_clearance_normalizes_to_unclassified(settings, manager):
    """A malformed token whose `attributes.classification_clearance` claim
    is not even a string (e.g. a stray integer from some long-past bug) --
    constructed via raw jwt.encode since Principal.attributes is typed
    dict[str, str] and would not let a real caller build this shape."""
    now = time.time()
    payload = {
        "sub": "dev.malformed",
        "roles": ["platform-user"],
        "attributes": {"classification_clearance": 12345},
        "token_type": "access",
        "jti": "malformed-clearance",
        "iat": int(now),
        "exp": int(now) + 900,
        "iss": settings.token_issuer,
        "aud": settings.token_audience,
    }
    token = jwt.encode(
        payload, settings.session_signing_key, algorithm=settings.session_signing_algorithm
    )

    claims = manager.verify(token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "UNCLASSIFIED"


@pytest.mark.parametrize("bogus_value", ["banana", "SUPER_SECRET", "foobar"])
def test_unrecognized_clearance_string_normalizes_to_unclassified(manager, bogus_value):
    """ADR-026 final blocker: an unrecognized `classification_clearance`
    string (not a `Classification` enum member) must never survive
    normalization unchanged -- it must resolve to `"UNCLASSIFIED"`, exactly
    like a missing/blank/non-string value. Covers a fresh human login-style
    Principal (issue -> verify)."""
    principal = Principal(
        subject="dev.bogus",
        roles=("platform-user",),
        attributes={"classification_clearance": bogus_value},
    )
    pair = manager.issue(principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "UNCLASSIFIED"


@pytest.mark.parametrize("bogus_value", ["banana", "SUPER_SECRET", "foobar"])
def test_legacy_session_with_unrecognized_clearance_normalizes_on_verify(manager, bogus_value):
    """ADR-026 final blocker: a legacy-shaped session token carrying an
    unrecognized `classification_clearance` value (e.g. from a stale/forged
    claim predating enum validation) must be corrected to `"UNCLASSIFIED"`
    at `verify()` time, the same as the empty/whitespace/non-string legacy
    cases above."""
    legacy_principal = Principal(
        subject="dev.legacy.bogus",
        roles=("platform-user",),
        attributes={"classification_clearance": bogus_value},
    )
    pair = manager.issue(legacy_principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == "UNCLASSIFIED"


@pytest.mark.parametrize("valid_value", ["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"])
def test_all_valid_classification_enum_members_survive_normalization_unchanged(
    manager, valid_value
):
    """Every recognized `Classification` enum member must pass through
    normalization completely unchanged, not just the one ("INTERNAL") used
    by the `principal` fixture above."""
    principal = Principal(
        subject="dev.valid",
        roles=("platform-user",),
        attributes={"classification_clearance": valid_value},
    )
    pair = manager.issue(principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["classification_clearance"] == valid_value


def test_department_omitted_when_legacy_attributes_empty(manager):
    """Normalization must not invent a department the way it defaults
    classification_clearance -- a legacy session with no department claim
    simply has none, exactly as before this remediation."""
    legacy_principal = Principal(subject="dev.legacy", roles=("platform-user",), attributes={})
    pair = manager.issue(legacy_principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert "department" not in claims.attributes


def test_department_preserved_unchanged_through_normalization(manager, principal):
    """principal already carries a department ("Investigations") --
    normalization (which only ever touches classification_clearance) must
    leave it exactly as-is."""
    pair = manager.issue(principal)

    claims = manager.verify(pair.access_token, expected_type="access")

    assert claims.attributes["department"] == "Investigations"
