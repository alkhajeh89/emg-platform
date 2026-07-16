"""Real adoption of the shared authorization testing harness (FEAT-03-4).

This is the proof that the Sprint 5 harness (`emg_policy_engine.testing`)
works outside its own unit tests: `services/identity` — a real service —
expresses authorization expectations against its own shipped policy
(`config/policy.example.yaml`) declaratively via `AuthorizationScenario` /
`assert_scenario` / `run_scenarios`, instead of hand-rolling engine or HTTP
assertions.

It is deliberately additive and does NOT replace `test_authz_router.py`
(Sprint 4, HTTP-level) — both suites coexist and both pass. It also uses the
service's real `ServicePrincipal` type (not a structural fake), demonstrating
the harness accepts the actual machine-identity type Sprint 3 issues.
"""

from __future__ import annotations

from pathlib import Path

from emg_auth_client import Principal
from emg_identity.service_principal import ServicePrincipal
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


def _cleared_platform_user() -> Principal:
    return Principal(
        subject="dev.investigator",
        roles=("platform-user", "investigator"),
        attributes={"classification_clearance": "INTERNAL"},
    )


def _knowledge_steward() -> Principal:
    return Principal(
        subject="dev.steward",
        roles=("platform-user", "knowledge-steward"),
        attributes={"classification_clearance": "INTERNAL"},
    )


def _identity_service_principal() -> ServicePrincipal:
    return ServicePrincipal(
        client_id="emg-svc-identity",
        service_name="identity",
        roles=("service-account", "svc-identity"),
        scopes=("svc-identity",),
    )


# Declarative scenarios against the real policy.example.yaml rules.
_SCENARIOS = [
    AuthorizationScenario(
        name="cleared platform user may read diagnostics",
        principal=_cleared_platform_user(),
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="allow",
        expected_policy_id="diagnostics-read-internal",
    ),
    AuthorizationScenario(
        name="knowledge steward is denied by deny-overrides",
        principal=_knowledge_steward(),
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="deny",
        expected_policy_id="diagnostics-read-knowledge-steward-excluded",
    ),
    AuthorizationScenario(
        name="registered identity service principal may read diagnostics",
        principal=_identity_service_principal(),
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="allow",
        expected_policy_id="diagnostics-read-service",
    ),
    AuthorizationScenario(
        name="unknown resource is denied by default",
        principal=_cleared_platform_user(),
        resource_type="identity.nonexistent",
        action="read",
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
        name="insufficiently-cleared user wrongly expected to be allowed",
        principal=Principal(subject="dev.nobody", roles=("platform-user",), attributes={}),
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="allow",
    )
    failures = run_scenarios(_pep(), [wrong])
    assert len(failures) == 1
    assert "dev.nobody" in failures[0]
