from __future__ import annotations

import pytest
from emg_auth_client import AuthorizationRequest, Decision
from emg_policy_engine.pep import LocalPolicyEnforcementPoint
from emg_policy_engine.rules import PolicyConfig, PolicyRule


class MalformedPrincipal:
    """Deliberately malformed runtime input for principal protocol testing."""

    def __init__(self, roles: list[str]) -> None:
        self.roles = roles
        # Intentionally missing 'attributes' field required by Principal


@pytest.fixture
def pep() -> LocalPolicyEnforcementPoint:
    config = PolicyConfig(
        rules=[
            PolicyRule(
                rule_id="test-rule",
                resource_type="resource",
                action="read",
                effect="allow",
                required_roles=["admin"],
                required_attributes={"clearance": ["secret"]},
            ),
        ]
    )
    return LocalPolicyEnforcementPoint(config)


def test_pep_handles_malformed_principal_gracefully(
    pep: LocalPolicyEnforcementPoint,
) -> None:
    """
    Verifies that missing fields in a principal protocol implementation
    do not crash the PEP engine but result in a managed 'deny' decision.
    """
    malformed_principal = MalformedPrincipal(roles=["admin"])

    # Cast to Any to bypass type checking for deliberately malformed input
    # used to verify runtime robustness.
    request = AuthorizationRequest(
        principal=malformed_principal,  # type: ignore[arg-type]
        resource_type="resource",
        action="read",
    )

    decision: Decision = pep.authorize(request)

    assert decision.outcome == "deny"
    assert "no policy rule's conditions were satisfied" in decision.reason
    assert decision.policy_id is None
