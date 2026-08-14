"""FastAPI dependency wiring: settings, Keycloak client, session manager,
audit sink, and the current-Principal extractor used by protected routes.

Uses the `Annotated[X, Depends(...)]` style (current FastAPI recommendation)
rather than `x: X = Depends(...)` default-argument style, which also avoids
flake8-bugbear's B008 (function-call-in-default-argument) lint warning.

Sprint 3 (FEAT-02-3, FEAT-02-4) and Sprint 4 (FEAT-03-1, FEAT-03-2)
additions are grouped below the Sprint 1/2 dependencies; every existing
dependency keeps its exact name and behavior.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from emg_auth_client import AuthorizedIdentity, PolicyEnforcementPoint, Principal
from emg_errors import AuthorizationError
from emg_policy_engine import LocalPolicyEnforcementPoint, load_validated_policy_config
from fastapi import Depends, Header

from .audit import AuditEventSink, StructuredLogAuditSink
from .audit_pipeline import (
    AuditDeliveryStatus,
    DurableSpool,
    HttpAuditForwarder,
    PipelineAuditSink,
)
from .auth_client import SessionAuthClient
from .config import Settings, get_settings, validate_runtime_configuration
from .federation import FederationConfig, load_federation_config
from .keycloak_client import KeycloakClient
from .rate_limit import InMemoryRateLimiter, RateLimiter
from .refresh_tokens import (
    InMemoryRefreshTokenStore,
    PostgresRefreshTokenStore,
    RefreshTokenStore,
)
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
    """Constructed with default JWKS-based verification for the human-grant
    access-token claims (Group D Phase 1 Remediation, Blocking Fix 1) — no
    signing_key_resolver override in production; only tests inject one to
    avoid a live Keycloak/JWKS dependency."""
    return KeycloakClient(settings)


@lru_cache
def _refresh_token_store_singleton(
    backend: str, dsn: str, recovery_authority_file: str
) -> RefreshTokenStore:
    if backend == "postgres":
        from pathlib import Path

        return PostgresRefreshTokenStore(
            dsn,
            recovery_authority_file=(
                Path(recovery_authority_file) if recovery_authority_file else None
            ),
        )
    return InMemoryRefreshTokenStore()


def session_manager_dependency(settings: SettingsDep) -> SessionManager:
    return SessionManager(
        settings,
        _refresh_token_store_singleton(
            settings.refresh_token_store_backend,
            settings.refresh_token_postgres_dsn,
            settings.recovery_authority_file,
        ),
    )


SessionManagerDep = Annotated[SessionManager, Depends(session_manager_dependency)]


def auth_client_dependency(session_manager: SessionManagerDep) -> SessionAuthClient:
    return SessionAuthClient(session_manager)


# --- Sprint 6: Audit Event Pipeline forwarding (FEAT-04-1) ----------------
#
# The audit sink is migrated from StructuredLogAuditSink to the
# Protocol-preserving PipelineAuditSink. Forwarding to the audit service is
# gated by `audit_forwarding_enabled` (default False): when off, the sink
# emits ADR-015 telemetry only — byte-for-byte the prior behavior — so every
# Sprint 2-5 call site and test is unaffected. When on, the Decision-C durable
# delivery / spool / dead-letter machinery activates. The spool, status, and
# forwarder are process-level singletons so degraded state persists across
# requests and is visible on the readiness endpoint.


@lru_cache
def _audit_delivery_status_singleton() -> AuditDeliveryStatus:
    return AuditDeliveryStatus()


def audit_delivery_status() -> AuditDeliveryStatus:
    return _audit_delivery_status_singleton()


@lru_cache
def _audit_spool_singleton() -> DurableSpool:
    return DurableSpool(_settings_singleton().audit_spool_path)


def _fetch_service_token(settings: Settings) -> str:
    """Synchronously acquire this service's own client-credentials token to
    authenticate to the audit service. Any failure raises, which the forwarder
    maps to a transient AuditDeliveryError (event spooled, login unaffected)."""
    import httpx

    response = httpx.post(
        f"{settings.keycloak_issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.service_client_id,
            "client_secret": settings.service_client_secret,
        },
        timeout=settings.audit_delivery_timeout_seconds,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str):
        raise RuntimeError("client-credentials response missing access_token")
    return token


@lru_cache
def _pipeline_audit_sink_singleton() -> PipelineAuditSink:
    settings = _settings_singleton()
    forwarder = HttpAuditForwarder(
        base_url=settings.audit_service_base_url,
        token_provider=lambda: _fetch_service_token(settings),
        timeout_seconds=settings.audit_delivery_timeout_seconds,
    )
    return PipelineAuditSink(
        forwarder=forwarder,
        spool=_audit_spool_singleton(),
        status=_audit_delivery_status_singleton(),
        telemetry=StructuredLogAuditSink(),
        max_attempts=settings.audit_delivery_max_attempts,
        enabled=settings.audit_forwarding_enabled,
    )


def audit_sink_dependency() -> AuditEventSink:
    return _pipeline_audit_sink_singleton()


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


# --- Sprint 4: Authorization Platform (FEAT-03-1, FEAT-03-2) ---------------


def get_current_identity(
    auth_client: AuthClientDep,
    validator: ServiceTokenValidatorDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthorizedIdentity:
    """Resolve the current caller as EITHER a human `Principal` OR a machine
    `ServicePrincipal`, trying human-session verification first and falling
    back to service-token verification. Used only by the `/authz/check`
    reference endpoint, which by design must accept either identity kind
    (FEAT-03-1: "support both Principal and ServicePrincipal") — every
    other route keeps depending on exactly one of `get_current_principal` /
    `get_current_service_principal`, unchanged, so this composition never
    weakens the existing structural separation between the two identity
    kinds (Sprint 3 Required Security Control) elsewhere in the service.

    Fails closed: if the header is missing/malformed, or the token matches
    neither trust path, the second (service-token) `AuthorizationError`
    propagates.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthorizationError("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return auth_client.authenticate(token)
    except AuthorizationError:
        pass
    return validator.validate(token)


CurrentIdentityDep = Annotated[AuthorizedIdentity, Depends(get_current_identity)]


@lru_cache
def _policy_enforcement_point_singleton() -> PolicyEnforcementPoint:
    settings = _settings_singleton()
    config = load_validated_policy_config(settings.policy_config_path)
    return LocalPolicyEnforcementPoint(config)


def policy_enforcement_point_dependency() -> PolicyEnforcementPoint:
    return _policy_enforcement_point_singleton()


PolicyEnforcementPointDep = Annotated[
    PolicyEnforcementPoint, Depends(policy_enforcement_point_dependency)
]


def validate_identity_runtime_configuration() -> None:
    """Run production-safety and policy boot gates before serving traffic."""

    validate_runtime_configuration(_settings_singleton())
    _policy_enforcement_point_singleton()
