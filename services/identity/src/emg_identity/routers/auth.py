"""Authentication endpoints — FEAT-02-1 (Identity Provider Integration) and
FEAT-02-2 (Authentication Session Management).
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
    session_manager_dependency,
)
from ..keycloak_client import KeycloakClient
from ..schemas import LoginRequest, RefreshRequest, SessionInfoResponse, TokenResponse
from ..session import SessionManager

router = APIRouter(prefix="/auth", tags=["auth"])

KeycloakDep = Annotated[KeycloakClient, Depends(keycloak_client_dependency)]
SessionManagerDep = Annotated[SessionManager, Depends(session_manager_dependency)]
AuditSinkDep = Annotated[AuditEventSink, Depends(audit_sink_dependency)]
CurrentPrincipalDep = Annotated[Principal, Depends(get_current_principal)]


def _claims_to_principal(username: str, raw_claims: dict[str, object]) -> Principal:
    """Map Keycloak's token claims to an emg_auth_client.Principal.

    Realm roles and the ABAC-relevant custom attributes seeded in
    tools/seed-data/keycloak/emg-realm.json (classification_clearance,
    department) are carried through so Module 5's PEP (EPIC-03) has real
    attributes to evaluate once it exists, per US-02's acceptance criterion.
    """
    realm_access = raw_claims.get("realm_access")
    roles: tuple[str, ...] = ()
    if isinstance(realm_access, dict):
        roles = tuple(realm_access.get("roles", ()))

    attributes: dict[str, str] = {}
    for key in ("classification_clearance", "department"):
        value = raw_claims.get(key)
        if isinstance(value, list) and value:
            attributes[key] = str(value[0])
        elif isinstance(value, str):
            attributes[key] = value

    return Principal(subject=username, roles=roles, attributes=attributes)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    keycloak: KeycloakDep,
    session_manager: SessionManagerDep,
    audit: AuditSinkDep,
) -> TokenResponse:
    correlation_id = get_correlation_id()
    try:
        kc_result = await keycloak.login_with_password(request.username, request.password)
    except AuthorizationError:
        audit.record_login_failure(
            username=request.username,
            reason="invalid_credentials",
            correlation_id=correlation_id,
        )
        raise

    principal = _claims_to_principal(request.username, kc_result.raw_claims)
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
