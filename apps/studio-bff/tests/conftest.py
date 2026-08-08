"""Test fixtures for the Studio BFF.

Uses a locally-generated RSA keypair (the same pattern
`services/audit/tests/conftest.py` and `services/knowledge-graph/tests/test_authn.py`
already establish) so no Docker, Redis, or live Keycloak is required. The
Keycloak *token endpoint* itself (`exchange_code_for_tokens`,
`refresh_tokens`, `token_exchange`-equivalent) is monkeypatched per-test to
return locally-signed tokens — this suite tests the BFF's own logic
(session handling, cookie flags, fail-closed behaviour, claim mapping), not
Keycloak's wire protocol, which the ADR-038 capability-verification suite
(`tests/security/adr_038/`) already exercises against a real instance.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_studio_bff import oidc
from emg_studio_bff.config import Settings
from emg_studio_bff.dependencies import session_store_dependency, settings_dependency
from emg_studio_bff.main import create_app
from emg_studio_bff.session_store import InMemorySessionStore
from fastapi.testclient import TestClient

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
        oidc_redirect_uri="http://bff.test/auth/callback",
        studio_frontend_url="http://studio.test",
        knowledge_graph_audience="emg-kg-audience-test",
        knowledge_graph_base_url="http://kg.test",
        session_cookie_name="__Host-emg_studio_session",
        csrf_cookie_name="__Host-emg_studio_csrf",
        session_ttl_seconds=60,
        session_absolute_ttl_seconds=3600,
        session_refresh_margin_seconds=60,
    )


@pytest.fixture
def session_store(settings) -> InMemorySessionStore:
    return InMemorySessionStore(pre_auth_ttl_seconds=settings.pre_auth_ttl_seconds)


def _issue(private_key, *, claims: dict, exp_delta: int = 300) -> str:
    now = int(time.time())
    payload = {"iat": now, "exp": now + exp_delta, "iss": ISSUER, **claims}
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture
def issue_id_token(rsa_keypair, settings):
    private_key, _ = rsa_keypair

    def _make(*, nonce: str, sub: str = "human-a", exp_delta: int = 300) -> str:
        return _issue(
            private_key,
            claims={"aud": settings.oidc_client_id, "sub": sub, "nonce": nonce},
            exp_delta=exp_delta,
        )

    return _make


@pytest.fixture
def issue_access_token(rsa_keypair, settings):
    private_key, _ = rsa_keypair

    def _make(
        *,
        sub: str = "human-a",
        tenant_id: str | None = "tenant-a",
        clearance: str | None = "CONFIDENTIAL",
        roles: tuple[str, ...] = ("investigator", "platform-user"),
        azp: str | None = ...,  # sentinel: default to settings.oidc_client_id
        exp_delta: int = 300,
    ) -> str:
        claims: dict[str, object] = {"sub": sub, "realm_access": {"roles": list(roles)}}
        if tenant_id is not None:
            claims["tenant_id"] = tenant_id
        if clearance is not None:
            claims["classification_clearance"] = clearance
        resolved_azp = settings.oidc_client_id if azp is ... else azp
        if resolved_azp is not None:
            claims["azp"] = resolved_azp
        return _issue(private_key, claims=claims, exp_delta=exp_delta)

    return _make


@pytest.fixture(autouse=True)
def _patch_signing_key_resolver(monkeypatch, rsa_keypair):
    """Every verification call in this suite uses the test RSA public key
    instead of a live JWKS endpoint — mirrors the injectable-resolver
    pattern `services/knowledge-graph/.../authn.py` already established."""
    _, public_key = rsa_keypair
    monkeypatch.setattr(
        oidc, "_default_signing_key_resolver", lambda settings: (lambda token: public_key)
    )


@pytest.fixture
def client(settings, session_store, monkeypatch) -> TestClient:
    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[session_store_dependency] = lambda: session_store
    return TestClient(app, base_url="https://bff.test")


@pytest.fixture
def patch_token_exchange(monkeypatch, rsa_keypair):
    """Patches emg_studio_bff.oidc.exchange_code_for_tokens so
    /auth/callback never makes a real HTTP call. Returns a setter the test
    calls with the id/access tokens it wants issued for a given code."""

    async def _default(*, settings, code, code_verifier):
        raise AssertionError("exchange_code_for_tokens called before the test set a response")

    state = {"fn": _default}

    async def _dispatch(settings, *, code, code_verifier):
        return await state["fn"](settings=settings, code=code, code_verifier=code_verifier)

    monkeypatch.setattr("emg_studio_bff.routers.auth.oidc.exchange_code_for_tokens", _dispatch)

    def _set(fn):
        state["fn"] = fn

    return _set
