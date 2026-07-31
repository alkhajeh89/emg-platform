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

from .roles import is_known_role
from .rules import PolicyConfig

_log = logging.getLogger("emg.policy_engine")


class PolicyConfigurationError(ValueError):
    """Raised when a structurally valid policy is semantically unsafe."""


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
    valid). Never raises — callers decide how to surface problems.

    All checks here are *advisory*: they help operators catch likely
    mistakes, but a returned problem does not block `load_policy_config`
    (only a malformed file, raising `pydantic.ValidationError`, does). This
    includes the Sprint 5 unknown-role check (FEAT-03-3): a `required_roles`
    value not present in the RBAC baseline catalog (`roles.ROLE_CATALOG`) is
    surfaced as a problem string, not enforced — see
    `docs/engineering/sprint-5-design.md` and `security-limitations.md`.
    """
    errors: list[str] = []
    seen_rule_ids: set[str] = set()

    for rule in config.rules:
        if rule.rule_id in seen_rule_ids:
            errors.append(f"Duplicate rule_id '{rule.rule_id}'")
        seen_rule_ids.add(rule.rule_id)

        if (
            not rule.required_roles
            and not rule.required_attributes
            and not rule.required_scopes
            and not rule.required_resource_attributes
        ):
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

        # ADR-026 Revision 2, Amendment 1: required_resource_attributes is
        # symmetric with required_attributes — the same empty-allow-list
        # mistake is just as possible (and just as unsatisfiable) on the
        # resource side.
        for attribute_name, allowed_values in rule.required_resource_attributes.items():
            if not allowed_values:
                errors.append(
                    f"Rule '{rule.rule_id}' required_resource_attributes['{attribute_name}'] "
                    "has an empty allow-list, which can never be satisfied"
                )

        # FEAT-03-3 (advisory): flag roles not present in the RBAC baseline
        # catalog. Does not block loading — a typo'd role is a warning, not a
        # hard failure (documented known limitation).
        for role in rule.required_roles:
            if not is_known_role(role):
                errors.append(
                    f"Rule '{rule.rule_id}' required_roles references "
                    f"'{role}', which is not in the RBAC baseline role "
                    "catalog (emg_policy_engine.roles.ROLE_CATALOG)"
                )

    return errors


def load_validated_policy_config(path: Path) -> PolicyConfig:
    """Load policy data and reject every semantic validation problem."""

    config = load_policy_config(path)
    problems = validate_policy_config(config)
    if problems:
        raise PolicyConfigurationError("invalid policy configuration: " + "; ".join(problems))
    return config
