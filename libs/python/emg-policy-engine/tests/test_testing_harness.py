"""Authorization testing harness meta-tests (FEAT-03-4).

Tests the harness itself: it must pass a correct scenario silently, fail an
incorrect one with an actionable message, and aggregate a batch correctly.
The harness is exercised against a real LocalPolicyEnforcementPoint over a
small in-test PolicyConfig (no file I/O, no HTTP).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from emg_auth_client import Principal
from emg_policy_engine import (
    AuthorizationScenario,
    LocalPolicyEnforcementPoint,
    PolicyConfig,
    PolicyRule,
    assert_scenario,
    run_scenarios,
)


@dataclass(frozen=True)
class _FakeServicePrincipal:
    client_id: str
    service_name: str
    roles: tuple[str, ...]
    scopes: tuple[str, ...]


def _pep() -> LocalPolicyEnforcementPoint:
    rules = [
        PolicyRule(
            rule_id="diag-read-human",
            resource_type="identity.diagnostics",
            action="read",
            effect="allow",
            required_roles=["platform-user"],
            required_attributes={
                "classification_clearance": ["INTERNAL", "CONFIDENTIAL", "SECRET"]
            },
        ),
        PolicyRule(
            rule_id="diag-read-service",
            resource_type="identity.diagnostics",
            action="read",
            effect="allow",
            required_roles=["svc-identity"],
            required_scopes=["svc-identity"],
        ),
    ]
    return LocalPolicyEnforcementPoint(PolicyConfig(rules=rules))


def _cleared_user() -> Principal:
    return Principal(
        subject="dev.user",
        roles=("platform-user",),
        attributes={"classification_clearance": "INTERNAL"},
    )


def test_assert_scenario_passes_a_correct_allow_scenario():
    scenario = AuthorizationScenario(
        name="cleared human may read diagnostics",
        principal=_cleared_user(),
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="allow",
        expected_policy_id="diag-read-human",
    )
    assert_scenario(_pep(), scenario)  # must not raise


def test_assert_scenario_passes_a_correct_deny_scenario():
    scenario = AuthorizationScenario(
        name="unknown action is denied by default",
        principal=_cleared_user(),
        resource_type="identity.diagnostics",
        action="delete",
        expected_outcome="deny",
    )
    assert_scenario(_pep(), scenario)  # must not raise


def test_assert_scenario_raises_on_wrong_expected_outcome():
    scenario = AuthorizationScenario(
        name="wrongly expects deny for a cleared user",
        principal=_cleared_user(),
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="deny",
    )
    with pytest.raises(AssertionError) as excinfo:
        assert_scenario(_pep(), scenario)
    message = str(excinfo.value)
    assert "dev.user" in message
    assert "identity.diagnostics" in message
    assert "read" in message


def test_assert_scenario_raises_on_wrong_expected_policy_id():
    scenario = AuthorizationScenario(
        name="right outcome, wrong rule",
        principal=_cleared_user(),
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="allow",
        expected_policy_id="some-other-rule",
    )
    with pytest.raises(AssertionError) as excinfo:
        assert_scenario(_pep(), scenario)
    assert "some-other-rule" in str(excinfo.value)


def test_assert_scenario_works_for_service_principal():
    service = _FakeServicePrincipal(
        client_id="emg-svc-identity",
        service_name="identity",
        roles=("service-account", "svc-identity"),
        scopes=("svc-identity",),
    )
    scenario = AuthorizationScenario(
        name="registered service may read diagnostics",
        principal=service,
        resource_type="identity.diagnostics",
        action="read",
        expected_outcome="allow",
        expected_policy_id="diag-read-service",
    )
    assert_scenario(_pep(), scenario)  # must not raise


def test_run_scenarios_returns_empty_list_when_all_pass():
    scenarios = [
        AuthorizationScenario(
            name="cleared human allowed",
            principal=_cleared_user(),
            resource_type="identity.diagnostics",
            action="read",
            expected_outcome="allow",
        ),
        AuthorizationScenario(
            name="unknown action denied",
            principal=_cleared_user(),
            resource_type="identity.diagnostics",
            action="delete",
            expected_outcome="deny",
        ),
    ]
    assert run_scenarios(_pep(), scenarios) == []


def test_run_scenarios_collects_only_the_failing_messages():
    scenarios = [
        AuthorizationScenario(
            name="passing scenario",
            principal=_cleared_user(),
            resource_type="identity.diagnostics",
            action="read",
            expected_outcome="allow",
        ),
        AuthorizationScenario(
            name="failing scenario",
            principal=_cleared_user(),
            resource_type="identity.diagnostics",
            action="read",
            expected_outcome="deny",
        ),
    ]
    failures = run_scenarios(_pep(), scenarios)
    assert len(failures) == 1
    assert "failing scenario" in failures[0]
