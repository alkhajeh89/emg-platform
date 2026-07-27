"""Local ABAC evaluation (FEAT-03-2; extended by ADR-026 Revision 2,
Amendments 1 and 2).

Pure and local: no network calls, no database, no I/O beyond what the
caller already did to build a `PolicyConfig` (see `loader.py`). Evaluation
semantics (see `docs/engineering/sprint-4-design.md` for the original Sprint
4 rationale, and
`docs/architecture/EMG_ADR-026_KNOWLEDGE_GRAPH_CLASSIFICATION_ENFORCEMENT_MODEL.md`
(Revision 2) §8.2/§8.4/§8.9/Appendix ADR-026A for the extension):

- **Default-deny, fail-closed.** Zero matching rules -> deny. This is not
  configurable (there is deliberately no "default effect" field on
  `PolicyConfig`). Unchanged by ADR-026 Revision 2.
- **Deny-overrides.** If both an `allow` and a `deny` rule match and are
  satisfied, `deny` wins. Unchanged by ADR-026 Revision 2.
- **Resource-attribute conditions (`required_resource_attributes`, ADR-026
  Revision 2 Amendment 1):** all-of, matched against
  `AuthorizationRequest.resource_attributes` — evaluated identically
  regardless of principal kind, *before* dispatching to the
  principal-specific checks below. A rule with no
  `required_resource_attributes` is vacuously satisfied on this axis (the
  loop over an empty dict never runs), which is exactly what preserves
  ADR-025's existing operation-level authorization rules (which never set
  this field and never populate `resource_attributes` on their request)
  byte-for-byte: this is purely additive to the matching logic, never a
  removal or narrowing of it.
- **Human (`Principal`) conditions:** `required_roles` (any-of) AND
  `required_attributes` (all-of, each attribute's value must be in its
  allow-list, matched against `principal.attributes`).
- **Machine (`ServicePrincipalLike`) conditions:** `required_roles` (any-of,
  against the service's registered roles) AND `required_scopes` (any-of) AND
  (ADR-026 Revision 2 Amendment 2) `required_attributes` (all-of, matched
  against `principal.attributes` exactly as for a human `Principal`) — prior
  to ADR-026 Revision 2, `ServicePrincipalLike` had no `attributes` field, so
  a rule with any `required_attributes` could never be satisfied by a
  service principal; that restriction is retired now that
  `ServicePrincipalLike` carries `attributes` symmetrically with `Principal`.
  A `ServicePrincipalLike` value that structurally lacks `attributes` (e.g. a
  test double predating this extension) is treated as having an empty
  attributes mapping (`getattr(principal, "attributes", {})`) rather than
  raising — fail-closed, not a crash, consistent with this module's existing
  robustness guarantee for structurally incomplete principals (see
  `tests/test_negative_protocols.py`).
"""

from __future__ import annotations

from emg_auth_client import (
    AuthorizationRequest,
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

        satisfied = [rule for rule in matching if self._conditions_satisfied(rule, request)]

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

    def _conditions_satisfied(self, rule: PolicyRule, request: AuthorizationRequest) -> bool:
        """ADR-026 Revision 2, Amendment 1: the resource-attribute check runs
        first, uniformly for both principal kinds, before dispatching to the
        principal-specific (human vs. service) condition checks below."""
        if not self._resource_attributes_satisfied(rule, request.resource_attributes):
            return False
        principal = request.principal
        if isinstance(principal, Principal):
            return self._human_conditions_satisfied(rule, principal)
        return self._service_conditions_satisfied(rule, principal)

    @staticmethod
    def _resource_attributes_satisfied(
        rule: PolicyRule, resource_attributes: dict[str, str]
    ) -> bool:
        """ADR-026 Revision 2, Amendment 1: symmetric with
        `_human_conditions_satisfied`'s `required_attributes` loop, but
        matched against the *request's* resource-side attributes rather than
        the principal's own attributes. Evaluated once, identically, for
        both principal kinds — a resource's classification (or any other
        future resource attribute) does not depend on who is asking."""
        for attribute_name, allowed_values in rule.required_resource_attributes.items():
            if resource_attributes.get(attribute_name) not in allowed_values:
                return False
        return True

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
        if rule.required_roles and not any(role in principal.roles for role in rule.required_roles):
            return False
        if rule.required_scopes and not any(
            scope in principal.scopes for scope in rule.required_scopes
        ):
            return False
        # ADR-026 Revision 2, Amendment 2: ServicePrincipalLike now carries
        # `attributes`, symmetric with Principal.attributes — evaluated
        # identically to the human path, retiring the prior hard `return
        # False` this method used whenever `required_attributes` was
        # non-empty. `getattr(..., "attributes", {})` keeps this fail-closed
        # (not a crash) for any ServicePrincipalLike value that structurally
        # predates this field (e.g. a test double).
        principal_attributes: dict[str, str] = getattr(principal, "attributes", {})
        for attribute_name, allowed_values in rule.required_attributes.items():
            if principal_attributes.get(attribute_name) not in allowed_values:
                return False
        return True
