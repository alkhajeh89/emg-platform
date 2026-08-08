"""Login / callback / logout / session-presence endpoints (ADR-035).

Every route here upholds ADR-035 D-8/D-9/D-10/D-11 directly:
- the browser receives ONLY the opaque session cookie (plus a non-HttpOnly
  CSRF cookie — an unguessable token, never identity-bearing) — never an
  access, refresh, or ID token, in any response body or Set-Cookie value;
- the cookie is `__Host-` prefixed, `HttpOnly`, `Secure`, `SameSite=Lax`,
  with a bounded lifetime, and is rotated (a fresh id, never reused or
  extended) on every successful login;
- CSRF is covered by the OAuth `state` parameter (single-use, server-side
  only — see oidc.py's module docstring) for `/auth/callback`. For the
  state-changing `POST /auth/logout`, **correction-sprint Finding 3**: a
  double-submit CSRF token is additionally required — ADR-035 D-10 is
  explicit that "SameSite alone is not sufficient," so relying on SameSite
  alone (this route's own prior implementation) was a direct, confirmed gap
  against that clause, not a stylistic choice.
"""

from __future__ import annotations

import secrets
import time
from typing import Annotated

from emg_errors import AuthorizationError
from emg_telemetry import get_logger
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from .. import oidc
from ..config import Settings
from ..dependencies import CurrentSessionDep, SessionStoreDep, SettingsDep, set_session_cookie
from ..session_store import HumanSession, PendingAuthorization, new_session_id

router = APIRouter(prefix="/auth", tags=["auth"])
_log = get_logger("studio-bff.auth")


def _set_csrf_cookie(response: Response, settings: Settings, csrf_token: str, max_age: int) -> None:
    # Deliberately NOT httponly: the double-submit pattern requires
    # client-side JS to read this value and echo it back as a header: an
    # attacker's cross-site form/fetch can attach the browser's cookies
    # automatically but cannot read this cookie's value to also set the
    # matching header, which is exactly what defeats the forgery.
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=max_age,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    response.delete_cookie(key=settings.csrf_cookie_name, path="/")


@router.get("/login")
async def login(settings: SettingsDep, session_store: SessionStoreDep) -> RedirectResponse:
    state = oidc.generate_state()
    nonce = oidc.generate_nonce()
    pkce = oidc.generate_pkce_pair()
    session_store.create_pending_authorization(
        PendingAuthorization(
            state=state, nonce=nonce, code_verifier=pkce.code_verifier, created_at=time.time()
        )
    )
    url = oidc.build_authorize_url(
        settings, state=state, nonce=nonce, code_challenge=pkce.code_challenge
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    settings: SettingsDep,
    session_store: SessionStoreDep,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    if error is not None or code is None or state is None:
        raise AuthorizationError(
            "Authorization callback missing code/state or IdP returned an error"
        )

    # Single-use: deleted on first read regardless of what happens next —
    # a second callback attempt with this same state can never succeed.
    pending = session_store.consume_pending_authorization(state)
    if pending is None:
        raise AuthorizationError("Invalid or already-used state")

    try:
        tokens = await oidc.exchange_code_for_tokens(
            settings, code=code, code_verifier=pending.code_verifier
        )
        oidc.verify_id_token(settings, tokens.id_token, expected_nonce=pending.nonce)
        identity = oidc.verify_access_token(settings, tokens.access_token)
    except oidc.OidcError as exc:
        raise AuthorizationError(str(exc)) from exc

    # Session rotation: if a (possibly stale) session cookie is already
    # present, its server-side record is discarded — a fresh login never
    # extends a prior session, it replaces it.
    stale_session_id = request.cookies.get(settings.session_cookie_name)
    if stale_session_id is not None:
        session_store.delete_session(stale_session_id)

    session_id = new_session_id()
    csrf_token = secrets.token_urlsafe(32)
    session_store.create_session(
        HumanSession(
            session_id=session_id,
            subject=identity.subject,
            tenant_id=identity.tenant_id,
            classification_clearance=identity.classification_clearance,
            roles=identity.roles,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            access_token_expires_at=float(identity.access_token_expires_at),
            created_at=time.time(),
            csrf_token=csrf_token,
        )
    )

    response = RedirectResponse(url=settings.studio_frontend_url, status_code=302)
    max_age = max(1, identity.access_token_expires_at - int(time.time()))
    set_session_cookie(response, settings, session_id, max_age)
    _set_csrf_cookie(response, settings, csrf_token, max_age)
    return response


@router.post("/logout")
async def logout(
    request: Request, settings: SettingsDep, session_store: SessionStoreDep
) -> Response:
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id is not None:
        session = session_store.get_session(session_id)
        if session is not None:
            # Correction-sprint Finding 3: double-submit CSRF check.
            # SameSite=Lax alone is explicitly insufficient per ADR-035
            # D-10 — a mismatched or missing header is rejected before any
            # state changes (session deletion, revocation) happen.
            presented = request.headers.get("x-csrf-token")
            if presented is None or not secrets.compare_digest(presented, session.csrf_token):
                raise AuthorizationError("Missing or invalid CSRF token")
        session_store.delete_session(session_id)
        if session is not None and session.refresh_token:
            # Best-effort — the server-side session above is already gone
            # regardless of whether Keycloak's own revocation succeeds
            # (ADR-035 D-9 is satisfied either way). Final correction-sprint
            # Finding 8: a failure is no longer completely silent — logged
            # at WARNING so an operator has visibility into a failing
            # upstream revocation, without changing this fail-open-on-
            # revoke/fail-closed-on-session-delete behavior itself.
            try:
                await oidc.revoke_refresh_token(settings, session.refresh_token)
            except Exception:
                _log.warning(
                    "refresh token revocation failed for subject=%s; server-side session "
                    "already deleted",
                    session.subject,
                    exc_info=True,
                )

    response = Response(status_code=204)
    _clear_session_cookie(response, settings)
    return response


@router.get("/session")
async def session_info(_session: CurrentSessionDep) -> dict[str, bool]:
    """Presence-check only — the session is authenticated or this raises
    (401) before returning. Never returns subject, tenant, clearance, or
    any token content — the browser learns nothing beyond 'yes/no'."""
    return {"authenticated": True}
