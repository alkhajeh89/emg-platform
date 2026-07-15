"""Concrete AuthClient implementation against emg_auth_client's Protocol.

libs/python/emg-auth-client (Sprint 1, FEAT-01-2) deliberately shipped only
an interface: "A concrete implementation ... is delivered in EPIC-02
(FEAT-02-1 ... FEAT-03-1)." This module is that concrete implementation for
the identity side (session-token verification); Module 5's Policy
Enforcement Point (FEAT-03-1, EPIC-03) will additionally consume the
`roles`/`attributes` this produces for ABAC evaluation.
"""

from __future__ import annotations

from contextvars import ContextVar

from emg_auth_client import Principal

from .session import SessionManager

_current_principal: ContextVar[Principal | None] = ContextVar("emg_current_principal", default=None)


class SessionAuthClient:
    """AuthClient (per emg_auth_client.AuthClient Protocol) backed by EMG
    session tokens (session.py)."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager

    def authenticate(self, token: str) -> Principal:
        """Validate an EMG access token and return the authenticated
        Principal. Raises emg_errors.AuthorizationError on an invalid or
        expired token (via SessionManager.verify)."""
        claims = self._session_manager.verify(token, expected_type="access")
        principal = Principal(
            subject=claims.subject, roles=claims.roles, attributes=claims.attributes
        )
        _current_principal.set(principal)
        return principal

    def current_principal(self) -> Principal | None:
        return _current_principal.get()
