"""ABAC policy configuration schema (FEAT-03-2).

Mirrors the shape and safety posture of Sprint 3's
`emg_identity.federation` module deliberately: a pydantic schema, a safe
default, a `load_*` function that never raises on a missing file, and a
`validate_*` function callers use before trusting a loaded config.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PolicyRule(BaseModel):
    """One ABAC rule: does `principal` satisfy the stated conditions to
    perform `action` on a resource of type `resource_type`?

    Conditions are two independent tracks, matching the two identity kinds
    `AuthorizationRequest.principal` can hold (Sprint 4 design decision:
    "support both Principal and ServicePrincipal"):

    - `required_roles` + `required_attributes` apply to a human `Principal`.
    - `required_roles` + `required_scopes` apply to a machine
      `ServicePrincipalLike`. A rule that sets `required_attributes` can
      never be satisfied by a service principal (it has no `attributes`),
      by design — see `docs/engineering/sprint-4-design.md`.

    `required_roles` is evaluated any-of (at least one of the principal's
    roles must appear here, or the list must be empty = no role
    requirement). `required_attributes` is evaluated all-of: every named
    attribute key must be present on the principal with a value in the
    given allow-list. `required_scopes` is any-of, same shape as
    `required_roles`.
    """

    rule_id: str
    resource_type: str
    action: str
    effect: str = Field(default="allow", pattern="^(allow|deny)$")
    description: str = ""
    required_roles: list[str] = Field(default_factory=list)
    required_attributes: dict[str, list[str]] = Field(default_factory=dict)
    required_scopes: list[str] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    """A versioned ruleset. There is no configurable "default effect" field
    here — Sprint 4 design decision: default-deny is fixed in
    `PolicyEngine.evaluate()`, not an operator-adjustable setting, so a
    misconfigured policy file can never flip the platform's fail-closed
    posture."""

    rules: list[PolicyRule] = Field(default_factory=list)
