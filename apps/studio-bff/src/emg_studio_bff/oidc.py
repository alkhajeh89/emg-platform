"""OIDC Authorization Code + PKCE S256 mechanics (ADR-035 D-1).

This is the ONE module that knows Keycloak's raw claim shape and OAuth wire
format. Everything downstream (`routers/auth.py`, `session_store.py`) works
only against `VerifiedHumanIdentity` / `TokenSet` below — mirroring the same
transport-boundary discipline `claim_adapter.py` established for the ADR-038
capability verification (Phase 3: "raw Keycloak JWT structure must not leak
into application services").

Threat coverage, each backed by a concrete mechanism, not a claim of intent:

- **CSRF / state mismatch**: `state` is a random, single-use, server-stored
  value; `callback()` rejects any `state` it did not itself issue and that
  has not already been consumed (`SessionStore.consume_pending_authorization`
  deletes on first read).
- **Nonce mismatch / ID-token substitution**: `nonce` is random and
  independently verified inside the signed ID token.
- **Authorization-code replay**: the pending-authorization record backing a
  given `state` is deleted on the FIRST callback attempt for it, success or
  failure — a second attempt with the same `state` (and therefore the same
  captured `code`) can never reach the token exchange at all.
- **PKCE downgrade/bypass**: `code_challenge_method` is hardcoded to `S256`
  (`generate_pkce_pair` never offers `plain`); Keycloak enforces the
  matching `code_verifier` at the token endpoint independently.
- **Open redirect**: there is no browser-supplied redirect target anywhere
  in this module — `oidc_redirect_uri` and `studio_frontend_url` are fixed,
  server-configured values (`config.py`).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx
import jwt

from .config import Settings

SigningKeyResolver = Callable[[str], object]


@dataclass(frozen=True, slots=True)
class PkcePair:
    code_verifier: str
    code_challenge: str


@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    id_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class VerifiedHumanIdentity:
    subject: str
    tenant_id: str
    classification_clearance: str
    roles: tuple[str, ...]
    access_token_expires_at: int


class OidcError(Exception):
    """Raised for any OIDC-flow failure — invalid state, invalid nonce,
    invalid code, PKCE failure, token verification failure. Callers map
    this to a single generic, fail-closed HTTP response; the specific
    reason is never echoed to the browser (mirrors production's existing
    'never leak internal identifiers' convention)."""


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> PkcePair:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(code_verifier=verifier, code_challenge=challenge)


def build_authorize_url(settings: Settings, *, state: str, nonce: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": settings.pkce_code_challenge_method,
    }
    return f"{settings.authorize_endpoint}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_tokens(
    settings: Settings, *, code: str, code_verifier: str
) -> TokenSet:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret.get_secret_value(),
                "redirect_uri": settings.oidc_redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            },
        )
    if response.status_code != 200:
        raise OidcError(f"token endpoint rejected the authorization code: {response.status_code}")
    body = response.json()
    if "id_token" not in body:
        raise OidcError("token response missing id_token")
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        id_token=body["id_token"],
        expires_in=int(body["expires_in"]),
    )


def _default_signing_key_resolver(settings: Settings) -> SigningKeyResolver:
    jwks_client = jwt.PyJWKClient(settings.jwks_uri, lifespan=settings.jwks_cache_ttl_seconds)
    return lambda token: jwks_client.get_signing_key_from_jwt(token).key


def verify_id_token(
    settings: Settings,
    id_token: str,
    *,
    expected_nonce: str,
    signing_key_resolver: SigningKeyResolver | None = None,
) -> None:
    """Verify signature, issuer, audience (this BFF's own client id), expiry,
    and nonce. Raises OidcError on any failure. Does not return claims — the
    ID token is used only to prove this exact browser round-trip is genuine;
    `verify_access_token` below is the source of truth for identity claims.

    `signing_key_resolver` mirrors the injectable-resolver pattern already
    established in `services/knowledge-graph/.../authn.py`'s
    `TenantServiceTokenValidator` — defaults to real JWKS resolution;
    tests inject a local key instead of requiring a live Keycloak."""
    resolver = signing_key_resolver or _default_signing_key_resolver(settings)
    try:
        signing_key = resolver(id_token)
        payload = jwt.decode(
            id_token,
            cast(Any, signing_key),
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer,
            audience=settings.oidc_client_id,
            options={"require": ["exp", "iat", "iss", "aud", "nonce"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"invalid ID token: {exc}") from exc
    if payload.get("nonce") != expected_nonce:
        raise OidcError("ID token nonce does not match the original request")


def verify_access_token(
    settings: Settings,
    access_token: str,
    *,
    signing_key_resolver: SigningKeyResolver | None = None,
) -> VerifiedHumanIdentity:
    """Verify signature/issuer/expiry and extract the claims this BFF's
    session record needs. `tenant_id` absent or invalid is a hard failure
    (ADR-035 D-11: 401, never a default tenant) — this BFF does not accept
    or forward a client-supplied tenant under any circumstance."""
    resolver = signing_key_resolver or _default_signing_key_resolver(settings)
    try:
        signing_key = resolver(access_token)
        payload = jwt.decode(
            access_token,
            cast(Any, signing_key),
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer,
            options={"require": ["exp", "iat", "iss", "sub", "azp"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"invalid access token: {exc}") from exc

    # Final correction-sprint Finding 3: CONFIRMED against a real
    # Authorization Code flow driven end-to-end against a fresh Keycloak 25
    # import of the canonical realm (not assumed) — the human access token
    # this client receives carries no `aud` claim at all for this client's
    # scope configuration, so a strict `audience=` check would reject every
    # legitimate token. `azp` ("authorized party") is confirmed present and
    # correct — the same claim this codebase already trusts elsewhere
    # (DelegatedCredentialValidator, TenantServiceTokenValidator) to prove
    # which client a token was actually issued to.
    if payload.get("azp") != settings.oidc_client_id:
        raise OidcError("access token was not issued to this BFF's own client")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise OidcError("access token missing sub")

    tenant_id = payload.get(settings.tenant_claim)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise OidcError(f"access token missing required '{settings.tenant_claim}' claim")

    # Same real-Keycloak verification (Finding 3) also found this: Keycloak
    # projects a multivalued user attribute as a single-element LIST
    # (`["INTERNAL"]`), not a bare string, exactly the shape
    # `services/identity/routers/auth.py::_extract_human_attributes` already
    # documents and unwraps for the same claim via the same mapper type.
    # Without unwrapping here, every real human's clearance silently
    # defaulted to UNCLASSIFIED regardless of their actual clearance.
    raw_clearance = payload.get(settings.classification_clearance_claim)
    if isinstance(raw_clearance, list) and raw_clearance:
        raw_clearance = raw_clearance[0]
    clearance = (
        raw_clearance if isinstance(raw_clearance, str) and raw_clearance else "UNCLASSIFIED"
    )

    realm_access = payload.get("realm_access")
    raw_roles = realm_access.get("roles", ()) if isinstance(realm_access, dict) else ()
    roles = tuple(str(r) for r in raw_roles) if isinstance(raw_roles, list) else ()

    return VerifiedHumanIdentity(
        subject=subject,
        tenant_id=tenant_id,
        classification_clearance=clearance,
        roles=roles,
        access_token_expires_at=int(payload["exp"]),
    )


async def refresh_tokens(settings: Settings, refresh_token: str) -> TokenSet:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret.get_secret_value(),
                "refresh_token": refresh_token,
            },
        )
    if response.status_code != 200:
        raise OidcError(f"token endpoint rejected the refresh token: {response.status_code}")
    body = response.json()
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", refresh_token),
        id_token=body.get("id_token", ""),
        expires_in=int(body["expires_in"]),
    )


async def revoke_refresh_token(settings: Settings, refresh_token: str) -> None:
    """RP-initiated logout (ADR-035 D-9: 'Logout revokes the server-side
    session AND the refresh token'). Best-effort against Keycloak's
    end-session endpoint; the server-side session is deleted by the caller
    (`routers/auth.py::logout`) regardless of this call's outcome — a
    revocation-endpoint failure must never leave the BROWSER's own session
    alive, even if the upstream IdP-side revocation itself is delayed."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            settings.end_session_endpoint,
            data={
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret.get_secret_value(),
                "refresh_token": refresh_token,
            },
        )
