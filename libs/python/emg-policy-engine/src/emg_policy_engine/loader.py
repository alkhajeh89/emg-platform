"""Safe policy configuration loading and validation (FEAT-03-2).

Same safety posture as Sprint 3's `emg_identity.federation.load_federation_config`:
a missing file is a normal, expected local-development/no-policy-configured
state (falls back to an empty ruleset, which `PolicyEngine` still evaluates
as default-deny — an empty policy denies everything, it does not allow
everything). A malformed *existing* file is a hard error, not silently
ignored.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .rules import PolicyConfig

_log = logging.getLogger("emg.policy_engine")


def default_policy_config() -> PolicyConfig:
    """The safe default when no policy file is present: zero rules. Because
    `PolicyEngine.evaluate()` is default-deny, this denies every request —
    never silently allows one."""
    return PolicyConfig(rules=[])


def load_policy_config(path: Path) -> PolicyConfig:
    """Load a `PolicyConfig` from `path`. Never raises for a missing file
    (logs at INFO and returns `default_policy_config()`); raises
    `pydantic.ValidationError` for a malformed file that does exist —
    fail-closed on bad configuration, not silently ignored."""
    if not path.exists():
        _log.info(
            "No policy configuration file at %s — using empty (default-deny) ruleset",
            path,
        )
        return default_policy_config()

    raw = yaml.safe_load(path.read_text()) or {}
    return PolicyConfig.model_validate(raw)


def validate_policy_config(config: PolicyConfig) -> list[str]:
    """Return a list of human-readable validation problems (empty list =
    valid). Never raises — callers decide how to surface problems."""
    errors: list[str] = []
    seen_rule_ids: set[str] = set()

    for rule in config.rules:
        if rule.rule_id in seen_rule_ids:
            errors.append(f"Duplicate rule_id '{rule.rule_id}'")
        seen_rule_ids.add(rule.rule_id)

        if not rule.required_roles and not rule.required_attributes and not rule.required_scopes:
            errors.append(
                f"Rule '{rule.rule_id}' ({rule.resource_type}/{rule.action}) has no "
                "conditions at all — it would match every principal unconditionally"
            )

        for attribute_name, allowed_values in rule.required_attributes.items():
            if not allowed_values:
                errors.append(
                    f"Rule '{rule.rule_id}' required_attributes['{attribute_name}'] "
                    "has an empty allow-list, which can never be satisfied"
                )

    return errors
