"""Authorization testing harness (FEAT-03-4).

A small, reusable, declarative toolkit for positive/negative authorization
testing against any `PolicyEnforcementPoint`. Deliberately minimal (Sprint 5
approved scope):

- no pytest runtime dependency — `assert_scenario` uses a plain `assert` and
  `run_scenarios` returns plain strings, so the harness works under pytest
  and standalone; pytest stays a dev-only dependency;
- no YAML DSL / config-file-driven scenarios — a scenario is a plain frozen
  dataclass;
- no framework machinery — a dataclass, one assertion helper, one batch
  runner. Nothing more until a real consumer proves more is needed.

The harness lives in `emg_policy_engine` so any service already depending on
this package gets it for free. Real adoption is demonstrated in
`services/identity/tests/test_authz_scenarios.py`. See
`docs/engineering/sprint-5-design.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from emg_auth_client import (
    AuthorizationRequest,
    AuthorizedIdentity,
    DecisionOutcome,
    PolicyEnforcementPoint,
    Principal,
)


@dataclass(frozen=True)
class AuthorizationScenario:
    """One declarative authorization expectation.

    `principal` is any `AuthorizedIdentity` (a human `Principal` or a
    machine `ServicePrincipalLike`). `expected_outcome` is `"allow"` or
    `"deny"`. `expected_policy_id`, if given, additionally asserts *which*
    rule produced the decision (Sprint 4 `Decision.policy_id`); leave it
    `None` to assert only the outcome.
    """

    name: str
    principal: AuthorizedIdentity
    resource_type: str
    action: str
    expected_outcome: DecisionOutcome
    expected_policy_id: str | None = None


def _subject_of(principal: AuthorizedIdentity) -> str:
    """Best-effort human-readable label for either identity kind, for
    failure messages only — never used in an authorization decision."""
    if isinstance(principal, Principal):
        return principal.subject
    return principal.client_id


def describe_scenario(scenario: AuthorizationScenario) -> str:
    """Stable one-line description of a scenario, used in failure messages
    and available to callers for their own reporting."""
    return (
        f"{scenario.name}: subject={_subject_of(scenario.principal)!r} "
        f"resource_type={scenario.resource_type!r} action={scenario.action!r} "
        f"expected={scenario.expected_outcome!r}"
    )


def check_scenario(pep: PolicyEnforcementPoint, scenario: AuthorizationScenario) -> str | None:
    """Evaluate `scenario` against `pep`. Return `None` if it matches
    expectations, or a human-readable failure message if it does not. Never
    raises for a mismatch (that is `assert_scenario`'s job) — this is the
    non-raising primitive both `assert_scenario` and `run_scenarios` build
    on.
    """
    decision = pep.authorize(
        AuthorizationRequest(
            principal=scenario.principal,
            resource_type=scenario.resource_type,
            action=scenario.action,
        )
    )

    if decision.outcome != scenario.expected_outcome:
        return (
            f"{describe_scenario(scenario)} but got outcome={decision.outcome!r} "
            f"(reason: {decision.reason})"
        )

    if (
        scenario.expected_policy_id is not None
        and decision.policy_id != scenario.expected_policy_id
    ):
        return (
            f"{describe_scenario(scenario)} with expected_policy_id="
            f"{scenario.expected_policy_id!r} but got policy_id={decision.policy_id!r}"
        )

    return None


def assert_scenario(pep: PolicyEnforcementPoint, scenario: AuthorizationScenario) -> None:
    """Assert that `pep` decides `scenario` as expected. Raises
    `AssertionError` with a message naming the subject, resource, action, and
    expected-vs-actual outcome on mismatch. Uses a plain `assert` — no pytest
    dependency."""
    failure = check_scenario(pep, scenario)
    assert failure is None, failure


def run_scenarios(pep: PolicyEnforcementPoint, scenarios: list[AuthorizationScenario]) -> list[str]:
    """Evaluate every scenario against `pep`. Return the list of failure
    messages (empty list = every scenario matched its expectation), so a
    caller can assert a whole suite is "green" in one check:

        failures = run_scenarios(pep, scenarios)
        assert not failures, failures
    """
    return [
        message
        for message in (check_scenario(pep, scenario) for scenario in scenarios)
        if message is not None
    ]
