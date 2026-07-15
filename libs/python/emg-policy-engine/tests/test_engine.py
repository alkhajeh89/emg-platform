"""PolicyEngine evaluation semantics (FEAT-03-2). Covers the Sprint 4 design
decisions: default-deny, deny-overrides, human vs. service principal
conditions, and that a request with sufficient/insufficient attributes is
allowed/denied with an auditable reason (US-03 acceptance criteria)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from emg_auth_client import AuthorizationRequest, Principal
from emg_policy_engine import PolicyConfig, PolicyEngine, PolicyRule


@dataclass(frozen=True)
class _FakeServicePrincipal:
    """Structural ServicePrincipalLike, independent of emg_identity (a
    service, not a shared library — see Sprint 4 design decision)."""

    client_id: str
    service_name: str
    roles: tuple[str, ...]
    scopes: tuple[str, ...]


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


def test_rule_with_required_attributes_can_never_be_satisfied_by_service_principal():
    """A rule that only makes sense for a human (attribute-gated) must not
    accidentally admit a service principal just because it has no
    attributes to check against."""
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
