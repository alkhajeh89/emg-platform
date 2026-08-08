"""AUTHENTICATION test category: valid callback, invalid state, invalid
nonce, invalid code, PKCE failure, open-redirect rejection, authorization-
code replay."""

from __future__ import annotations

import time

from emg_studio_bff import oidc
from emg_studio_bff.session_store import PendingAuthorization


def _seed_pending(session_store, *, state="state-1", nonce="nonce-1", code_verifier="verifier-1"):
    session_store.create_pending_authorization(
        PendingAuthorization(
            state=state, nonce=nonce, code_verifier=code_verifier, created_at=time.time()
        )
    )


def test_valid_authorization_callback_sets_cookie_and_redirects(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    _seed_pending(session_store)
    id_token = issue_id_token(nonce="nonce-1")
    access_token = issue_access_token()

    async def fake_exchange(*, settings, code, code_verifier):
        assert code == "auth-code-1"
        assert code_verifier == "verifier-1"
        return oidc.TokenSet(
            access_token=access_token, refresh_token="rt-1", id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)

    response = client.get(
        "/auth/callback", params={"code": "auth-code-1", "state": "state-1"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://studio.test"
    cookie_header = response.headers.get("set-cookie", "")
    assert "__Host-emg_studio_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "samesite=lax" in cookie_header.lower()


def test_invalid_state_is_rejected(client):
    response = client.get("/auth/callback", params={"code": "auth-code-1", "state": "never-issued"})
    assert response.status_code == 401


def test_invalid_nonce_is_rejected(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    _seed_pending(session_store, state="state-2", nonce="expected-nonce")
    # ID token carries a DIFFERENT nonce than what /auth/login originally issued.
    id_token = issue_id_token(nonce="attacker-supplied-nonce")
    access_token = issue_access_token()

    async def fake_exchange(*, settings, code, code_verifier):
        return oidc.TokenSet(
            access_token=access_token, refresh_token=None, id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)

    response = client.get("/auth/callback", params={"code": "code-2", "state": "state-2"})
    assert response.status_code == 401


def test_invalid_code_is_rejected(client, session_store, patch_token_exchange):
    _seed_pending(session_store, state="state-3")

    async def fake_exchange(*, settings, code, code_verifier):
        raise oidc.OidcError("token endpoint rejected the authorization code: 400")

    patch_token_exchange(fake_exchange)

    response = client.get("/auth/callback", params={"code": "bad-code", "state": "state-3"})
    assert response.status_code == 401


def test_pkce_failure_is_rejected(client, session_store, patch_token_exchange):
    """Simulates Keycloak's own PKCE enforcement rejecting a code_verifier
    that does not match the code_challenge originally sent to /authorize
    (the BFF always sends its server-stored verifier — there is no
    browser-supplied verifier anywhere in this flow; this test proves the
    BFF surfaces that rejection as a clean, fail-closed 401, not a 500 or a
    silently-accepted session)."""
    _seed_pending(session_store, state="state-4", code_verifier="the-real-verifier")

    async def fake_exchange(*, settings, code, code_verifier):
        assert code_verifier == "the-real-verifier"  # confirms the BFF sent its own stored verifier
        raise oidc.OidcError("token endpoint rejected the authorization code: 400 (PKCE mismatch)")

    patch_token_exchange(fake_exchange)

    response = client.get("/auth/callback", params={"code": "code-4", "state": "state-4"})
    assert response.status_code == 401
    assert "set-cookie" not in {k.lower() for k in response.headers}


def test_authorization_code_replay_is_rejected(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    _seed_pending(session_store, state="state-5")
    id_token = issue_id_token(nonce="nonce-1")
    access_token = issue_access_token()
    calls = {"n": 0}

    async def fake_exchange(*, settings, code, code_verifier):
        calls["n"] += 1
        return oidc.TokenSet(
            access_token=access_token, refresh_token=None, id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)

    first = client.get(
        "/auth/callback", params={"code": "code-5", "state": "state-5"}, follow_redirects=False
    )
    assert first.status_code == 302
    assert calls["n"] == 1

    # Second attempt with the SAME state: the pending record was already
    # consumed on the first call, so this must fail before ever reaching
    # the token endpoint again.
    second = client.get("/auth/callback", params={"code": "code-5", "state": "state-5"})
    assert second.status_code == 401
    assert calls["n"] == 1


def test_access_token_with_wrong_azp_is_rejected(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    """Correction-sprint Finding 8: an access token not issued to this BFF's
    own client (azp mismatch) is rejected — proves audience/azp validation
    on the human access token actually runs, not only on the ID token."""
    _seed_pending(session_store, state="state-azp")
    id_token = issue_id_token(nonce="nonce-1")
    access_token = issue_access_token(azp="some-other-client")

    async def fake_exchange(*, settings, code, code_verifier):
        return oidc.TokenSet(
            access_token=access_token, refresh_token=None, id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)

    response = client.get("/auth/callback", params={"code": "code-azp", "state": "state-azp"})
    assert response.status_code == 401


def test_access_token_with_correct_azp_is_accepted(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    _seed_pending(session_store, state="state-azp-ok")
    id_token = issue_id_token(nonce="nonce-1")
    access_token = issue_access_token()  # default azp == settings.oidc_client_id

    async def fake_exchange(*, settings, code, code_verifier):
        return oidc.TokenSet(
            access_token=access_token, refresh_token=None, id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)

    response = client.get(
        "/auth/callback",
        params={"code": "code-azp-ok", "state": "state-azp-ok"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_open_redirect_is_structurally_impossible(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    """There is no browser-supplied redirect-target parameter anywhere in
    this flow — the post-login destination is always the fixed
    `studio_frontend_url`, regardless of any extra query parameters a
    caller supplies."""
    _seed_pending(session_store, state="state-6")
    id_token = issue_id_token(nonce="nonce-1")
    access_token = issue_access_token()

    async def fake_exchange(*, settings, code, code_verifier):
        return oidc.TokenSet(
            access_token=access_token, refresh_token=None, id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)

    response = client.get(
        "/auth/callback",
        params={"code": "code-6", "state": "state-6", "redirect_uri": "https://evil.example/"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://studio.test"
