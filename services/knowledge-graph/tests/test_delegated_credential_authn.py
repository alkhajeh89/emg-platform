"""DelegatedCredentialValidator tests (Phase 2B, ADR-038). Mirrors
test_authn.py's exact fixture/injection pattern."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_auth_client import Principal
from emg_errors import AuthorizationError
from emg_knowledge_graph_api.authn import (
    AuthenticatedCallerDep,  # noqa: F401 - import-surface check
    DelegatedCredentialValidator,
    require_authenticated_caller,
)
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
        delegated_credential_audience="emg-knowledge-graph-audience",
    )


@pytest.fixture
def validator(settings, rsa_keypair) -> DelegatedCredentialValidator:
    _, public_key = rsa_keypair
    return DelegatedCredentialValidator(settings, signing_key_resolver=lambda token: public_key)


def _issue_delegated_credential(
    settings,
    private_key,
    *,
    azp="emg-studio-bff",
    sub="human-a",
    roles=("investigator", "platform-user"),
    tenant_id="tenant-a",
    classification_clearance="CONFIDENTIAL",
    exp_delta=300,
    omit_sub=False,
    omit_jti=False,
    aud=None,
):
    now = int(time.time())
    payload: dict[str, object] = {
        "iat": now,
        "exp": now + exp_delta,
        "iss": settings.keycloak_issuer,
        "aud": aud if aud is not None else settings.delegated_credential_audience,
        "azp": azp,
        "realm_access": {"roles": list(roles)},
        "tenant_id": tenant_id,
    }
    if not omit_jti:
        payload["jti"] = str(uuid.uuid4())
    if not omit_sub:
        payload["sub"] = sub
    if classification_clearance is not None:
        payload["classification_clearance"] = classification_clearance
    return jwt.encode(payload, private_key, algorithm="RS256")


def test_validate_accepts_a_well_formed_delegated_credential(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_delegated_credential(settings, private_key)

    context = validator.validate(token)

    assert isinstance(context.principal, Principal)
    assert context.principal.subject == "human-a"
    assert context.acting_service == "emg-studio-bff"
    assert context.tenant.value == "tenant-a"


def test_validate_preserves_human_subject_exactly(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_delegated_credential(settings, private_key, sub="a-specific-human-subject-id")

    context = validator.validate(token)
    assert context.principal.subject == "a-specific-human-subject-id"


def test_validate_extracts_tenant_and_clearance(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_delegated_credential(
        settings, private_key, tenant_id="tenant-xyz", classification_clearance="SECRET"
    )

    context = validator.validate(token)
    assert context.tenant.value == "tenant-xyz"
    assert context.principal.attributes["classification_clearance"] == "SECRET"


def test_validate_rejects_unrecognized_acting_service(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    token = _issue_delegated_credential(settings, private_key, azp="some-other-client")

    with pytest.raises(AuthorizationError, match="Unrecognized Acting Service"):
        validator.validate(token)


def test_validate_rejects_missing_sub_never_proceeds_silently(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    # PyJWT's own `require: ["sub", ...]` enforcement rejects a token
    # missing `sub` before this validator's own explicit check even runs —
    # both layers independently guarantee no silent proceed.
    now = int(time.time())
    token = jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": settings.delegated_credential_audience,
            "azp": "emg-studio-bff",
            "jti": str(uuid.uuid4()),
            "realm_access": {"roles": ["investigator"]},
            "tenant_id": "tenant-a",
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_rejects_missing_tenant(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    now = int(time.time())
    token = jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": settings.delegated_credential_audience,
            "azp": "emg-studio-bff",
            "jti": str(uuid.uuid4()),
            "sub": "human-a",
            "realm_access": {"roles": ["investigator"]},
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(AuthorizationError, match="tenant_id"):
        validator.validate(token)


def test_validate_rejects_wrong_audience(settings, rsa_keypair, validator):
    private_key, _ = rsa_keypair
    now = int(time.time())
    token = jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": "some-other-audience",
            "azp": "emg-studio-bff",
            "jti": str(uuid.uuid4()),
            "sub": "human-a",
            "realm_access": {"roles": ["investigator"]},
            "tenant_id": "tenant-a",
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_rejects_multi_audience_credential_even_if_expected_audience_is_present(
    settings, rsa_keypair, validator
):
    """Correction-sprint Finding 7b (ADR-038 §7.4: 'exactly one downstream
    audience'). PyJWT's own `audience=` check only confirms membership; a
    token whose `aud` names MULTIPLE audiences — even including the correct
    one — must still be rejected."""
    private_key, _ = rsa_keypair
    token = _issue_delegated_credential(
        settings, private_key, aud=[settings.delegated_credential_audience, "some-other-audience"]
    )

    with pytest.raises(AuthorizationError, match="exactly one"):
        validator.validate(token)


def test_validate_rejects_credential_missing_jti(settings, rsa_keypair, validator):
    """Correction-sprint Finding 7a (ADR-038 §7.3: 'unique credential
    identifier' is a mandatory property)."""
    private_key, _ = rsa_keypair
    token = _issue_delegated_credential(settings, private_key, omit_jti=True)

    with pytest.raises(AuthorizationError):
        validator.validate(token)


def test_validate_defaults_to_unclassified_when_clearance_claim_absent(
    settings, rsa_keypair, validator
):
    private_key, _ = rsa_keypair
    token = _issue_delegated_credential(settings, private_key, classification_clearance=None)

    context = validator.validate(token)
    assert context.principal.attributes["classification_clearance"] == "UNCLASSIFIED"


def test_require_authenticated_caller_routes_recognized_acting_service_to_delegated_validator(
    settings, rsa_keypair
):
    """Confirms the combined dependency's own selection logic, not just the
    validator in isolation."""
    from unittest.mock import Mock

    from fastapi.security import HTTPAuthorizationCredentials

    private_key, _ = rsa_keypair
    delegated_token = _issue_delegated_credential(settings, private_key)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=delegated_token)

    delegated_validator = Mock()
    delegated_validator.validate.return_value = "delegated-result"
    tenant_validator = Mock()

    result = require_authenticated_caller(credentials, tenant_validator, delegated_validator)

    assert result == "delegated-result"
    delegated_validator.validate.assert_called_once_with(delegated_token)
    tenant_validator.validate.assert_not_called()


def test_require_authenticated_caller_falls_back_to_tenant_validator_for_unrecognized_azp(
    settings, rsa_keypair
):
    from unittest.mock import Mock

    from fastapi.security import HTTPAuthorizationCredentials

    private_key, _ = rsa_keypair
    now = int(time.time())
    service_token = jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": "emg-internal-services",
            "azp": "emg-svc-identity",
        },
        private_key,
        algorithm="RS256",
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=service_token)

    delegated_validator = Mock()
    tenant_validator = Mock()
    tenant_validator.validate.return_value = "service-result"

    result = require_authenticated_caller(credentials, tenant_validator, delegated_validator)

    assert result == "service-result"
    tenant_validator.validate.assert_called_once_with(service_token)
    delegated_validator.validate.assert_not_called()
