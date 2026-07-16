"""RBAC baseline role catalog (FEAT-03-3).

A governed, versioned *vocabulary* of the platform's roles — **not** a second
authorization or enforcement mechanism. There is exactly one authorization
mechanism in EMG™: the ABAC `PolicyEngine` (`engine.py`), which evaluates
`required_roles`/`required_attributes`/`required_scopes` conditions. This
catalog is the authoritative list of role names those `required_roles`
conditions are expected to draw from; it deliberately has:

- no permission matrix (role -> allowed actions/resources),
- no role hierarchy or inheritance,
- no `evaluate()`, decision, or enforcement method of any kind.

Its only programmatic consumer is `loader.validate_policy_config`, which uses
it to advisorily flag a policy rule that references a role not in this
catalog (see that function and `docs/engineering/sprint-5-design.md`).

Every role here is one already proven to exist in the repository and the
Keycloak realm seed (`tools/seed-data/keycloak/emg-realm.json`); no role is
invented by this catalog. `RoleDefinition` mirrors the frozen-dataclass shape
of `services/identity`'s `ServiceRegistryEntry` (Sprint 3) for consistency,
but this catalog is a distinct concern from that service's `SERVICE_REGISTRY`
(which registers service *identities* for token validation) and does not
modify it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RoleCategory = Literal["human", "service"]


@dataclass(frozen=True)
class RoleDefinition:
    """One catalogued role. `governing_reference` names the architecture /
    sprint artifact that introduced or governs the role, so the catalog is
    self-documenting about provenance."""

    role_id: str
    category: RoleCategory
    description: str
    governing_reference: str


def _entry(
    role_id: str, category: RoleCategory, description: str, governing_reference: str
) -> RoleDefinition:
    return RoleDefinition(
        role_id=role_id,
        category=category,
        description=description,
        governing_reference=governing_reference,
    )


# The authoritative baseline role catalog. Keyed by role_id. Ordered
# human-then-service for readability; ordering carries no semantics.
ROLE_CATALOG: dict[str, RoleDefinition] = {
    "platform-user": _entry(
        "platform-user",
        "human",
        "Baseline authenticated EMG platform user.",
        "Keycloak realm seed (Sprint 2, FEAT-02-1); Module 5",
    ),
    "investigator": _entry(
        "investigator",
        "human",
        "Case investigator — Investigation Agent scope (Module 9 §5).",
        "Keycloak realm seed (Sprint 2); Module 5",
    ),
    "decision-maker": _entry(
        "decision-maker",
        "human",
        "Accountable decision-maker — Human Decision Workspace (Module 10).",
        "Keycloak realm seed (Sprint 2); Module 5",
    ),
    "knowledge-steward": _entry(
        "knowledge-steward",
        "human",
        "Knowledge Graph steward — Knowledge Authoring UI (Module 7).",
        "Keycloak realm seed (Sprint 2); Module 5",
    ),
    "service-account": _entry(
        "service-account",
        "service",
        "Baseline realm role granted to every non-human service principal.",
        "Keycloak realm seed (Sprint 3, FEAT-02-3); Module 5",
    ),
    "svc-identity": _entry(
        "svc-identity",
        "service",
        "Least-privilege role for the Identity Service's own service principal.",
        "Keycloak realm seed (Sprint 3, FEAT-02-3); Module 5",
    ),
    "svc-authorization": _entry(
        "svc-authorization",
        "service",
        "Least-privilege role for the Authorization Service's service principal.",
        "Keycloak realm seed (Sprint 3, FEAT-02-3); Module 5",
    ),
    "svc-audit": _entry(
        "svc-audit",
        "service",
        "Least-privilege role for the Audit Service's service principal.",
        "Keycloak realm seed (Sprint 3, FEAT-02-3); Module 5",
    ),
}


def is_known_role(role_id: str) -> bool:
    """True if `role_id` is a catalogued baseline role. Pure lookup — no
    authorization decision is made or implied by this function."""
    return role_id in ROLE_CATALOG


def role_ids() -> frozenset[str]:
    """The set of all catalogued role ids."""
    return frozenset(ROLE_CATALOG)
