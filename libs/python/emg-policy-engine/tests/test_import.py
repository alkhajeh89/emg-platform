from emg_policy_engine import LocalPolicyEnforcementPoint, PolicyEngine, default_policy_config


def test_default_policy_config_denies_by_default():
    """An empty ruleset is default-deny, not default-allow — the package's
    single most important safety property."""
    from emg_auth_client import AuthorizationRequest, Principal

    engine = PolicyEngine(default_policy_config())
    principal = Principal(subject="dev.investigator", roles=("platform-user",))
    decision = engine.evaluate(
        AuthorizationRequest(principal=principal, resource_type="anything", action="read")
    )
    assert decision.outcome == "deny"


def test_local_pep_implements_the_shared_protocol():
    from emg_auth_client import PolicyEnforcementPoint

    pep = LocalPolicyEnforcementPoint(default_policy_config())
    assert isinstance(pep, PolicyEnforcementPoint)
