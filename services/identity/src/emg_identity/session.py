"""EMG session token issuance, verification, and refresh (FEAT-02-2).

Design decision (Sprint 2, documented per Engineering Master Plan §1: "Where
architecture leaves an implementation detail open, this backlog leaves it
open too — it is refined during sprint backlog grooming"): EMG mints its own
short-lived signed session token independent of Keycloak's own access token,
so that every downstream service depends on one EMG-governed session
contract (this module) rather than each service needing to understand
Keycloak's token format directly. The EMG session token carries the claims
Module 5's Policy Enforcement Point will require once implemented (US-02
acceptance criterion): subject, roles, and attributes — mirroring
`emg_auth_client.Principal` exactly so a PEP client can be built directly
against it in EPIC-03.

Tokens are stateless JWTs (HS256 for local development; Section "Config"
notes production must override the signing key via the centralized secrets
store). Refresh tokens are rotated on every use. Because there is no
persistent store yet (Module 6 audit/session storage lands EPIC-04), a
refresh token cannot be actively revoked before its natural expiry — this is
a known limitation, documented in services/identity/README.md, acceptable
for Sprint 2 given the short refresh TTL (12h default) and out-of-scope
status of session revocation in FEAT-02-2's stated acceptance criteria.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from emg_auth_client import Principal
from emg_common_types import normalize_classification_clearance
from emg_errors import AuthorizationError

from .config import Settings
from .refresh_tokens import InMemoryRefreshTokenStore, RefreshTokenStore

TokenType = Literal["access", "refresh"]


def _normalize_human_attributes(attributes: dict[str, str]) -> dict[str, str]:
    """Ensure a human Principal's `classification_clearance` attribute is
    always present and resolvable to a real value — never absent, blank, or
    a non-string leftover.

    **Group D Phase 1 Remediation (Legacy Session Normalization):** the
    original human-provisioning fix (routers/auth.py's login flow) only
    guaranteed this for a *freshly minted* session, built from a
    just-verified Keycloak access token. It did not cover an EMG session
    token minted *before* that fix existed: such a token's own
    `attributes` claim was persisted as `{}` (or without
    `classification_clearance` at all) at issuance time, and
    `SessionManager.verify()`/`SessionAuthClient.authenticate()` previously
    passed that stored value straight through unchanged, forever — a
    caller who logged in before this remediation and simply keeps refreshing
    their session would never receive a `classification_clearance` value,
    silently defeating the fail-closed guarantee (`PolicyRule` matching has
    no "attribute absent" special case, so an absent/blank/malformed value
    satisfies neither an allow rule requiring a specific clearance nor a
    deny rule keyed on the literal `"UNCLASSIFIED"` string).

    This is the single point both the login flow (`routers/auth.py`) and
    every session-reconstruction path (`SessionManager.verify()`, and
    therefore also `SessionManager.refresh()` and
    `SessionAuthClient.authenticate()`, both of which call `verify()`) share,
    so a legacy session is normalized -- and, once refreshed, re-minted with
    the normalized value going forward -- identically to how a brand-new
    login is. Applying this once, here, rather than separately at each of
    the several `Principal(...)` construction call sites, is what "avoid
    duplicate logic" (Legacy Session Normalization scope) means in practice.

    A value counts as valid only if it is a `str` with at least one
    non-whitespace character AND matches a recognized `Classification` enum
    member; missing, empty, whitespace-only, non-string, or unrecognized
    values (e.g. `"banana"`, `"SUPER_SECRET"`) are all replaced with the
    literal `"UNCLASSIFIED"` (ADR-026 final blocker fix, closing the gap
    where an unrecognized clearance string previously survived normalization
    unchanged and satisfied none of `PolicyRule`'s per-classification deny
    rules). This validation is delegated to
    `emg_common_types.normalize_classification_clearance` — the single
    shared helper every `classification_clearance` normalization boundary in
    the platform calls, rather than each boundary re-implementing the check.
    Every other attribute (e.g. `department`) passes through completely
    unchanged -- this function has no opinion on, and does not touch, any
    key besides `classification_clearance`.
    """
    raw_clearance = attributes.get("classification_clearance")
    clearance = normalize_classification_clearance(raw_clearance)
    normalized = dict(attributes)
    normalized["classification_clearance"] = clearance
    return normalized


@dataclass(frozen=True)
class SessionClaims:
    """Decoded, verified claims from an EMG session token."""

    subject: str
    roles: tuple[str, ...]
    attributes: dict[str, str]
    token_type: TokenType
    jti: str
    family_id: str | None
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class SessionTokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_in: int


class SessionManager:
    """Mints and verifies EMG session tokens for a given Settings instance."""

    def __init__(
        self,
        settings: Settings,
        refresh_tokens: RefreshTokenStore | None = None,
    ) -> None:
        self._settings = settings
        self._refresh_tokens = refresh_tokens or InMemoryRefreshTokenStore()

    def issue(self, principal: Principal) -> SessionTokenPair:
        """Mint a fresh access/refresh token pair for an authenticated
        Principal (called immediately after a successful Keycloak login)."""
        family_id = str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())
        refresh_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._settings.refresh_token_ttl_seconds
        )
        self._refresh_tokens.register(family_id, refresh_jti, refresh_expires_at)
        return self._issue_pair(
            principal,
            family_id=family_id,
            refresh_jti=refresh_jti,
        )

    def _issue_pair(
        self,
        principal: Principal,
        *,
        family_id: str,
        refresh_jti: str,
    ) -> SessionTokenPair:
        access_token = self._mint(
            principal,
            "access",
            self._settings.access_token_ttl_seconds,
            family_id=family_id,
        )
        refresh_token = self._mint(
            principal,
            "refresh",
            self._settings.refresh_token_ttl_seconds,
            family_id=family_id,
            jti=refresh_jti,
        )
        return SessionTokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=self._settings.access_token_ttl_seconds,
            refresh_expires_in=self._settings.refresh_token_ttl_seconds,
        )

    def refresh(self, refresh_token: str) -> SessionTokenPair:
        """Verify a refresh token and mint a new, rotated token pair.

        Raises AuthorizationError if the refresh token is invalid, expired,
        or not of type "refresh" (e.g. an access token was presented here).
        """
        claims = self.verify(refresh_token, expected_type="refresh")
        if claims.family_id is None:
            raise AuthorizationError("Legacy refresh tokens must authenticate again")
        next_jti = str(uuid.uuid4())
        next_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._settings.refresh_token_ttl_seconds
        )
        if not self._refresh_tokens.rotate(
            claims.family_id,
            claims.jti,
            next_jti,
            next_expires_at,
        ):
            raise AuthorizationError("Refresh token reuse detected; session revoked")
        principal = Principal(
            subject=claims.subject, roles=claims.roles, attributes=claims.attributes
        )
        return self._issue_pair(
            principal,
            family_id=claims.family_id,
            refresh_jti=next_jti,
        )

    def verify(self, token: str, *, expected_type: TokenType) -> SessionClaims:
        """Verify signature, expiry, issuer, and audience; raises
        AuthorizationError on any failure (never leaks the underlying JWT
        library exception to callers, keeping error handling uniform with
        the rest of the platform's emg_errors hierarchy)."""
        try:
            payload = jwt.decode(
                token,
                self._settings.session_signing_key,
                algorithms=[self._settings.session_signing_algorithm],
                issuer=self._settings.token_issuer,
                audience=self._settings.token_audience,
            )
        except jwt.PyJWTError as exc:
            raise AuthorizationError(f"Invalid or expired session token: {exc}") from exc

        if payload.get("token_type") != expected_type:
            raise AuthorizationError(
                f"Expected a '{expected_type}' token, got '{payload.get('token_type')}'"
            )

        family_id = payload.get("family_id")
        if family_id is not None and not isinstance(family_id, str):
            raise AuthorizationError("Session token has an invalid token family")
        if (
            expected_type == "access"
            and family_id is not None
            and not self._refresh_tokens.family_is_active(family_id)
        ):
            raise AuthorizationError("Session token family has been revoked")

        return SessionClaims(
            subject=payload["sub"],
            roles=tuple(payload.get("roles", ())),
            attributes=_normalize_human_attributes(dict(payload.get("attributes", {}))),
            token_type=payload["token_type"],
            jti=payload["jti"],
            family_id=family_id,
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )

    def _mint(
        self,
        principal: Principal,
        token_type: TokenType,
        ttl_seconds: int,
        *,
        family_id: str,
        jti: str | None = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": principal.subject,
            "roles": list(principal.roles),
            "attributes": dict(principal.attributes),
            "token_type": token_type,
            "jti": jti or str(uuid.uuid4()),
            "family_id": family_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
            "iss": self._settings.token_issuer,
            "aud": self._settings.token_audience,
        }
        return jwt.encode(
            payload,
            self._settings.session_signing_key,
            algorithm=self._settings.session_signing_algorithm,
        )
