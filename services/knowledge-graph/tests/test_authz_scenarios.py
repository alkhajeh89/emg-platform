"""Real adoption of the shared authorization testing harness for the
Knowledge Graph Query API (ADR-025 Group C9).

Mirrors `services/identity/tests/test_authz_scenarios.py` field-for-field:
declarative expectations against the real, shipped
`config/policy.example.yaml`, expressed via `AuthorizationScenario` /
`assert_scenario` / `run_scenarios` instead of hand-rolled engine or HTTP
assertions. This is deliberately additive to, and does not replace,
`tests/api/test_authorization.py` (HTTP-level) — both suites coexist and
both pass. It also uses this service's real `ServicePrincipal` type (not a
structural fake), demonstrating the harness accepts the actual
machine-identity shape this service's `authn.py` issues.

The ABAC combining logic itself (default-deny, deny-overrides, human vs.
service condition tracks) is unit-tested in
`libs/python/emg-policy-engine/tests/test_engine.py`, not re-tested here.
"""

from __future__ import annotations

from pathlib import Path

from emg_auth_client import AuthorizationRequest, Principal
from emg_knowledge_graph_api.authn import ServicePrincipal
from emg_policy_engine import (
    AuthorizationScenario,
    LocalPolicyEnforcementPoint,
    assert_scenario,
    load_policy_config,
    run_scenarios,
)

_POLICY_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "policy.example.yaml"


def _pep() -> LocalPolicyEnforcementPoint:
    return LocalPolicyEnforcementPoint(load_policy_config(_POLICY_CONFIG_PATH))


def _investigator() -> Principal:
    return Principal(subject="dev.investigator", roles=("platform-user", "investigator"))


def _decision_maker() -> Principal:
    return Principal(subject="dev.decider", roles=("platform-user", "decision-maker"))


def _knowledge_steward() -> Principal:
    return Principal(subject="dev.steward", roles=("platform-user", "knowledge-steward"))


def _baseline_platform_user() -> Principal:
    # A human with only the baseline role — deliberately NOT granted by
    # policy.example.yaml (ADR-025 Group C4/C8: platform-user alone has no
    # job-function tie to the Knowledge Graph).
    return Principal(subject="dev.someone", roles=("platform-user",))


def _registered_service() -> ServicePrincipal:
    return ServicePrincipal(client_id="emg-svc-retrieval", roles=("service-account",))


def _unregistered_service_role() -> ServicePrincipal:
    # A service principal with no recognized role at all.
    return ServicePrincipal(client_id="emg-svc-unknown", roles=())


_ALLOWED_RESOURCE_TYPES = (
    "knowledge-graph.entity",
    "knowledge-graph.edge",
    "knowledge-graph.neighbors",
    "knowledge-graph.path",
    "knowledge-graph.history",
)

_SCENARIOS = [
    *(
        AuthorizationScenario(
            name=f"investigator may read {resource_type}",
            principal=_investigator(),
            resource_type=resource_type,
            action="read",
            expected_outcome="allow",
        )
        for resource_type in _ALLOWED_RESOURCE_TYPES
    ),
    *(
        AuthorizationScenario(
            name=f"decision-maker may read {resource_type}",
            principal=_decision_maker(),
            resource_type=resource_type,
            action="read",
            expected_outcome="allow",
        )
        for resource_type in _ALLOWED_RESOURCE_TYPES
    ),
    *(
        AuthorizationScenario(
            name=f"knowledge-steward may read {resource_type}",
            principal=_knowledge_steward(),
            resource_type=resource_type,
            action="read",
            expected_outcome="allow",
        )
        for resource_type in _ALLOWED_RESOURCE_TYPES
    ),
    *(
        AuthorizationScenario(
            name=f"registered service principal may read {resource_type}",
            principal=_registered_service(),
            resource_type=resource_type,
            action="read",
            expected_outcome="allow",
        )
        for resource_type in _ALLOWED_RESOURCE_TYPES
    ),
    AuthorizationScenario(
        name="baseline platform-user alone is denied (missing role)",
        principal=_baseline_platform_user(),
        resource_type="knowledge-graph.entity",
        action="read",
        expected_outcome="deny",
    ),
    AuthorizationScenario(
        name="service principal with no roles is denied (missing role)",
        principal=_unregistered_service_role(),
        resource_type="knowledge-graph.entity",
        action="read",
        expected_outcome="deny",
    ),
    AuthorizationScenario(
        name="unknown resource type is denied by default (default-deny)",
        principal=_investigator(),
        resource_type="knowledge-graph.nonexistent",
        action="read",
        expected_outcome="deny",
    ),
    AuthorizationScenario(
        name="known resource type with an unsupported action is denied by default",
        principal=_registered_service(),
        resource_type="knowledge-graph.entity",
        action="write",
        expected_outcome="deny",
    ),
]


def test_each_scenario_individually_via_assert_scenario():
    pep = _pep()
    for scenario in _SCENARIOS:
        assert_scenario(pep, scenario)


def test_all_scenarios_pass_as_a_batch_via_run_scenarios():
    failures = run_scenarios(_pep(), _SCENARIOS)
    assert failures == [], failures


def test_harness_reports_a_regression_if_policy_changes_unexpectedly():
    """Demonstrates the harness's value: an expectation that does not hold is
    surfaced as an actionable failure message rather than passing silently."""
    wrong = AuthorizationScenario(
        name="baseline platform-user wrongly expected to be allowed",
        principal=_baseline_platform_user(),
        resource_type="knowledge-graph.entity",
        action="read",
        expected_outcome="allow",
    )
    failures = run_scenarios(_pep(), [wrong])
    assert len(failures) == 1
    assert "dev.someone" in failures[0]


def test_missing_policy_file_denies_every_previously_allowed_scenario():
    """A missing policy configuration is `load_policy_config`'s own
    safe-default: an empty ruleset, which `PolicyEngine` evaluates as
    default-deny (ADR-025 §12's documented fail-closed operational
    sharp edge). Every scenario that is normally allowed becomes denied."""
    missing_path = _POLICY_CONFIG_PATH.parent / "does-not-exist.yaml"
    assert not missing_path.exists()
    pep = LocalPolicyEnforcementPoint(load_policy_config(missing_path))
    allow_scenarios = [s for s in _SCENARIOS if s.expected_outcome == "allow"]
    assert allow_scenarios, "expected at least one normally-allowed scenario to check"
    for scenario in allow_scenarios:
        decision = pep.authorize(
            AuthorizationRequest(
                principal=scenario.principal,
                resource_type=scenario.resource_type,
                action=scenario.action,
            )
        )
        assert (
            decision.outcome == "deny"
        ), f"{scenario.name} unexpectedly allowed with an empty (missing-file) policy"
