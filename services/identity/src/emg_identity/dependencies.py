"""FastAPI dependency wiring: settings, Keycloak client, session manager,
audit sink, and the current-Principal extractor used by protected routes.

Uses the `Annotated[X, Depends(...)]` style (current FastAPI recommendation)
rather than `x: X = Depends(...)` default-argument style, which also avoids
flake8-bugbear's B008 (function-call-in-default-argument) lint warning.

Sprint 3 (FEAT-02-3, FEAT-02-4) additions are grouped below the Sprint 1/2
dependencies; every existing dependency keeps its exact name and behavior.
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
from .federation import FederationConfig, load_federation_config
from .keycloak_client import KeycloakClient
from .rate_limit import InMemoryRateLimiter, RateLimiter
from .service_principal import ServicePrincipal
from .service_token_validator import ServiceTokenValidator
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


# --- Sprint 3: Service Identity & M2M Authentication (FEAT-02-3) ----------


def service_token_validator_dependency(settings: SettingsDep) -> ServiceTokenValidator:
    return ServiceTokenValidator(settings)


ServiceTokenValidatorDep = Annotated[
    ServiceTokenValidator, Depends(service_token_validator_dependency)
]


def get_current_service_principal(
    validator: ServiceTokenValidatorDep,
    authorization: Annotated[str | None, Header()] = None,
) -> ServicePrincipal:
    """Extract and verify a Bearer token as a machine (service) token.

    Deliberately separate from `get_current_principal`: a route that
    requires a service caller depends on this function, never on
    `get_current_principal`, so the two identity kinds cannot be mixed up at
    the routing layer either (Required Security Controls: "Separation
    between human and machine identities")."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthorizationError("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    return validator.validate(token)


@lru_cache
def _login_rate_limiter_singleton() -> InMemoryRateLimiter:
    settings = _settings_singleton()
    return InMemoryRateLimiter(
        max_attempts=settings.login_rate_limit_max_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )


def login_rate_limiter_dependency() -> RateLimiter:
    return _login_rate_limiter_singleton()


LoginRateLimiterDep = Annotated[RateLimiter, Depends(login_rate_limiter_dependency)]


# --- Sprint 3: Identity Federation Readiness (FEAT-02-4) -------------------


@lru_cache
def _federation_config_singleton() -> FederationConfig:
    settings = _settings_singleton()
    return load_federation_config(settings.federation_config_path)


def federation_config_dependency() -> FederationConfig:
    return _federation_config_singleton()


FederationConfigDep = Annotated[FederationConfig, Depends(federation_config_dependency)]
