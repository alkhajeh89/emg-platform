"""FastAPI dependency wiring for the Studio BFF."""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Annotated

from emg_errors import AuthorizationError
from fastapi import Depends, Request, Response

from . import oidc
from .config import Settings, get_settings
from .session_store import HumanSession, InMemorySessionStore, SessionStore, new_session_id


@lru_cache
def _settings_singleton() -> Settings:
    return get_settings()


def settings_dependency() -> Settings:
    return _settings_singleton()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]


@lru_cache
def _session_store_singleton() -> SessionStore:
    # Correction-sprint Finding 1: this app must never hold a direct
    # datastore connection (ADR-036 D-10.2 names Redis explicitly). The only
    # adapter for this batch is in-process — see session_store.py's module
    # docstring and docs/security/adr-038/07_PRODUCTION_CONFIGURATION.md.
    settings = _settings_singleton()
    return InMemorySessionStore(pre_auth_ttl_seconds=settings.pre_auth_ttl_seconds)


def session_store_dependency() -> SessionStore:
    return _session_store_singleton()


SessionStoreDep = Annotated[SessionStore, Depends(session_store_dependency)]


def set_session_cookie(
    response: Response, settings: Settings, session_id: str, max_age: int
) -> None:
    """Shared by `routers/auth.py::callback` (fresh login) and
    `current_session_dependency` below (transparent refresh) — a single
    place both write the session cookie, so the two paths cannot drift."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


async def current_session_dependency(
    request: Request,
    response: Response,
    settings: SettingsDep,
    session_store: SessionStoreDep,
) -> HumanSession:
    """Resolve the authenticated session from the opaque session cookie.

    Raises AuthorizationError (-> 401) if the cookie is absent or the
    session it names does not exist / has expired. The cookie's value is an
    opaque id only — it is never itself trusted as identity;
    `SessionStore.get_session` is the sole source of truth, and an absent
    lookup result is treated identically to an absent cookie. Read directly
    from `request.cookies` (rather than a FastAPI `Cookie(...)` parameter)
    because the cookie name is a `Settings` value, not a literal known at
    route-declaration time.

    **Correction-sprint Findings 4+5.** Two independent bounds, per ADR-035
    D-8 ("idle timeout and absolute lifetime both bounded"):

    - **Absolute lifetime**: once `created_at + session_absolute_ttl_seconds`
      passes, the session is deleted and rejected unconditionally — no
      refresh, however recent, extends it. This is the cap `oidc.py`'s
      previously-unused `refresh_tokens()` could otherwise extend forever.
    - **Idle/access-token expiry, now with transparent refresh**: when the
      underlying Keycloak access token is within `session_refresh_margin_seconds`
      of its own expiry and a refresh token is available, a server-side
      refresh is attempted (ADR-035 D-8: refresh occurs server-side; the
      browser never sees a token). The refreshed record is capped at the
      absolute lifetime even if the new access token's own expiry would
      exceed it. A refresh failure fails closed — the session is deleted and
      rejected (ADR-035 D-11: "Session expires mid-journey → Re-authenticate
      — never a silent scope downgrade"), never silently retried with the
      stale token.

    **Final correction-sprint Finding 2.** A refresh is no longer trusted
    blindly: `identity.subject`/`identity.tenant_id` from the refreshed
    token are compared against the session's own recorded values before
    anything is accepted. A refresh tied to one user's own `refresh_token`
    should never legitimately return a different subject or tenant — if it
    does, that is treated as a critical anomaly, not a normal privilege
    change: the session is deleted and the request fails closed (401),
    forcing re-authentication rather than silently continuing under a
    changed identity. A refresh that returns the SAME subject/tenant but a
    changed `classification_clearance` or `roles` (a legitimate IdP-side
    privilege change) is accepted, but the session is **rotated** — a fresh
    `session_id`, a fresh cookie, and the old id invalidated — rather than
    updated in place, so a still-cached old session id/cookie cannot be
    used to coast on stale privilege assumptions. Only when identity AND
    privilege are both unchanged does the session id stay the same
    (`SessionStore.replace_session` updates the stored tokens in place;
    only the cookie's `max_age` changes) — that is the sole case a fresh
    login is not required to rotate the id."""
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id is None:
        raise AuthorizationError("No session cookie presented")
    session = session_store.get_session(session_id)
    if session is None:
        raise AuthorizationError("Session is missing or has expired")

    now = time.time()
    absolute_deadline = session.created_at + settings.session_absolute_ttl_seconds
    if now >= absolute_deadline:
        session_store.delete_session(session_id)
        raise AuthorizationError("Session has reached its absolute lifetime")

    if (
        session.refresh_token is not None
        and session.access_token_expires_at - now <= settings.session_refresh_margin_seconds
    ):
        try:
            tokens = await oidc.refresh_tokens(settings, session.refresh_token)
            identity = oidc.verify_access_token(settings, tokens.access_token)
        except oidc.OidcError as exc:
            session_store.delete_session(session_id)
            raise AuthorizationError(f"Session refresh failed: {exc}") from exc

        if identity.subject != session.subject or identity.tenant_id != session.tenant_id:
            # Critical anomaly, not a normal privilege change — a refresh
            # tied to one user's own refresh_token should never legitimately
            # change WHO it represents. Fail closed rather than accept it.
            session_store.delete_session(session_id)
            raise AuthorizationError(
                "Session refresh returned a different subject or tenant than the "
                "originating session; refusing to continue"
            )

        capped_expires_at = min(float(identity.access_token_expires_at), absolute_deadline)
        privilege_changed = (
            identity.classification_clearance != session.classification_clearance
            or identity.roles != session.roles
        )
        next_session_id = new_session_id() if privilege_changed else session_id
        refreshed_session = HumanSession(
            session_id=next_session_id,
            subject=identity.subject,
            tenant_id=identity.tenant_id,
            classification_clearance=identity.classification_clearance,
            roles=identity.roles,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            access_token_expires_at=capped_expires_at,
            created_at=session.created_at,
            csrf_token=session.csrf_token,
        )
        if privilege_changed:
            session_store.delete_session(session_id)
            session_store.create_session(refreshed_session)
        else:
            session_store.replace_session(session_id, refreshed_session)
        set_session_cookie(
            response, settings, next_session_id, max(1, int(capped_expires_at - now))
        )
        session = refreshed_session

    return session


CurrentSessionDep = Annotated[HumanSession, Depends(current_session_dependency)]
