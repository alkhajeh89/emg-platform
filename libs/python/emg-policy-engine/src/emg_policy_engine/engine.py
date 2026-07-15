"""Local ABAC evaluation (FEAT-03-2).

Pure and local: no network calls, no database, no I/O beyond what the
caller already did to build a `PolicyConfig` (see `loader.py`). Evaluation
semantics (see `docs/engineering/sprint-4-design.md` for the full
rationale):

- **Default-deny, fail-closed.** Zero matching rules -> deny. This is not
  configurable (there is deliberately no "default effect" field on
  `PolicyConfig`).
- **Deny-overrides.** If both an `allow` and a `deny` rule match and are
  satisfied, `deny` wins.
- **Human (`Principal`) conditions:** `required_roles` (any-of) AND
  `required_attributes` (all-of, each attribute's value must be in its
  allow-list).
- **Machine (`ServicePrincipalLike`) conditions:** `required_roles` (any-of,
  against the service's registered roles) AND `required_scopes` (any-of).
  A rule with any `required_attributes` can never be satisfied by a service
  principal — machine identities carry no attributes by Sprint 3 design.
"""

from __future__ import annotations

from emg_auth_client import (
    AuthorizationRequest,
    AuthorizedIdentity,
    Decision,
    Principal,
    ServicePrincipalLike,
)

from .rules import PolicyConfig, PolicyRule


class PolicyEngine:
    """Evaluates `AuthorizationRequest`s against a fixed `PolicyConfig`."""

    def __init__(self, config: PolicyConfig) -> None:
        self._config = config

    def evaluate(self, request: AuthorizationRequest) -> Decision:
        matching = [
            rule
            for rule in self._config.rules
            if rule.resource_type == request.resource_type and rule.action == request.action
        ]
        if not matching:
            return Decision(
                outcome="deny",
                reason=(
                    f"no policy rule defined for resource_type={request.resource_type!r} "
                    f"action={request.action!r} (default-deny)"
                ),
            )

        satisfied = [
            rule for rule in matching if self._conditions_satisfied(rule, request.principal)
        ]

        deny_matches = [rule for rule in satisfied if rule.effect == "deny"]
        if deny_matches:
            rule = deny_matches[0]
            return Decision(outcome="deny", reason=self._describe(rule), policy_id=rule.rule_id)

        allow_matches = [rule for rule in satisfied if rule.effect == "allow"]
        if allow_matches:
            rule = allow_matches[0]
            return Decision(outcome="allow", reason=self._describe(rule), policy_id=rule.rule_id)

        return Decision(
            outcome="deny",
            reason=(
                f"no policy rule's conditions were satisfied for "
                f"resource_type={request.resource_type!r} action={request.action!r} "
                "(default-deny)"
            ),
        )

    @staticmethod
    def _describe(rule: PolicyRule) -> str:
        suffix = f": {rule.description}" if rule.description else ""
        return f"matched policy rule '{rule.rule_id}'{suffix}"

    def _conditions_satisfied(self, rule: PolicyRule, principal: AuthorizedIdentity) -> bool:
        if isinstance(principal, Principal):
            return self._human_conditions_satisfied(rule, principal)
        return self._service_conditions_satisfied(rule, principal)

    @staticmethod
    def _human_conditions_satisfied(rule: PolicyRule, principal: Principal) -> bool:
        if rule.required_roles and not any(role in principal.roles for role in rule.required_roles):
            return False
        for attribute_name, allowed_values in rule.required_attributes.items():
            if principal.attributes.get(attribute_name) not in allowed_values:
                return False
        return True

    @staticmethod
    def _service_conditions_satisfied(rule: PolicyRule, principal: ServicePrincipalLike) -> bool:
        # A rule requiring attributes can never be satisfied by a service
        # principal (no `attributes` field on ServicePrincipalLike).
        if rule.required_attributes:
            return False
        if rule.required_roles and not any(role in principal.roles for role in rule.required_roles):
            return False
        return not (
            rule.required_scopes
            and not any(scope in principal.scopes for scope in rule.required_scopes)
        )
