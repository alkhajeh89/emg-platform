"""PolicyEngine evaluation semantics (FEAT-03-2; extended by ADR-026
Revision 2, Amendments 1 and 2). Covers the Sprint 4 design decisions:
default-deny, deny-overrides, human vs. service principal conditions, and
that a request with sufficient/insufficient attributes is allowed/denied
with an auditable reason (US-03 acceptance criteria) — plus ADR-026 Revision
2's symmetric `required_resource_attributes` matching and the retired
service-principal `required_attributes` exclusion."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from emg_auth_client import AuthorizationRequest, Principal
from emg_policy_engine import PolicyConfig, PolicyEngine, PolicyRule


@dataclass(frozen=True)
class _FakeServicePrincipal:
    """Structural ServicePrincipalLike, independent of emg_identity (a
    service, not a shared library — see Sprint 4 design decision).
    `attributes` (ADR-026 Revision 2, Amendment 2) defaults to an empty dict
    so existing call sites below that omit it are unaffected."""

    client_id: str
    service_name: str
    roles: tuple[str, ...]
    scopes: tuple[str, ...]
    attributes: dict[str, str] = field(default_factory=dict)


def _investigator(**overrides: object) -> Principal:
    defaults: dict[str, object] = {
        "subject": "dev.investigator",
        "roles": ("platform-user", "investigator"),
        "attributes": {"classification_clearance": "INTERNAL", "department": "Investigations"},
    }
    defaults.update(overrides)
    return Principal(**defaults)  # type: ignore[arg-type]


def test_no_matching_rule_denies_by_default():
    engine = PolicyEngine(PolicyConfig(rules=[]))
    decision = engine.evaluate(
        AuthorizationRequest(principal=_investigator(), resource_type="widget", action="read")
    )
    assert decision.outcome == "deny"
    assert "default-deny" in decision.reason


def test_sufficient_attributes_and_role_are_allowed():
    rule = PolicyRule(
        rule_id="diag-read",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_roles=["platform-user"],
        required_attributes={"classification_clearance": ["INTERNAL", "CONFIDENTIAL", "SECRET"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    decision = engine.evaluate(
        AuthorizationRequest(
            principal=_investigator(), resource_type="identity.diagnostics", action="read"
        )
    )
    assert decision.outcome == "allow"
    assert decision.policy_id == "diag-read"
    assert decision.reason  # auditable reason is always populated


def test_insufficient_attributes_are_denied_with_reason():
    rule = PolicyRule(
        rule_id="diag-read",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_roles=["platform-user"],
        required_attributes={"classification_clearance": ["SECRET"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    principal = _investigator(attributes={"classification_clearance": "INTERNAL"})
    decision = engine.evaluate(
        AuthorizationRequest(
            principal=principal, resource_type="identity.diagnostics", action="read"
        )
    )
    assert decision.outcome == "deny"
    assert decision.reason


def test_insufficient_role_is_denied():
    rule = PolicyRule(
        rule_id="diag-read",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_roles=["decision-maker"],
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    decision = engine.evaluate(
        AuthorizationRequest(
            principal=_investigator(), resource_type="identity.diagnostics", action="read"
        )
    )
    assert decision.outcome == "deny"


def test_deny_rule_overrides_matching_allow_rule():
    allow_rule = PolicyRule(
        rule_id="allow-all-investigators",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_roles=["investigator"],
    )
    deny_rule = PolicyRule(
        rule_id="deny-low-clearance",
        resource_type="identity.diagnostics",
        action="read",
        effect="deny",
        required_attributes={"classification_clearance": ["INTERNAL"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[allow_rule, deny_rule]))
    decision = engine.evaluate(
        AuthorizationRequest(
            principal=_investigator(), resource_type="identity.diagnostics", action="read"
        )
    )
    assert decision.outcome == "deny"
    assert decision.policy_id == "deny-low-clearance"


def test_service_principal_evaluated_by_role_and_scope():
    rule = PolicyRule(
        rule_id="svc-authz-read",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_roles=["svc-authorization"],
        required_scopes=["svc-authorization"],
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    service = _FakeServicePrincipal(
        client_id="emg-svc-authorization",
        service_name="authorization",
        roles=("service-account", "svc-authorization"),
        scopes=("svc-authorization",),
    )
    decision = engine.evaluate(
        AuthorizationRequest(principal=service, resource_type="identity.diagnostics", action="read")
    )
    assert decision.outcome == "allow"


def test_service_principal_denied_without_required_scope():
    rule = PolicyRule(
        rule_id="svc-authz-read",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_roles=["svc-authorization"],
        required_scopes=["svc-authorization-write"],
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    service = _FakeServicePrincipal(
        client_id="emg-svc-authorization",
        service_name="authorization",
        roles=("service-account", "svc-authorization"),
        scopes=("svc-authorization",),
    )
    decision = engine.evaluate(
        AuthorizationRequest(principal=service, resource_type="identity.diagnostics", action="read")
    )
    assert decision.outcome == "deny"


def test_rule_with_required_attributes_denies_a_service_principal_lacking_the_attribute():
    """Prior to ADR-026 Revision 2, a rule with `required_attributes` could
    *never* be satisfied by a service principal (no `attributes` field
    existed on `ServicePrincipalLike` at all). ADR-026 Revision 2 (Amendment
    2) retires that categorical exclusion — a service principal is now
    evaluated on `required_attributes` exactly like a human Principal. This
    particular service principal still has no matching attribute, so the
    rule is still not satisfied — but for an ordinary "attribute missing"
    reason now, not a "service principals are exempt" reason."""
    rule = PolicyRule(
        rule_id="human-only",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_attributes={"classification_clearance": ["INTERNAL"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    service = _FakeServicePrincipal(
        client_id="emg-svc-authorization",
        service_name="authorization",
        roles=("service-account",),
        scopes=(),
    )
    decision = engine.evaluate(
        AuthorizationRequest(principal=service, resource_type="identity.diagnostics", action="read")
    )
    assert decision.outcome == "deny"


def test_rule_with_required_attributes_is_satisfied_by_service_principal_with_matching_attribute():
    """ADR-026 Revision 2 (Amendment 2, Group D4): a service principal whose
    `attributes` dict actually satisfies a rule's `required_attributes` is
    now allowed — proving the retired exclusion, not just its removal."""
    rule = PolicyRule(
        rule_id="clearance-gated",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_attributes={"classification_clearance": ["INTERNAL", "CONFIDENTIAL", "SECRET"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    service = _FakeServicePrincipal(
        client_id="emg-svc-authorization",
        service_name="authorization",
        roles=("service-account",),
        scopes=(),
        attributes={"classification_clearance": "CONFIDENTIAL"},
    )
    decision = engine.evaluate(
        AuthorizationRequest(principal=service, resource_type="identity.diagnostics", action="read")
    )
    assert decision.outcome == "allow"
    assert decision.policy_id == "clearance-gated"


def test_service_principal_missing_attributes_field_is_denied_not_crashed():
    """A `ServicePrincipalLike`-shaped object that structurally predates the
    ADR-026 Revision 2 `attributes` field (no attribute at all, not even an
    empty dict) must still fail closed via a deny, never an
    `AttributeError` — the same robustness guarantee
    `test_negative_protocols.py` already established for the human path."""

    class _LegacyServicePrincipal:
        client_id = "emg-svc-legacy"
        service_name = "legacy"
        roles: tuple[str, ...] = ("service-account",)
        scopes: tuple[str, ...] = ()
        # Deliberately no `attributes` attribute at all.

    rule = PolicyRule(
        rule_id="clearance-gated",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_attributes={"classification_clearance": ["INTERNAL"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    decision = engine.evaluate(
        AuthorizationRequest(
            principal=_LegacyServicePrincipal(),  # type: ignore[arg-type]
            resource_type="identity.diagnostics",
            action="read",
        )
    )
    assert decision.outcome == "deny"


# --- ADR-026 Revision 2 (Amendment 1): required_resource_attributes -------


def test_resource_attributes_allow_rule_is_satisfied_when_classification_matches():
    rule = PolicyRule(
        rule_id="kg-entity-read-unclassified",
        resource_type="knowledge-graph.entity",
        action="read",
        effect="allow",
        required_roles=["investigator"],
        required_resource_attributes={"classification": ["UNCLASSIFIED"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    principal = _investigator()
    decision = engine.evaluate(
        AuthorizationRequest(
            principal=principal,
            resource_type="knowledge-graph.entity",
            action="read",
            resource_attributes={"classification": "UNCLASSIFIED"},
        )
    )
    assert decision.outcome == "allow"
    assert decision.policy_id == "kg-entity-read-unclassified"


def test_resource_attributes_allow_rule_is_not_satisfied_when_classification_mismatches():
    rule = PolicyRule(
        rule_id="kg-entity-read-unclassified",
        resource_type="knowledge-graph.entity",
        action="read",
        effect="allow",
        required_roles=["investigator"],
        required_resource_attributes={"classification": ["UNCLASSIFIED"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    decision = engine.evaluate(
        AuthorizationRequest(
            principal=_investigator(),
            resource_type="knowledge-graph.entity",
            action="read",
            resource_attributes={"classification": "SECRET"},
        )
    )
    assert decision.outcome == "deny"


def test_resource_attributes_condition_is_vacuously_satisfied_when_absent_from_rule():
    """A rule with no `required_resource_attributes` (ADR-025's existing
    operation-level authorization rules) must remain satisfiable regardless
    of what `resource_attributes` the request carries — including an empty
    dict (the normal ADR-025 per-request call shape) and a populated one
    (ADR-026 Revision 2's per-object classification call shape). This is
    what keeps ADR-025 byte-for-byte unaffected by this extension."""
    rule = PolicyRule(
        rule_id="kg-entity-read",
        resource_type="knowledge-graph.entity",
        action="read",
        effect="allow",
        required_roles=["investigator"],
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))

    no_resource_attrs = engine.evaluate(
        AuthorizationRequest(
            principal=_investigator(), resource_type="knowledge-graph.entity", action="read"
        )
    )
    assert no_resource_attrs.outcome == "allow"

    with_resource_attrs = engine.evaluate(
        AuthorizationRequest(
            principal=_investigator(),
            resource_type="knowledge-graph.entity",
            action="read",
            resource_attributes={"classification": "SECRET"},
        )
    )
    assert with_resource_attrs.outcome == "allow"


def test_resource_attributes_deny_overrides_an_unconditional_allow_rule():
    """The exact pattern services/knowledge-graph/config/policy.example.yaml
    uses (ADR-026 Revision 2, Group D6): an unconditional allow rule (no
    resource-attribute condition, ADR-025's existing operation-level check)
    plus a deny rule gated on insufficient clearance for a specific object's
    classification. The deny must override the allow exactly when the
    object's classification is populated and exceeds the caller's
    clearance, and never fire when resource_attributes is empty."""
    allow_rule = PolicyRule(
        rule_id="kg-entity-read",
        resource_type="knowledge-graph.entity",
        action="read",
        effect="allow",
        required_roles=["investigator"],
    )
    deny_rule = PolicyRule(
        rule_id="kg-entity-deny-unclassified-clearance",
        resource_type="knowledge-graph.entity",
        action="read",
        effect="deny",
        required_attributes={"classification_clearance": ["UNCLASSIFIED"]},
        required_resource_attributes={"classification": ["INTERNAL", "CONFIDENTIAL", "SECRET"]},
    )
    engine = PolicyEngine(PolicyConfig(rules=[allow_rule, deny_rule]))
    uncleared = _investigator(attributes={"classification_clearance": "UNCLASSIFIED"})

    # ADR-025's per-request check: empty resource_attributes, deny rule
    # never matches, plain allow rule grants access to the operation itself.
    operation_level = engine.evaluate(
        AuthorizationRequest(
            principal=uncleared, resource_type="knowledge-graph.entity", action="read"
        )
    )
    assert operation_level.outcome == "allow"

    # ADR-026 Revision 2's per-object check: an INTERNAL-classified object
    # exceeds the caller's UNCLASSIFIED clearance — deny overrides the
    # otherwise-unconditional allow.
    classified_object = engine.evaluate(
        AuthorizationRequest(
            principal=uncleared,
            resource_type="knowledge-graph.entity",
            action="read",
            resource_attributes={"classification": "INTERNAL"},
        )
    )
    assert classified_object.outcome == "deny"
    assert classified_object.policy_id == "kg-entity-deny-unclassified-clearance"

    # A caller with sufficient clearance is unaffected by the deny rule.
    cleared = _investigator(attributes={"classification_clearance": "CONFIDENTIAL"})
    allowed_object = engine.evaluate(
        AuthorizationRequest(
            principal=cleared,
            resource_type="knowledge-graph.entity",
            action="read",
            resource_attributes={"classification": "INTERNAL"},
        )
    )
    assert allowed_object.outcome == "allow"
    assert allowed_object.policy_id == "kg-entity-read"


@pytest.mark.parametrize(
    "resource_type,action", [("identity.diagnostics", "write"), ("other", "read")]
)
def test_rule_only_matches_its_exact_resource_type_and_action(resource_type, action):
    rule = PolicyRule(
        rule_id="diag-read",
        resource_type="identity.diagnostics",
        action="read",
        effect="allow",
        required_roles=["platform-user"],
    )
    engine = PolicyEngine(PolicyConfig(rules=[rule]))
    decision = engine.evaluate(
        AuthorizationRequest(principal=_investigator(), resource_type=resource_type, action=action)
    )
    assert decision.outcome == "deny"
