"""BROWSER SECURITY test category: no service token exposed, no delegated
token exposed, no token persistence in browser storage (i.e. no token
content anywhere in a response body or Set-Cookie value)."""

from __future__ import annotations

import time

from emg_studio_bff.session_store import HumanSession


def _seed_session(session_store, *, session_id="sess-sec") -> HumanSession:
    session = HumanSession(
        session_id=session_id,
        subject="human-a",
        tenant_id="tenant-a",
        classification_clearance="CONFIDENTIAL",
        roles=("investigator",),
        access_token="THE-HUMAN-ACCESS-TOKEN-SECRET-VALUE",
        refresh_token="THE-HUMAN-REFRESH-TOKEN-SECRET-VALUE",
        access_token_expires_at=time.time() + 300,
        created_at=time.time(),
        csrf_token="csrf-token-value",
    )
    session_store.create_session(session)
    return session


def test_session_response_never_contains_token_content(client, session_store):
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-sec")

    response = client.get("/auth/session")
    assert "THE-HUMAN-ACCESS-TOKEN-SECRET-VALUE" not in response.text
    assert "THE-HUMAN-REFRESH-TOKEN-SECRET-VALUE" not in response.text
    assert response.json() == {"authenticated": True}


def test_login_redirect_carries_no_secret_beyond_state_nonce_challenge(client):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    # The redirect URL is inherently browser-visible (it's a 302 Location
    # header) — it must contain only the public OAuth parameters, never the
    # confidential client secret.
    assert "client_secret" not in location
    assert "emg_studio_bff_local_dev_secret" not in location


def test_callback_response_body_never_contains_token_content(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    from emg_studio_bff.session_store import PendingAuthorization

    session_store.create_pending_authorization(
        PendingAuthorization(
            state="sec-state", nonce="sec-nonce", code_verifier="v", created_at=time.time()
        )
    )
    id_token = issue_id_token(nonce="sec-nonce")
    access_token = issue_access_token()

    async def fake_exchange(*, settings, code, code_verifier):
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=access_token,
            refresh_token="a-refresh-token",
            id_token=id_token,
            expires_in=300,
        )

    patch_token_exchange(fake_exchange)

    response = client.get(
        "/auth/callback", params={"code": "sec-code", "state": "sec-state"}, follow_redirects=False
    )
    assert access_token not in response.text
    assert id_token not in response.text
    assert "a-refresh-token" not in response.text
    # The cookie value is an opaque session id, never the access/refresh/ID token itself.
    cookie_header = response.headers.get("set-cookie", "")
    assert access_token not in cookie_header
    assert id_token not in cookie_header
    assert "a-refresh-token" not in cookie_header


def test_default_response_headers_are_private_no_store(client, session_store):
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-sec")

    response = client.get("/auth/session")
    assert response.headers.get("cache-control") == "private, no-store"


def test_session_cookie_has_no_readable_javascript_surface(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    """HttpOnly is the control that keeps the cookie out of `document.cookie`
    / any browser JS — asserted directly on the Set-Cookie header, since
    TestClient has no JS engine to prove this against."""
    from emg_studio_bff.session_store import PendingAuthorization

    session_store.create_pending_authorization(
        PendingAuthorization(
            state="js-state", nonce="js-nonce", code_verifier="v", created_at=time.time()
        )
    )
    id_token = issue_id_token(nonce="js-nonce")
    access_token = issue_access_token()

    async def fake_exchange(*, settings, code, code_verifier):
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=access_token, refresh_token=None, id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)
    response = client.get(
        "/auth/callback", params={"code": "js-code", "state": "js-state"}, follow_redirects=False
    )
    assert "httponly" in response.headers["set-cookie"].lower()
