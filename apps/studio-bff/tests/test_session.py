"""AUTHENTICATION test category (continued): expired session, logout /
session invalidation, session rotation after login."""

from __future__ import annotations

import time

from emg_studio_bff.session_store import HumanSession

CSRF_TOKEN = "csrf-token-value"


def _seed_session(
    session_store,
    *,
    session_id="sess-1",
    access_token_expires_at=None,
    created_at=None,
    refresh_token="refresh-token-value",
) -> HumanSession:
    session = HumanSession(
        session_id=session_id,
        subject="human-a",
        tenant_id="tenant-a",
        classification_clearance="CONFIDENTIAL",
        roles=("investigator",),
        access_token="access-token-value",
        refresh_token=refresh_token,
        access_token_expires_at=access_token_expires_at or (time.time() + 300),
        created_at=created_at if created_at is not None else time.time(),
        csrf_token=CSRF_TOKEN,
    )
    session_store.create_session(session)
    return session


def test_expired_session_is_rejected(client, session_store):
    _seed_session(
        session_store, session_id="expired-sess", access_token_expires_at=time.time() - 10
    )
    client.cookies.set("__Host-emg_studio_session", "expired-sess")

    response = client.get("/auth/session")
    assert response.status_code == 401


def test_valid_session_reports_authenticated(client, session_store):
    _seed_session(session_store, session_id="valid-sess")
    client.cookies.set("__Host-emg_studio_session", "valid-sess")

    response = client.get("/auth/session")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}


def test_missing_session_cookie_is_rejected(client):
    response = client.get("/auth/session")
    assert response.status_code == 401


def test_logout_deletes_session_and_clears_cookie(client, session_store, monkeypatch):
    _seed_session(session_store, session_id="logout-sess")
    client.cookies.set("__Host-emg_studio_session", "logout-sess")

    async def fake_revoke(settings, refresh_token):
        assert refresh_token == "refresh-token-value"

    monkeypatch.setattr("emg_studio_bff.routers.auth.oidc.revoke_refresh_token", fake_revoke)

    response = client.post("/auth/logout", headers={"X-CSRF-Token": CSRF_TOKEN})
    assert response.status_code == 204
    cookie_header = response.headers.get("set-cookie", "")
    assert 'emg_studio_session=""' in cookie_header or "Max-Age=0" in cookie_header

    assert session_store.get_session("logout-sess") is None


def test_logout_revocation_failure_is_logged_but_still_returns_204(
    client, session_store, monkeypatch, caplog
):
    """Final correction-sprint Finding 8: revocation failure is no longer
    completely silent — logged at WARNING — but the response and session
    deletion behavior are unchanged (already ADR-035 D-9 compliant)."""
    _seed_session(session_store, session_id="revoke-fail-sess")
    client.cookies.set("__Host-emg_studio_session", "revoke-fail-sess")

    async def failing_revoke(settings, refresh_token):
        raise RuntimeError("simulated Keycloak revocation-endpoint outage")

    monkeypatch.setattr("emg_studio_bff.routers.auth.oidc.revoke_refresh_token", failing_revoke)

    import logging

    with caplog.at_level(logging.WARNING, logger="emg.studio-bff.auth"):
        response = client.post("/auth/logout", headers={"X-CSRF-Token": CSRF_TOKEN})

    assert response.status_code == 204
    assert session_store.get_session("revoke-fail-sess") is None
    assert any("revocation failed" in record.message for record in caplog.records)


def test_session_after_logout_no_longer_authenticates(client, session_store, monkeypatch):
    _seed_session(session_store, session_id="logout-sess-2")
    client.cookies.set("__Host-emg_studio_session", "logout-sess-2")

    async def fake_revoke(settings, refresh_token):
        return None

    monkeypatch.setattr("emg_studio_bff.routers.auth.oidc.revoke_refresh_token", fake_revoke)
    client.post("/auth/logout", headers={"X-CSRF-Token": CSRF_TOKEN})

    response = client.get("/auth/session")
    assert response.status_code == 401


def test_logout_without_csrf_header_is_rejected(client, session_store):
    """Correction-sprint Finding 3 (ADR-035 D-10: 'SameSite alone is not
    sufficient'): a state-changing POST /auth/logout with no CSRF header at
    all must be rejected before any session state changes."""
    _seed_session(session_store, session_id="csrf-sess-1")
    client.cookies.set("__Host-emg_studio_session", "csrf-sess-1")

    response = client.post("/auth/logout")
    assert response.status_code == 401
    assert session_store.get_session("csrf-sess-1") is not None


def test_logout_with_wrong_csrf_header_is_rejected(client, session_store):
    _seed_session(session_store, session_id="csrf-sess-2")
    client.cookies.set("__Host-emg_studio_session", "csrf-sess-2")

    response = client.post("/auth/logout", headers={"X-CSRF-Token": "attacker-guessed-value"})
    assert response.status_code == 401
    assert session_store.get_session("csrf-sess-2") is not None


def test_logout_with_correct_csrf_header_succeeds(client, session_store):
    _seed_session(session_store, session_id="csrf-sess-3", refresh_token=None)
    client.cookies.set("__Host-emg_studio_session", "csrf-sess-3")

    response = client.post("/auth/logout", headers={"X-CSRF-Token": CSRF_TOKEN})
    assert response.status_code == 204
    assert session_store.get_session("csrf-sess-3") is None


def test_session_rejected_once_absolute_lifetime_reached(client, session_store):
    """Correction-sprint Finding 4: the absolute cap rejects a session even
    though its access token has not itself expired — a distinct bound from
    idle/access-token expiry."""
    _seed_session(
        session_store,
        session_id="absolute-sess",
        access_token_expires_at=time.time() + 300,  # access token still "valid"
        created_at=time.time() - 3600 - 1,  # but older than session_absolute_ttl_seconds (3600)
    )
    client.cookies.set("__Host-emg_studio_session", "absolute-sess")

    response = client.get("/auth/session")
    assert response.status_code == 401
    assert session_store.get_session("absolute-sess") is None


def test_session_refreshed_transparently_near_expiry(
    client, session_store, monkeypatch, issue_access_token
):
    """Correction-sprint Finding 5: `oidc.refresh_tokens` — previously dead
    code — is now actually called, and the session/cookie are updated with
    the refreshed token, when access-token expiry is within
    `session_refresh_margin_seconds`."""
    _seed_session(
        session_store,
        session_id="refresh-sess",
        access_token_expires_at=time.time() + 10,  # within the 60s refresh margin
        created_at=time.time() - 10,  # well within the absolute cap
    )
    client.cookies.set("__Host-emg_studio_session", "refresh-sess")

    # Same subject/tenant/clearance/roles as the seeded session (_seed_session's
    # defaults) — no privilege change, so Finding 2's rotation must NOT trigger.
    new_access_token = issue_access_token(
        sub="human-a", tenant_id="tenant-a", clearance="CONFIDENTIAL", roles=("investigator",)
    )
    calls = {"n": 0}

    async def fake_refresh(settings, refresh_token):
        calls["n"] += 1
        assert refresh_token == "refresh-token-value"
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=new_access_token,
            refresh_token="new-refresh-token",
            id_token="",
            expires_in=300,
        )

    monkeypatch.setattr("emg_studio_bff.dependencies.oidc.refresh_tokens", fake_refresh)

    response = client.get("/auth/session")
    assert response.status_code == 200
    assert calls["n"] == 1

    refreshed = session_store.get_session("refresh-sess")
    assert refreshed is not None
    assert refreshed.access_token == new_access_token
    assert refreshed.refresh_token == "new-refresh-token"
    assert refreshed.session_id == "refresh-sess"  # never rotated by a refresh


def test_session_refresh_failure_fails_closed(client, session_store, monkeypatch):
    """ADR-035 D-11: 'Session expires mid-journey -> Re-authenticate — never
    a silent scope downgrade.' A refresh failure must delete the session and
    reject, never silently continue on the stale token."""
    _seed_session(
        session_store,
        session_id="refresh-fail-sess",
        access_token_expires_at=time.time() + 10,
        created_at=time.time() - 10,
    )
    client.cookies.set("__Host-emg_studio_session", "refresh-fail-sess")

    async def failing_refresh(settings, refresh_token):
        from emg_studio_bff import oidc as oidc_module

        raise oidc_module.OidcError("token endpoint rejected the refresh token: 400")

    monkeypatch.setattr("emg_studio_bff.dependencies.oidc.refresh_tokens", failing_refresh)

    response = client.get("/auth/session")
    assert response.status_code == 401
    assert session_store.get_session("refresh-fail-sess") is None


def test_refresh_returning_different_subject_fails_closed(
    client, session_store, monkeypatch, issue_access_token
):
    """Final correction-sprint Finding 2: a refresh must never silently
    accept a different subject than the originating session — treated as a
    critical anomaly, not a privilege change."""
    _seed_session(
        session_store,
        session_id="subj-mismatch-sess",
        access_token_expires_at=time.time() + 10,
        created_at=time.time() - 10,
    )
    client.cookies.set("__Host-emg_studio_session", "subj-mismatch-sess")

    different_subject_token = issue_access_token(sub="human-b", tenant_id="tenant-a")

    async def fake_refresh(settings, refresh_token):
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=different_subject_token,
            refresh_token="new-refresh-token",
            id_token="",
            expires_in=300,
        )

    monkeypatch.setattr("emg_studio_bff.dependencies.oidc.refresh_tokens", fake_refresh)

    response = client.get("/auth/session")
    assert response.status_code == 401
    assert session_store.get_session("subj-mismatch-sess") is None


def test_refresh_returning_different_tenant_fails_closed(
    client, session_store, monkeypatch, issue_access_token
):
    """Same class of anomaly as subject mismatch, for tenant_id."""
    _seed_session(
        session_store,
        session_id="tenant-mismatch-sess",
        access_token_expires_at=time.time() + 10,
        created_at=time.time() - 10,
    )
    client.cookies.set("__Host-emg_studio_session", "tenant-mismatch-sess")

    different_tenant_token = issue_access_token(sub="human-a", tenant_id="tenant-b")

    async def fake_refresh(settings, refresh_token):
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=different_tenant_token,
            refresh_token="new-refresh-token",
            id_token="",
            expires_in=300,
        )

    monkeypatch.setattr("emg_studio_bff.dependencies.oidc.refresh_tokens", fake_refresh)

    response = client.get("/auth/session")
    assert response.status_code == 401
    assert session_store.get_session("tenant-mismatch-sess") is None


def test_refresh_with_changed_clearance_rotates_session(
    client, session_store, monkeypatch, issue_access_token
):
    """Final correction-sprint Finding 2: a legitimate IdP-side privilege
    change (clearance increased) is accepted, but the session is ROTATED
    (new id, new cookie) rather than updated in place under the old id."""
    _seed_session(
        session_store,
        session_id="clearance-change-sess",
        access_token_expires_at=time.time() + 10,
        created_at=time.time() - 10,
    )
    client.cookies.set("__Host-emg_studio_session", "clearance-change-sess")

    elevated_token = issue_access_token(
        sub="human-a", tenant_id="tenant-a", clearance="SECRET", roles=("investigator",)
    )

    async def fake_refresh(settings, refresh_token):
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=elevated_token,
            refresh_token="new-refresh-token",
            id_token="",
            expires_in=300,
        )

    monkeypatch.setattr("emg_studio_bff.dependencies.oidc.refresh_tokens", fake_refresh)

    response = client.get("/auth/session")
    assert response.status_code == 200

    # Old session id is gone — cannot be used to coast on stale privilege.
    assert session_store.get_session("clearance-change-sess") is None

    new_cookie = response.headers["set-cookie"]
    assert "clearance-change-sess" not in new_cookie

    # A session now exists under the NEW id, reflecting the new clearance.
    # Extract the new session id from the Set-Cookie header.
    import re

    match = re.search(r"__Host-emg_studio_session=([0-9a-f]+)", new_cookie)
    assert match is not None
    new_session = session_store.get_session(match.group(1))
    assert new_session is not None
    assert new_session.classification_clearance == "SECRET"


def test_refresh_with_changed_roles_rotates_session(
    client, session_store, monkeypatch, issue_access_token
):
    """Same rotation behaviour, triggered by a roles change instead of a
    clearance change."""
    _seed_session(
        session_store,
        session_id="roles-change-sess",
        access_token_expires_at=time.time() + 10,
        created_at=time.time() - 10,
    )
    client.cookies.set("__Host-emg_studio_session", "roles-change-sess")

    promoted_token = issue_access_token(
        sub="human-a",
        tenant_id="tenant-a",
        clearance="CONFIDENTIAL",
        roles=("investigator", "decision-maker"),
    )

    async def fake_refresh(settings, refresh_token):
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=promoted_token,
            refresh_token="new-refresh-token",
            id_token="",
            expires_in=300,
        )

    monkeypatch.setattr("emg_studio_bff.dependencies.oidc.refresh_tokens", fake_refresh)

    response = client.get("/auth/session")
    assert response.status_code == 200
    assert session_store.get_session("roles-change-sess") is None
    assert "roles-change-sess" not in response.headers["set-cookie"]


def test_stale_pending_authorization_cannot_be_consumed(session_store, settings):
    """Final correction-sprint Finding 1: an unconsumed PendingAuthorization
    older than pre_auth_ttl_seconds is rejected, not accepted indefinitely."""
    from emg_studio_bff.session_store import PendingAuthorization

    stale = PendingAuthorization(
        state="stale-state",
        nonce="stale-nonce",
        code_verifier="v",
        created_at=time.time() - settings.pre_auth_ttl_seconds - 5,
    )
    session_store.create_pending_authorization(stale)

    assert session_store.consume_pending_authorization("stale-state") is None


def test_pending_authorization_store_does_not_grow_unboundedly(session_store, settings):
    """An abandoned login flow (state created, callback never completed)
    must not accumulate forever — active eviction on subsequent writes."""
    from emg_studio_bff.session_store import PendingAuthorization

    old_cutoff = time.time() - settings.pre_auth_ttl_seconds - 5
    for i in range(50):
        session_store.create_pending_authorization(
            PendingAuthorization(
                state=f"abandoned-{i}", nonce="n", code_verifier="v", created_at=old_cutoff
            )
        )
    # A single fresh write triggers the active sweep — none of the 50
    # abandoned, expired records should survive it.
    session_store.create_pending_authorization(
        PendingAuthorization(state="fresh", nonce="n", code_verifier="v", created_at=time.time())
    )

    assert len(session_store._pending) == 1  # type: ignore[attr-defined]
    assert session_store.consume_pending_authorization("abandoned-0") is None
    assert session_store.consume_pending_authorization("fresh") is not None


def test_session_store_does_not_grow_unboundedly(session_store):
    """An abandoned session (created, never re-queried) is actively evicted
    on a subsequent write, not retained forever."""
    for i in range(50):
        session_store.create_session(
            HumanSession(
                session_id=f"abandoned-sess-{i}",
                subject="human-a",
                tenant_id="tenant-a",
                classification_clearance="CONFIDENTIAL",
                roles=("investigator",),
                access_token="tok",
                refresh_token=None,
                access_token_expires_at=time.time() - 100,  # already expired
                created_at=time.time() - 200,
                csrf_token=CSRF_TOKEN,
            )
        )
    session_store.create_session(
        HumanSession(
            session_id="fresh-sess",
            subject="human-a",
            tenant_id="tenant-a",
            classification_clearance="CONFIDENTIAL",
            roles=("investigator",),
            access_token="tok",
            refresh_token=None,
            access_token_expires_at=time.time() + 300,
            created_at=time.time(),
            csrf_token=CSRF_TOKEN,
        )
    )

    assert len(session_store._sessions) == 1  # type: ignore[attr-defined]
    assert session_store.get_session("fresh-sess") is not None


def test_login_rotates_session_never_extends_a_stale_one(
    client, session_store, patch_token_exchange, issue_id_token, issue_access_token
):
    """A pre-existing (e.g. stale/compromised) session cookie present at
    login time is discarded server-side, not extended or reused, by the new
    login."""
    from emg_studio_bff.session_store import PendingAuthorization

    stale = _seed_session(session_store, session_id="stale-sess")
    client.cookies.set("__Host-emg_studio_session", "stale-sess")

    session_store.create_pending_authorization(
        PendingAuthorization(
            state="rotate-state", nonce="rotate-nonce", code_verifier="v", created_at=time.time()
        )
    )
    id_token = issue_id_token(nonce="rotate-nonce", sub="human-b")
    access_token = issue_access_token(sub="human-b", tenant_id="tenant-b", clearance="INTERNAL")

    async def fake_exchange(*, settings, code, code_verifier):
        import emg_studio_bff.oidc as oidc_module

        return oidc_module.TokenSet(
            access_token=access_token, refresh_token=None, id_token=id_token, expires_in=300
        )

    patch_token_exchange(fake_exchange)

    response = client.get(
        "/auth/callback",
        params={"code": "rotate-code", "state": "rotate-state"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    # The OLD session id must be gone (rotated away), and the new cookie
    # value must differ from the stale one.
    assert session_store.get_session(stale.session_id) is None
    new_cookie = response.headers["set-cookie"]
    assert "stale-sess" not in new_cookie
