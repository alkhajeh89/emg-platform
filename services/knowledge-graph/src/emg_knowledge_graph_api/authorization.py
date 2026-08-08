"""Authorization enforcement for the Knowledge Graph Query API (ADR-025
Group C5, C6).

`require_permission(resource_type, action="read")` returns a FastAPI
dependency that, for the calling principal already resolved by
`TenantContextDep`, builds an `emg_auth_client.AuthorizationRequest` and
evaluates it against the shared Policy Enforcement Point
(`PolicyEnforcementPointDep` — `dependencies.py`). A deny raises the new,
platform-wide `emg_errors.PermissionDeniedError`, mapped to HTTP 403
(`errors.py`) by the same centralized `EMGError` handler every other error
in this service already passes through.

This module introduces no authorization logic of its own: `PolicyEngine`
(`emg_policy_engine`) makes every actual allow/deny decision; this module
only supplies the two request-shape values only the HTTP layer knows
(`resource_type`, `action`) and enforces the returned `Decision`. Per
ADR-025 §8.3, this is deliberately the HTTP layer, not
`emg_knowledge_graph` (the Query Engine / domain layer, which is frozen and
carries no principal/authorization concept — see that package's
`test_dependency_boundary.py`) and not `KnowledgeGraphApplication` (whose
ADR-024 contracts are unchanged by this ADR).

Fail-closed (ADR-025 §8.6, §12): any deny — including "no rule matched"
(the Policy Engine's own default-deny) and "policy config file missing"
(`load_policy_config`'s own safe-default, an empty ruleset that denies
everything) — is a 403, never a silent allow. This module never treats an
evaluation problem as an implicit allow; `PolicyEnforcementPoint.authorize`
is documented as MUST be fail-closed on its own internal errors, and this
helper adds no exception-swallowing around that call.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, NoReturn

from emg_auth_client import AuthorizationRequest, Decision, PolicyEnforcementPoint
from emg_errors import PermissionDeniedError, UpstreamServiceError
from emg_telemetry import get_correlation_id

from . import audit_producer
from .authn import AuthenticatedCallerDep, CallerContext, SettingsDep, TenantContextDep
from .config import Settings
from .dependencies import PolicyEnforcementPointDep

DEFAULT_ACTION = "read"


def _authorize(
    caller: CallerContext,
    resource_type: str,
    action: str,
    pep: PolicyEnforcementPoint,
) -> Decision:
    """Shared by `require_permission` and `require_permission_delegated_aware`
    (correction-sprint Finding 12): identical `AuthorizationRequest`
    construction and PEP evaluation for both, so the two public factories
    below cannot drift out of sync on security-critical logic. Returns the
    raw `Decision` — each caller below decides how to act on a deny (both
    ultimately raise `PermissionDeniedError`; the delegated-aware path also
    attempts audit attribution first, see Finding 6)."""
    request = AuthorizationRequest(
        principal=caller.principal,
        resource_type=resource_type,
        action=action,
    )
    return pep.authorize(request)


def _deny(resource_type: str, action: str, decision: Decision) -> NoReturn:
    raise PermissionDeniedError(
        f"principal is not permitted to {action!r} {resource_type!r}: {decision.reason}"
    )


def require_permission(
    resource_type: str, action: str = DEFAULT_ACTION
) -> Callable[[CallerContext, PolicyEnforcementPoint], None]:
    """Return a FastAPI dependency authorizing `action` on `resource_type`
    for the authenticated, tenant-resolved caller.

    `resource_type`/`action` are supplied per-route (ADR-025 §8.5's mapping
    table) — the same pair every request against that route is evaluated
    against, mirroring `identity`'s `policy.example.yaml` convention of one
    `resource_type`/`action` per protected surface (e.g.
    `identity.diagnostics`/`read`).
    """

    def _dependency(
        caller: TenantContextDep,
        pep: PolicyEnforcementPointDep,
    ) -> None:
        decision = _authorize(caller, resource_type, action, pep)
        if not decision.allowed:
            _deny(resource_type, action, decision)

    return _dependency


def require_permission_delegated_aware(
    resource_type: str, action: str = DEFAULT_ACTION
) -> Callable[[CallerContext, PolicyEnforcementPoint, Settings], Coroutine[Any, Any, None]]:
    """Phase 2B: identical to `require_permission` in every respect —
    same `AuthorizationRequest` shape, same PEP call, same fail-closed
    deny-raises-403 behavior, same `ADR-025`/`ADR-026` semantics — except
    it depends on `AuthenticatedCallerDep` instead of `TenantContextDep`, so
    it accepts a Delegated Credential's resolved Human Principal as well as
    a plain service token.

    Used ONLY by the read routes that Phase 2B exposes through the Studio
    BFF proxy. `require_permission` above is untouched and remains the sole
    dependency mutation routes use — this is a parallel factory, not a
    replacement, precisely so a delegated (human) credential can never
    reach a mutation route through this module.

    **Correction-sprint Finding 6.** A delegated (human-attributed) caller's
    DENY decision is now also audit-attributed here, before the caller ever
    sees the 403 — not only successes, which each route body separately
    attributes with richer resource-level detail after a 200 is already
    guaranteed. ADR-038 §8.7 requires "authorization decision" to be
    recorded for "every delegated operation," not only allowed ones. If
    attribution of the denial itself cannot be completed, this raises
    `UpstreamServiceError` (500) instead of `PermissionDeniedError` (403) —
    an unattributed delegated denial is not an acceptable fallback. A
    non-delegated (`caller.acting_service is None`) deny is completely
    unaffected: no audit call is attempted, behavior is byte-for-byte
    unchanged from before this correction."""

    async def _dependency(
        caller: AuthenticatedCallerDep,
        pep: PolicyEnforcementPointDep,
        settings: SettingsDep,
    ) -> None:
        decision = _authorize(caller, resource_type, action, pep)
        if decision.allowed:
            return
        if caller.acting_service is not None:
            try:
                await audit_producer.emit_delegated_audit_event(
                    settings,
                    caller,
                    resource_type=resource_type,
                    resource_id=None,
                    action=action,
                    outcome="denied",
                    correlation_id=get_correlation_id(),
                )
            except UpstreamServiceError as exc:
                raise UpstreamServiceError(
                    f"delegated denial for {action!r} {resource_type!r} could not be "
                    f"audit-attributed: {exc}"
                ) from exc
        _deny(resource_type, action, decision)

    return _dependency
