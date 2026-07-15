"""Policy Enforcement Point reference/demonstration endpoint — Sprint 4
(FEAT-03-1, FEAT-03-2).

`GET /authz/check` is not new product functionality: it exists solely to
prove the PEP end-to-end (identity resolution -> ABAC policy evaluation ->
audit logging) against a real HTTP surface, the same role
`/auth/service-session` played for Sprint 3's `ServiceTokenValidator`.

It accepts a Bearer token for EITHER identity kind (human `Principal` or
machine `ServicePrincipal`, via `get_current_identity` — see
dependencies.py's docstring for why this composition doesn't weaken the
separation `/auth/session` and `/auth/service-session` still enforce) and
always returns HTTP 200 with the `Decision` in the body: this is an
introspection endpoint ("what would the PEP decide for this caller"), not
an enforcement gate, so there is no ambiguity about repurposing HTTP status
codes for a demonstration surface. Real enforcement
(`if not decision.allowed: raise AuthorizationError(...)`) is each calling
service's own responsibility, exercised directly in
`emg_policy_engine`'s and this router's own tests.
"""

from __future__ import annotations

from typing import Annotated

from emg_auth_client import AuthorizationRequest, Principal
from emg_telemetry import get_correlation_id
from fastapi import APIRouter, Depends

from ..audit import AuditEventSink
from ..dependencies import (
    CurrentIdentityDep,
    PolicyEnforcementPointDep,
    audit_sink_dependency,
)
from ..schemas import PolicyCheckResponse

router = APIRouter(prefix="/authz", tags=["authz"])

AuditSinkDep = Annotated[AuditEventSink, Depends(audit_sink_dependency)]


@router.get("/check", response_model=PolicyCheckResponse)
async def policy_check(
    resource_type: str,
    action: str,
    identity: CurrentIdentityDep,
    pep: PolicyEnforcementPointDep,
    audit: AuditSinkDep,
) -> PolicyCheckResponse:
    correlation_id = get_correlation_id()
    subject = identity.subject if isinstance(identity, Principal) else identity.client_id

    decision = pep.authorize(
        AuthorizationRequest(principal=identity, resource_type=resource_type, action=action)
    )

    audit.record_authorization_decision(
        subject=subject,
        resource_type=resource_type,
        action=action,
        outcome=decision.outcome,
        reason=decision.reason,
        correlation_id=correlation_id,
    )

    return PolicyCheckResponse(
        subject=subject,
        resource_type=resource_type,
        action=action,
        outcome=decision.outcome,
        allowed=decision.allowed,
        reason=decision.reason,
        policy_id=decision.policy_id,
    )
