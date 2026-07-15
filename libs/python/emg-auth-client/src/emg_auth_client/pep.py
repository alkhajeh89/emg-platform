"""Policy Enforcement Point contract (Sprint 4, FEAT-03-1).

`PolicyEnforcementPoint` is the interface every module programs against to
get an authorization decision — "every module evaluates authorization
consistently instead of reimplementing it" (US-03). The concrete, default
implementation (local ABAC evaluation against a policy configuration) is
`emg_policy_engine.LocalPolicyEnforcementPoint` (FEAT-03-2, a separate
package: policy *evaluation* is a distinct concern from the client
*contract*, the same split `emg-auth-client` (contract) / `services/identity`
(implementation) already uses for `AuthClient`/`AuthorizationError`).

This module defines only the contract. It contains no ABAC rule evaluation
logic and no network or file I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .decision import Decision
from .principal import Principal
from .service_principal_protocol import ServicePrincipalLike

# "Support both Principal and ServicePrincipal" — FEAT-03-1 requirement.
AuthorizedIdentity = Principal | ServicePrincipalLike


@dataclass(frozen=True)
class AuthorizationRequest:
    """One authorization question: can `principal` perform `action` on a
    resource of type `resource_type`?

    `resource_attributes` is optional, resource-side context (e.g. the
    specific resource's own classification) a policy rule may condition on,
    distinct from the *principal's* attributes (`Principal.attributes`).
    """

    principal: AuthorizedIdentity
    resource_type: str
    action: str
    resource_attributes: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class PolicyEnforcementPoint(Protocol):
    def authorize(self, request: AuthorizationRequest) -> Decision:
        """Evaluate `request` and return a Decision. Never raises for an
        ordinary deny — a deny is a normal `Decision`, not an exception.
        Implementations MUST be fail-closed: any internal error (malformed
        policy, unexpected principal shape) is a `Decision(outcome="deny")`,
        never a silently-allowed request and never an unhandled exception
        that could bypass a caller's own error handling."""
        ...
