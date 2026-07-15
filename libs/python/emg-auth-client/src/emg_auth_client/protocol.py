"""AuthClient interface every service programs against.

A concrete implementation (backed by Module 4's Keycloak integration and
Module 5's Policy Enforcement Point) is delivered in EPIC-02 (FEAT-02-1
Identity Provider Integration) and EPIC-03 (FEAT-03-1 Policy Enforcement
Point). Until then this Protocol exists so downstream service scaffolding
(TASK generators, FastAPI dependency wiring, etc.) can type against a stable
contract without a circular dependency on the identity service itself.
"""

from __future__ import annotations

from typing import Protocol

from .principal import Principal


class AuthClient(Protocol):
    def authenticate(self, token: str) -> Principal:
        """Validate a bearer token and return the authenticated Principal.

        Raises emg_errors.AuthorizationError on an invalid/expired token.
        Implemented in EPIC-02.
        """
        ...

    def current_principal(self) -> Principal | None:
        """Return the Principal bound to the current request context, if any."""
        ...
