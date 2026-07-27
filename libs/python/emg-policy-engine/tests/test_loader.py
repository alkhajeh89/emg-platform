from __future__ import annotations

from pathlib import Path

import pytest
from emg_auth_client import AuthorizationRequest, Principal
from emg_policy_engine import default_policy_config, load_policy_config, validate_policy_config
from emg_policy_engine.engine import PolicyEngine
from emg_policy_engine.rules import PolicyConfig, PolicyRule
from pydantic import ValidationError


def test_load_policy_config_missing_file_falls_back_to_default(tmp_path: Path):
    """Testing requirement (mirrors Sprint 3's federation config): safe
    handling of a missing policy configuration file — never raises."""
    missing = tmp_path / "does-not-exist.yaml"
    config = load_policy_config(missing)
    assert config == default_policy_config()
    assert config.rules == []


def test_load_policy_config_reads_a_real_file(tmp_path: Path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
rules:
  - rule_id: diag-read
    resource_type: identity.diagnostics
    action: read
    effect: allow
    required_roles: [platform-user]
    required_attributes:
      classification_clearance: [INTERNAL, CONFIDENTIAL, SECRET]
"""
    )
    config = load_policy_config(policy_path)
    assert len(config.rules) == 1
    assert config.rules[0].rule_id == "diag-read"


def test_load_policy_config_malformed_file_raises():
    """A malformed *existing* file is a hard error — fail-closed on bad
    configuration, distinct from a missing file (which is safe)."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as fh:
        fh.write("rules:\n  - rule_id: 123\n    resource_type: 1\n    action: []\n")
        path = Path(fh.name)

    with pytest.raises(ValidationError):
        load_policy_config(path)


def test_validate_default_config_has_no_problems():
    assert validate_policy_config(default_policy_config()) == []


def test_validate_rejects_duplicate_rule_ids():
    rule = PolicyRule(
        rule_id="dup", resource_type="x", action="read", required_roles=["platform-user"]
    )
    config = PolicyConfig(rules=[rule, rule])
    problems = validate_policy_config(config)
    assert any("Duplicate rule_id" in problem for problem in problems)


def test_validate_rejects_rule_with_no_conditions():
    rule = PolicyRule(rule_id="wide-open", resource_type="x", action="read")
    config = PolicyConfig(rules=[rule])
    problems = validate_policy_config(config)
    assert any("no conditions at all" in problem for problem in problems)


def test_validate_rejects_empty_attribute_allow_list():
    rule = PolicyRule(
        rule_id="broken",
        resource_type="x",
        action="read",
        required_attributes={"classification_clearance": []},
    )
    config = PolicyConfig(rules=[rule])
    problems = validate_policy_config(config)
    assert any("empty allow-list" in problem for problem in problems)


# --- Sprint 5 (FEAT-03-3): advisory unknown-role validation ----------------


def test_validate_flags_a_role_not_in_the_baseline_catalog():
    """An advisory problem is produced for a required_role not present in
    ROLE_CATALOG — but note load_policy_config still would not raise on it
    (see the advisory-only test below)."""
    rule = PolicyRule(
        rule_id="typo-role",
        resource_type="identity.diagnostics",
        action="read",
        required_roles=["platfrom-user"],  # deliberate typo
    )
    problems = validate_policy_config(PolicyConfig(rules=[rule]))
    assert any(
        "not in the RBAC baseline role catalog" in problem and "platfrom-user" in problem
        for problem in problems
    )


def test_validate_accepts_known_baseline_roles_without_role_problems():
    rule = PolicyRule(
        rule_id="known-roles",
        resource_type="identity.diagnostics",
        action="read",
        required_roles=["platform-user", "svc-identity"],
    )
    problems = validate_policy_config(PolicyConfig(rules=[rule]))
    assert not any("RBAC baseline role catalog" in problem for problem in problems)


def test_unknown_role_is_advisory_only_and_does_not_block_loading(tmp_path: Path):
    """A policy file that references an unknown role still loads successfully
    (default-deny ABAC is unaffected). The unknown role is surfaced only via
    validate_policy_config — a documented known limitation."""
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        """
rules:
  - rule_id: unknown-role-rule
    resource_type: identity.diagnostics
    action: read
    effect: allow
    required_roles: [not-a-real-role]
"""
    )
    config = load_policy_config(policy_path)  # must not raise
    assert len(config.rules) == 1
    problems = validate_policy_config(config)
    assert any("not-a-real-role" in problem for problem in problems)


def test_example_policy_config_references_only_catalogued_roles():
    """The shipped example config must not itself trip the advisory check —
    every role it names is in the baseline catalog."""
    example = (
        Path(__file__).resolve().parents[4]
        / "services"
        / "identity"
        / "config"
        / "policy.example.yaml"
    )
    config = load_policy_config(example)
    role_problems = [
        problem
        for problem in validate_policy_config(config)
        if "RBAC baseline role catalog" in problem
    ]
    assert role_problems == []


# --- ADR-026 Revision 2 (Amendment 1, Group D6): Knowledge Graph example ---
# policy classification-enforcement rules (required_resource_attributes).


def _kg_example_policy_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "services"
        / "knowledge-graph"
        / "config"
        / "policy.example.yaml"
    )


def test_kg_example_policy_config_loads_and_has_no_advisory_problems():
    """The shipped Knowledge Graph example config (ADR-025 Group C4 allow
    rules, ADR-026 Revision 2 Group D6 classification deny rules, and
    ADR-027 Revision 3 Stage 2 mutation rules) must load without error and
    trip no advisory validation problem — no unknown roles, no rule with an
    empty allow-list, no rule with zero conditions at all
    (required_resource_attributes now counts as a condition)."""
    config = load_policy_config(_kg_example_policy_path())
    # 20 read rules + 15 mutation allows + 33 mutation classification denies.
    assert len(config.rules) == 68
    assert validate_policy_config(config) == []


def test_kg_example_policy_config_classification_dominance_via_real_engine():
    """Loads the real shipped file and proves, via `PolicyEngine`, that the
    Group D6 deny rules correctly gate classification while leaving the
    existing ADR-025 operation-level allow rules unaffected."""
    config = load_policy_config(_kg_example_policy_path())
    engine = PolicyEngine(config)

    investigator = Principal(
        subject="dev.investigator",
        roles=("platform-user", "investigator"),
        attributes={"classification_clearance": "INTERNAL"},
    )

    # ADR-025's per-request operation-level check: empty resource_attributes
    # -- unaffected by the new deny rules, still allowed.
    operation_level = engine.evaluate(
        AuthorizationRequest(
            principal=investigator, resource_type="knowledge-graph.entity", action="read"
        )
    )
    assert operation_level.outcome == "allow"
    assert operation_level.policy_id == "kg-entity-read"

    # An INTERNAL-cleared caller may see an INTERNAL-classified entity.
    allowed = engine.evaluate(
        AuthorizationRequest(
            principal=investigator,
            resource_type="knowledge-graph.entity",
            action="read",
            resource_attributes={"classification": "INTERNAL"},
        )
    )
    assert allowed.outcome == "allow"
    assert allowed.policy_id == "kg-entity-read"

    # The same caller may not see a SECRET-classified entity.
    denied = engine.evaluate(
        AuthorizationRequest(
            principal=investigator,
            resource_type="knowledge-graph.entity",
            action="read",
            resource_attributes={"classification": "SECRET"},
        )
    )
    assert denied.outcome == "deny"
    assert denied.policy_id == "kg-entity-deny-internal-clearance"

    # A caller resolved to UNCLASSIFIED (ADR-026 Revision 2 §8.4's default
    # for an unresolved clearance — applied explicitly by each service's
    # `_extract_attributes`, e.g.
    # `emg_knowledge_graph_api.authn._extract_attributes`, not by the engine
    # itself; see that function's docstring for why) cannot see even the
    # default INTERNAL classification most Knowledge Graph objects carry.
    uncleared = Principal(
        subject="dev.uncleared",
        roles=("platform-user", "investigator"),
        attributes={"classification_clearance": "UNCLASSIFIED"},
    )
    denied_uncleared = engine.evaluate(
        AuthorizationRequest(
            principal=uncleared,
            resource_type="knowledge-graph.edge",
            action="read",
            resource_attributes={"classification": "INTERNAL"},
        )
    )
    assert denied_uncleared.outcome == "deny"
    assert denied_uncleared.policy_id == "kg-edge-deny-unclassified-clearance"
