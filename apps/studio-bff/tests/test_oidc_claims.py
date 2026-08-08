"""Direct unit tests for `oidc.verify_access_token`'s claim extraction —
final correction-sprint Finding 3. These specifically cover claim SHAPES
confirmed against a real Authorization Code flow driven against a fresh
Keycloak 25 import of the canonical realm (see
docs/security/adr-038/07_PRODUCTION_CONFIGURATION.md), not assumed."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_studio_bff import oidc
from emg_studio_bff.config import Settings

ISSUER = "http://keycloak.test/realms/emg-test"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        keycloak_base_url="http://keycloak.test",
        keycloak_realm="emg-test",
        oidc_client_id="emg-studio-bff-test",
    )


def _issue(private_key, claims: dict, exp_delta: int = 300) -> str:
    now = int(time.time())
    payload = {"iat": now, "exp": now + exp_delta, "iss": ISSUER, **claims}
    return jwt.encode(payload, private_key, algorithm="RS256")


def test_classification_clearance_unwrapped_from_single_element_list(settings, rsa_keypair):
    """Confirmed real Keycloak shape: a multivalued user-attribute mapper
    projects `["INTERNAL"]`, not `"INTERNAL"` — must still resolve to the
    scalar clearance, not silently default to UNCLASSIFIED."""
    private_key, public_key = rsa_keypair
    token = _issue(
        private_key,
        {
            "sub": "human-a",
            "azp": "emg-studio-bff-test",
            "tenant_id": "tenant-a",
            "classification_clearance": ["CONFIDENTIAL"],
            "realm_access": {"roles": ["investigator"]},
        },
    )
    identity = oidc.verify_access_token(settings, token, signing_key_resolver=lambda t: public_key)
    assert identity.classification_clearance == "CONFIDENTIAL"


def test_classification_clearance_plain_string_still_accepted(settings, rsa_keypair):
    """Backward compatible: a plain-string claim (e.g. from a mapper with
    multivalued=false) still resolves correctly."""
    private_key, public_key = rsa_keypair
    token = _issue(
        private_key,
        {
            "sub": "human-a",
            "azp": "emg-studio-bff-test",
            "tenant_id": "tenant-a",
            "classification_clearance": "SECRET",
            "realm_access": {"roles": ["investigator"]},
        },
    )
    identity = oidc.verify_access_token(settings, token, signing_key_resolver=lambda t: public_key)
    assert identity.classification_clearance == "SECRET"


def test_classification_clearance_empty_list_defaults_to_unclassified(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    token = _issue(
        private_key,
        {
            "sub": "human-a",
            "azp": "emg-studio-bff-test",
            "tenant_id": "tenant-a",
            "classification_clearance": [],
            "realm_access": {"roles": ["investigator"]},
        },
    )
    identity = oidc.verify_access_token(settings, token, signing_key_resolver=lambda t: public_key)
    assert identity.classification_clearance == "UNCLASSIFIED"


def test_missing_classification_clearance_defaults_to_unclassified(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    token = _issue(
        private_key,
        {
            "sub": "human-a",
            "azp": "emg-studio-bff-test",
            "tenant_id": "tenant-a",
            "realm_access": {"roles": ["investigator"]},
        },
    )
    identity = oidc.verify_access_token(settings, token, signing_key_resolver=lambda t: public_key)
    assert identity.classification_clearance == "UNCLASSIFIED"


def test_access_token_with_no_aud_claim_at_all_is_still_accepted(settings, rsa_keypair):
    """Confirmed real Keycloak shape: the human access token for this
    client's scope configuration carries NO `aud` claim whatsoever — a
    strict `audience=` check would reject every legitimate token. Only
    `azp` is checked."""
    private_key, public_key = rsa_keypair
    token = _issue(
        private_key,
        {
            "sub": "human-a",
            "azp": "emg-studio-bff-test",
            "tenant_id": "tenant-a",
            "realm_access": {"roles": ["investigator"]},
        },
    )
    identity = oidc.verify_access_token(settings, token, signing_key_resolver=lambda t: public_key)
    assert identity.subject == "human-a"
