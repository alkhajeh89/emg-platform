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
from emg_errors import AuthorizationError

from .config import Settings

TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class SessionClaims:
    """Decoded, verified claims from an EMG session token."""

    subject: str
    roles: tuple[str, ...]
    attributes: dict[str, str]
    token_type: TokenType
    jti: str
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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def issue(self, principal: Principal) -> SessionTokenPair:
        """Mint a fresh access/refresh token pair for an authenticated
        Principal (called immediately after a successful Keycloak login)."""
        access_token = self._mint(principal, "access", self._settings.access_token_ttl_seconds)
        refresh_token = self._mint(principal, "refresh", self._settings.refresh_token_ttl_seconds)
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
        principal = Principal(
            subject=claims.subject, roles=claims.roles, attributes=claims.attributes
        )
        return self.issue(principal)

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

        return SessionClaims(
            subject=payload["sub"],
            roles=tuple(payload.get("roles", ())),
            attributes=dict(payload.get("attributes", {})),
            token_type=payload["token_type"],
            jti=payload["jti"],
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )

    def _mint(self, principal: Principal, token_type: TokenType, ttl_seconds: int) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": principal.subject,
            "roles": list(principal.roles),
            "attributes": dict(principal.attributes),
            "token_type": token_type,
            "jti": str(uuid.uuid4()),
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
