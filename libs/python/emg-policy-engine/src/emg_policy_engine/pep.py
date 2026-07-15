"""Default `PolicyEnforcementPoint` implementation (FEAT-03-1 + FEAT-03-2).

`LocalPolicyEnforcementPoint` is the concrete class services construct and
depend on through the `emg_auth_client.PolicyEnforcementPoint` Protocol —
callers should type against the Protocol, not this class, so a future
alternative implementation (e.g. a remote-PDP-backed one, if a later sprint
ever needs it) is a drop-in swap.
"""

from __future__ import annotations

from emg_auth_client import AuthorizationRequest, Decision

from .engine import PolicyEngine
from .rules import PolicyConfig


class LocalPolicyEnforcementPoint:
    """Wraps a `PolicyEngine` behind the shared `PolicyEnforcementPoint`
    contract. Fail-closed by construction: `PolicyEngine.evaluate()` never
    raises for an ordinary policy outcome, so this class does not need (and
    deliberately does not have) a broad try/except that could mask a real
    bug as a denial — a bug here should fail loudly in tests, not silently
    manifest as an unexplained deny in production.
    """

    def __init__(self, config: PolicyConfig) -> None:
        self._engine = PolicyEngine(config)

    def authorize(self, request: AuthorizationRequest) -> Decision:
        return self._engine.evaluate(request)
