"""ABAC policy configuration schema (FEAT-03-2).

Mirrors the shape and safety posture of Sprint 3's
`emg_identity.federation` module deliberately: a pydantic schema, a safe
default, a `load_*` function that never raises on a missing file, and a
`validate_*` function callers use before trusting a loaded config.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PolicyRule(BaseModel):
    """One ABAC rule: does `principal` satisfy the stated conditions to
    perform `action` on a resource of type `resource_type`?

    Conditions are three independent tracks (ADR-026 Revision 2, Amendment 1
    extends the original two-track Sprint 4 design):

    - `required_roles` + `required_attributes` apply to a human `Principal`.
    - `required_roles` + `required_attributes` + `required_scopes` apply to a
      machine `ServicePrincipalLike`. Prior to ADR-026 Revision 2, a rule
      that set `required_attributes` could never be satisfied by a service
      principal, because `ServicePrincipalLike` carried no `attributes`
      field. ADR-026 Revision 2 (Amendment 2) extended `ServicePrincipalLike`
      with `attributes: dict[str, str]`, mirroring `Principal.attributes`
      exactly, so `required_attributes` is now evaluated identically for
      both principal kinds (`PolicyEngine._service_conditions_satisfied`).
    - `required_resource_attributes` applies to *either* principal kind,
      symmetrically with `required_attributes` — the difference is which
      side of the request it is matched against. `required_attributes` is
      matched against the *principal's* own attributes (who is asking);
      `required_resource_attributes` is matched against
      `AuthorizationRequest.resource_attributes` (what is being asked about,
      e.g. a specific object's classification). This is ADR-026 Revision 2's
      Amendment 1: classification enforcement is evaluated through this
      existing symmetric-matching mechanism, not a second, separate
      comparator outside the Policy Engine. See
      `docs/architecture/EMG_ADR-026_KNOWLEDGE_GRAPH_CLASSIFICATION_ENFORCEMENT_MODEL.md`
      (Revision 2) §8.2, §8.9, and Appendix ADR-026A.

    `required_roles` is evaluated any-of (at least one of the principal's
    roles must appear here, or the list must be empty = no role
    requirement). `required_attributes` is evaluated all-of: every named
    attribute key must be present on the principal with a value in the
    given allow-list. `required_scopes` is any-of, same shape as
    `required_roles`. `required_resource_attributes` is evaluated all-of,
    identically in shape to `required_attributes`, but against
    `request.resource_attributes` instead of the principal.

    Per ADR-026A principle 1: this remains a purely declarative,
    allow-list/all-of matching schema. `required_resource_attributes` is not
    an expression language, an ordinal operator, or a scripting hook — an
    ordinal concept such as "classification dominance" is expressed by
    authoring one rule per satisfying combination (enumerated policy data),
    never by a new comparison primitive in this schema or in `PolicyEngine`.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    resource_type: str
    action: str
    effect: str = Field(default="allow", pattern="^(allow|deny)$")
    description: str = ""
    required_roles: list[str] = Field(default_factory=list)
    required_attributes: dict[str, list[str]] = Field(default_factory=dict)
    required_scopes: list[str] = Field(default_factory=list)
    required_resource_attributes: dict[str, list[str]] = Field(default_factory=dict)


class PolicyConfig(BaseModel):
    """A versioned ruleset. There is no configurable "default effect" field
    here — Sprint 4 design decision: default-deny is fixed in
    `PolicyEngine.evaluate()`, not an operator-adjustable setting, so a
    misconfigured policy file can never flip the platform's fail-closed
    posture."""

    model_config = ConfigDict(extra="forbid")

    rules: list[PolicyRule] = Field(default_factory=list)
