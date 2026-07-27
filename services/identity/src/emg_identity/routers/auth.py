"""Authentication endpoints — FEAT-02-1 (Identity Provider Integration) and
FEAT-02-2 (Authentication Session Management).

Sprint 3 adds only rate-limiting readiness to `/login` (Required Security
Controls: "Rate-limiting readiness for token requests"); no Sprint 2 route
signature, status code, or response shape changed.
"""

from __future__ import annotations

from typing import Annotated

from emg_auth_client import Principal
from emg_errors import AuthorizationError
from emg_telemetry import get_correlation_id
from fastapi import APIRouter, Depends

from ..audit import AuditEventSink
from ..dependencies import (
    audit_sink_dependency,
    get_current_principal,
    keycloak_client_dependency,
    login_rate_limiter_dependency,
    session_manager_dependency,
)
from ..keycloak_client import KeycloakClient
from ..rate_limit import RateLimiter
from ..schemas import LoginRequest, RefreshRequest, SessionInfoResponse, TokenResponse
from ..session import SessionManager, _normalize_human_attributes

router = APIRouter(prefix="/auth", tags=["auth"])

KeycloakDep = Annotated[KeycloakClient, Depends(keycloak_client_dependency)]
SessionManagerDep = Annotated[SessionManager, Depends(session_manager_dependency)]
AuditSinkDep = Annotated[AuditEventSink, Depends(audit_sink_dependency)]
CurrentPrincipalDep = Annotated[Principal, Depends(get_current_principal)]
LoginRateLimiterDep = Annotated[RateLimiter, Depends(login_rate_limiter_dependency)]


def _extract_human_attributes(claims: dict[str, object]) -> dict[str, str]:
    """Extract the ABAC-relevant attributes seeded in
    tools/seed-data/keycloak/emg-realm.json (`classification_clearance`,
    `department`) from verified Keycloak access-token claims.

    Both attributes are Keycloak user-attribute claims, which the realm's
    protocol mapper emits as single-element lists (Keycloak's
    `oidc-usermodel-attribute-mapper` convention for multivalued user
    attributes) — this unwraps that shape as well as accepting a bare
    string, so either representation resolves the same way.

    **Group D Phase 1 Remediation:** the "what counts as a valid clearance,
    what's the fail-closed default" decision itself is not made here — it is
    delegated to `session._normalize_human_attributes`, the single helper
    shared with session reconstruction (`SessionManager.verify()`), so a
    fresh login and a reconstructed legacy session apply byte-for-byte
    identical normalization (Legacy Session Normalization). This function's
    only remaining job is unwrapping Keycloak's claim *shape* (bare string
    vs. single-element list) into the flat `dict[str, str]` that shared
    helper expects. `department` has no default of its own: it is preserved
    only when it is a valid, non-empty string, and simply omitted otherwise
    (unlike clearance, no policy rule in this repository treats a missing
    `department` as a security-relevant condition today) — `_normalize_human_attributes`
    does not touch it.
    """

    def _unwrap(value: object) -> object:
        if isinstance(value, list) and value:
            return value[0]
        return value

    attributes: dict[str, str] = {}

    raw_clearance = _unwrap(claims.get("classification_clearance"))
    if isinstance(raw_clearance, str):
        attributes["classification_clearance"] = raw_clearance

    raw_department = _unwrap(claims.get("department"))
    if isinstance(raw_department, str) and raw_department:
        attributes["department"] = raw_department

    return _normalize_human_attributes(attributes)


def _claims_to_principal(username: str, verified_claims: dict[str, object]) -> Principal:
    """Map *verified* Keycloak access-token claims
    (`KeycloakTokenResult.verified_claims` — see keycloak_client.py's module
    docstring for why this is no longer the token endpoint's raw top-level
    JSON) to an emg_auth_client.Principal.

    Realm roles and the ABAC-relevant custom attributes seeded in
    tools/seed-data/keycloak/emg-realm.json (classification_clearance,
    department) are carried through so Module 5's PEP (EPIC-03) has real
    attributes to evaluate, per US-02's acceptance criterion.
    """
    realm_access = verified_claims.get("realm_access")
    roles: tuple[str, ...] = ()
    if isinstance(realm_access, dict):
        roles = tuple(realm_access.get("roles", ()))

    attributes = _extract_human_attributes(verified_claims)

    return Principal(subject=username, roles=roles, attributes=attributes)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    keycloak: KeycloakDep,
    session_manager: SessionManagerDep,
    audit: AuditSinkDep,
    rate_limiter: LoginRateLimiterDep,
) -> TokenResponse:
    correlation_id = get_correlation_id()
    # Rate-limit by username (Required Security Controls: "Rate-limiting
    # readiness for token requests"). Raises RateLimitedError -> HTTP 429
    # (main.py) before any credential is sent to Keycloak.
    rate_limiter.check(request.username)
    try:
        kc_result = await keycloak.login_with_password(request.username, request.password)
    except AuthorizationError:
        audit.record_login_failure(
            username=request.username,
            reason="invalid_credentials",
            correlation_id=correlation_id,
        )
        raise

    principal = _claims_to_principal(request.username, kc_result.verified_claims)
    pair = session_manager.issue(principal)
    audit.record_login_success(subject=principal.subject, correlation_id=correlation_id)

    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshRequest,
    session_manager: SessionManagerDep,
    audit: AuditSinkDep,
) -> TokenResponse:
    correlation_id = get_correlation_id()
    try:
        pair = session_manager.refresh(request.refresh_token)
    except AuthorizationError as exc:
        audit.record_token_refresh_failure(reason=str(exc), correlation_id=correlation_id)
        raise

    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
    )


@router.get("/session", response_model=SessionInfoResponse)
async def session_info(principal: CurrentPrincipalDep) -> SessionInfoResponse:
    return SessionInfoResponse(
        subject=principal.subject,
        roles=list(principal.roles),
        attributes=dict(principal.attributes),
    )
