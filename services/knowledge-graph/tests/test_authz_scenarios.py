"""Policy scenarios for Knowledge Graph read and mutation authorization.

Read scenarios retain ADR-025 Group C9's real adoption of the shared
authorization harness. Mutation scenarios add ADR-027 Revision 3 Stage 2
policy-data coverage against the same real `LocalPolicyEnforcementPoint`.
No route, application hook, or alternate authorization mechanism is involved.

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


def _mutation_steward(clearance: str = "SECRET") -> Principal:
    return Principal(
        subject="dev.mutation-steward",
        roles=("platform-user", "knowledge-steward"),
        attributes={"classification_clearance": clearance},
    )


def _writer_service(clearance: str = "SECRET") -> ServicePrincipal:
    return ServicePrincipal(
        client_id="emg-svc-knowledge-writer",
        roles=("service-account", "svc-knowledge-graph-writer"),
        attributes={"classification_clearance": clearance},
    )


_ALLOWED_RESOURCE_TYPES = (
    "knowledge-graph.entity",
    "knowledge-graph.edge",
    "knowledge-graph.neighbors",
    "knowledge-graph.path",
    "knowledge-graph.history",
)

_MUTATION_ACTIONS = (
    ("knowledge-graph.entity", "create"),
    ("knowledge-graph.entity", "update"),
    ("knowledge-graph.entity", "retire"),
    ("knowledge-graph.entity", "restore"),
    ("knowledge-graph.entity", "merge"),
    ("knowledge-graph.entity", "reclassify"),
    ("knowledge-graph.entity", "bulk"),
    ("knowledge-graph.relationship", "create"),
    ("knowledge-graph.relationship", "update"),
    ("knowledge-graph.relationship", "retire"),
    ("knowledge-graph.relationship", "bulk"),
)

_SERVICE_MUTATION_ACTIONS = (
    ("knowledge-graph.entity", "create"),
    ("knowledge-graph.entity", "update"),
    ("knowledge-graph.entity", "retire"),
    ("knowledge-graph.entity", "bulk"),
    ("knowledge-graph.relationship", "create"),
    ("knowledge-graph.relationship", "update"),
    ("knowledge-graph.relationship", "retire"),
    ("knowledge-graph.relationship", "bulk"),
)

_HUMAN_ONLY_MUTATION_ACTIONS = (
    ("knowledge-graph.entity", "restore"),
    ("knowledge-graph.entity", "merge"),
    ("knowledge-graph.entity", "reclassify"),
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

_MUTATION_SCENARIOS = [
    *(
        AuthorizationScenario(
            name=f"knowledge steward may {action} {resource_type}",
            principal=_mutation_steward(),
            resource_type=resource_type,
            action=action,
            expected_outcome="allow",
        )
        for resource_type, action in _MUTATION_ACTIONS
    ),
    *(
        AuthorizationScenario(
            name=f"writer service may {action} {resource_type}",
            principal=_writer_service(),
            resource_type=resource_type,
            action=action,
            expected_outcome="allow" if action in {"create", "bulk"} else "deny",
        )
        for resource_type, action in _SERVICE_MUTATION_ACTIONS
    ),
    *(
        AuthorizationScenario(
            name=f"writer service may not {action} {resource_type}",
            principal=_writer_service(),
            resource_type=resource_type,
            action=action,
            expected_outcome="deny",
        )
        for resource_type, action in _HUMAN_ONLY_MUTATION_ACTIONS
    ),
    AuthorizationScenario(
        name="baseline platform user may not create an entity",
        principal=Principal(
            subject="dev.unprivileged",
            roles=("platform-user",),
            attributes={"classification_clearance": "SECRET"},
        ),
        resource_type="knowledge-graph.entity",
        action="create",
        expected_outcome="deny",
    ),
    AuthorizationScenario(
        name="knowledge steward without clearance fails closed",
        principal=Principal(
            subject="dev.missing-clearance",
            roles=("platform-user", "knowledge-steward"),
        ),
        resource_type="knowledge-graph.entity",
        action="create",
        expected_outcome="deny",
    ),
    AuthorizationScenario(
        name="knowledge steward with unknown clearance fails closed",
        principal=Principal(
            subject="dev.unknown-clearance",
            roles=("platform-user", "knowledge-steward"),
            attributes={"classification_clearance": "BANANA"},
        ),
        resource_type="knowledge-graph.entity",
        action="create",
        expected_outcome="deny",
    ),
    AuthorizationScenario(
        name="bare service-account role may not mutate",
        principal=ServicePrincipal(
            client_id="emg-svc-bare",
            roles=("service-account",),
            attributes={"classification_clearance": "SECRET"},
        ),
        resource_type="knowledge-graph.relationship",
        action="create",
        expected_outcome="deny",
    ),
    AuthorizationScenario(
        name="writer service without clearance fails closed",
        principal=ServicePrincipal(
            client_id="emg-svc-missing-clearance",
            roles=("service-account", "svc-knowledge-graph-writer"),
        ),
        resource_type="knowledge-graph.relationship",
        action="create",
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


def test_each_mutation_scenario_individually_via_assert_scenario():
    pep = _pep()
    for scenario in _MUTATION_SCENARIOS:
        assert_scenario(pep, scenario)


def test_all_mutation_scenarios_pass_as_a_batch_via_run_scenarios():
    failures = run_scenarios(_pep(), _MUTATION_SCENARIOS)
    assert failures == [], failures


def test_writer_service_update_and_retire_require_owner_match():
    pep = _pep()
    for resource_type, action in _SERVICE_MUTATION_ACTIONS:
        if action in {"create", "bulk"}:
            continue
        allowed = pep.authorize(
            AuthorizationRequest(
                principal=_writer_service(),
                resource_type=resource_type,
                action=action,
                resource_attributes={"owner_matches_principal": "true"},
            )
        )
        missing = pep.authorize(
            AuthorizationRequest(
                principal=_writer_service(),
                resource_type=resource_type,
                action=action,
            )
        )
        false = pep.authorize(
            AuthorizationRequest(
                principal=_writer_service(),
                resource_type=resource_type,
                action=action,
                resource_attributes={"owner_matches_principal": "false"},
            )
        )
        assert allowed.outcome == "allow"
        assert missing.outcome == "deny"
        assert false.outcome == "deny"


def test_mutation_classification_dominance_uses_deny_overrides():
    pep = _pep()
    service_owned = {
        ("knowledge-graph.entity", "update"),
        ("knowledge-graph.entity", "retire"),
        ("knowledge-graph.relationship", "update"),
        ("knowledge-graph.relationship", "retire"),
    }
    for resource_type, action in _MUTATION_ACTIONS:
        principal = (
            _writer_service("UNCLASSIFIED")
            if (resource_type, action) in service_owned
            else _mutation_steward("UNCLASSIFIED")
        )
        resource_attributes = {"classification": "INTERNAL"}
        if (resource_type, action) in service_owned:
            resource_attributes["owner_matches_principal"] = "true"
        decision = pep.authorize(
            AuthorizationRequest(
                principal=principal,
                resource_type=resource_type,
                action=action,
                resource_attributes=resource_attributes,
            )
        )
        assert decision.outcome == "deny"
        assert decision.policy_id == (
            f"kg-{resource_type.removeprefix('knowledge-graph.')}-"
            f"{action}-deny-unclassified-clearance"
        )


def test_mutation_clearance_is_evaluated_for_each_supplied_classification():
    pep = _pep()
    principal = _mutation_steward("INTERNAL")
    current = pep.authorize(
        AuthorizationRequest(
            principal=principal,
            resource_type="knowledge-graph.entity",
            action="reclassify",
            resource_attributes={"classification": "INTERNAL"},
        )
    )
    proposed = pep.authorize(
        AuthorizationRequest(
            principal=principal,
            resource_type="knowledge-graph.entity",
            action="reclassify",
            resource_attributes={"classification": "CONFIDENTIAL"},
        )
    )
    assert current.outcome == "allow"
    assert proposed.outcome == "deny"


def test_relationship_endpoint_classifications_use_the_same_policy_path():
    pep = _pep()
    principal = _mutation_steward("CONFIDENTIAL")
    relationship = pep.authorize(
        AuthorizationRequest(
            principal=principal,
            resource_type="knowledge-graph.relationship",
            action="create",
            resource_attributes={"classification": "INTERNAL"},
        )
    )
    source_endpoint = pep.authorize(
        AuthorizationRequest(
            principal=principal,
            resource_type="knowledge-graph.relationship",
            action="create",
            resource_attributes={"classification": "CONFIDENTIAL"},
        )
    )
    target_endpoint = pep.authorize(
        AuthorizationRequest(
            principal=principal,
            resource_type="knowledge-graph.relationship",
            action="create",
            resource_attributes={"classification": "SECRET"},
        )
    )
    assert relationship.outcome == "allow"
    assert source_endpoint.outcome == "allow"
    assert target_endpoint.outcome == "deny"


def test_mutation_policy_inventory_matches_adr027_matrix():
    config = load_policy_config(_POLICY_CONFIG_PATH)
    mutation_allow_rules = {
        (rule.resource_type, rule.action, rule.rule_id)
        for rule in config.rules
        if rule.effect == "allow"
        and rule.resource_type in {"knowledge-graph.entity", "knowledge-graph.relationship"}
        and rule.action != "read"
    }
    represented_operations = {
        (resource_type, action) for resource_type, action, _ in mutation_allow_rules
    }
    assert represented_operations == set(_MUTATION_ACTIONS)
    assert all(
        rule.required_attributes.get("classification_clearance")
        == ["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"]
        for rule in config.rules
        if (rule.resource_type, rule.action) in _MUTATION_ACTIONS and rule.effect == "allow"
    )


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
    allow_scenarios = [
        scenario
        for scenario in (*_SCENARIOS, *_MUTATION_SCENARIOS)
        if scenario.expected_outcome == "allow"
    ]
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
