"""FastAPI dependency wiring: settings, Keycloak client, session manager,
audit sink, and the current-Principal extractor used by protected routes.

Uses the `Annotated[X, Depends(...)]` style (current FastAPI recommendation)
rather than `x: X = Depends(...)` default-argument style, which also avoids
flake8-bugbear's B008 (function-call-in-default-argument) lint warning.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from emg_auth_client import Principal
from emg_errors import AuthorizationError
from fastapi import Depends, Header

from .audit import AuditEventSink, StructuredLogAuditSink
from .auth_client import SessionAuthClient
from .config import Settings, get_settings
from .keycloak_client import KeycloakClient
from .session import SessionManager


@lru_cache
def _settings_singleton() -> Settings:
    return get_settings()


def settings_dependency() -> Settings:
    return _settings_singleton()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]


def keycloak_client_dependency(settings: SettingsDep) -> KeycloakClient:
    return KeycloakClient(settings)


def session_manager_dependency(settings: SettingsDep) -> SessionManager:
    return SessionManager(settings)


SessionManagerDep = Annotated[SessionManager, Depends(session_manager_dependency)]


def auth_client_dependency(session_manager: SessionManagerDep) -> SessionAuthClient:
    return SessionAuthClient(session_manager)


def audit_sink_dependency() -> AuditEventSink:
    return StructuredLogAuditSink()


AuthClientDep = Annotated[SessionAuthClient, Depends(auth_client_dependency)]


def get_current_principal(
    auth_client: AuthClientDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Extract and verify the Bearer token, returning the authenticated
    Principal. Raises AuthorizationError (mapped to HTTP 401 by main.py's
    exception handler) if the header is missing or the token is invalid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthorizationError("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    return auth_client.authenticate(token)
