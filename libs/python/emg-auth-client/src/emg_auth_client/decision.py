"""Authorization decision types (Sprint 4, FEAT-03-1 Policy Enforcement
Point contract).

`Decision` is the PEP's output: a fixed outcome plus a human-readable,
auditable reason. It deliberately carries no exception/control-flow
behavior — a deny is ordinary data, not a raised error — so a caller can
inspect a decision (e.g. for the reference `/authz/check` endpoint in
services/identity) as easily as it can enforce one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DecisionOutcome = Literal["allow", "deny"]


@dataclass(frozen=True)
class Decision:
    """The Policy Enforcement Point's answer to one authorization request.

    `reason` is always populated, for both outcomes — "US-03 acceptance
    criteria: a request with insufficient attributes is denied with an
    auditable reason" applies to allow decisions too, for consistent audit
    logging (Sprint 4 Required: "denial and allow decisions are both
    logged").
    """

    outcome: DecisionOutcome
    reason: str
    policy_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome == "allow"
