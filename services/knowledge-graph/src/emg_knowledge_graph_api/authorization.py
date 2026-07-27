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

from collections.abc import Callable

from emg_auth_client import AuthorizationRequest, PolicyEnforcementPoint
from emg_errors import PermissionDeniedError

from .authn import CallerContext, TenantContextDep
from .dependencies import PolicyEnforcementPointDep

DEFAULT_ACTION = "read"


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
        request = AuthorizationRequest(
            principal=caller.principal,
            resource_type=resource_type,
            action=action,
        )
        decision = pep.authorize(request)
        if not decision.allowed:
            raise PermissionDeniedError(
                f"principal is not permitted to {action!r} {resource_type!r}: " f"{decision.reason}"
            )

    return _dependency
