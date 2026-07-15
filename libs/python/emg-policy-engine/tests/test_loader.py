from __future__ import annotations

from pathlib import Path

import pytest
from emg_policy_engine import default_policy_config, load_policy_config, validate_policy_config
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
    policy_path.write_text("""
rules:
  - rule_id: diag-read
    resource_type: identity.diagnostics
    action: read
    effect: allow
    required_roles: [platform-user]
    required_attributes:
      classification_clearance: [INTERNAL, CONFIDENTIAL, SECRET]
""")
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
