"""RBAC baseline role catalog tests (FEAT-03-3).

Verifies the catalog is complete against the roles actually seeded in the
Keycloak realm, internally consistent, and — critically — that it is a
*vocabulary* with no enforcement/decision surface (the Sprint 5 design
decision that the catalog must not become a second authorization mechanism).
"""

from __future__ import annotations

import json
from pathlib import Path

from emg_policy_engine import ROLE_CATALOG, RoleDefinition, is_known_role, role_ids

# The eight roles approved for Sprint 5, plus svc-knowledge-graph-writer
# (ADR-027 Revision 2 Stage 0), matching the Keycloak realm seed.
_EXPECTED_ROLE_IDS = {
    "platform-user",
    "investigator",
    "decision-maker",
    "knowledge-steward",
    "service-account",
    "svc-identity",
    "svc-authorization",
    "svc-audit",
    "svc-knowledge-graph-writer",
}

_REALM_SEED = (
    Path(__file__).resolve().parents[4] / "tools" / "seed-data" / "keycloak" / "emg-realm.json"
)


def test_catalog_contains_exactly_the_approved_roles():
    assert set(ROLE_CATALOG) == _EXPECTED_ROLE_IDS


def test_role_ids_helper_matches_catalog_keys():
    assert role_ids() == frozenset(ROLE_CATALOG)


def test_every_catalog_key_matches_its_role_id():
    for key, definition in ROLE_CATALOG.items():
        assert isinstance(definition, RoleDefinition)
        assert definition.role_id == key


def test_every_role_has_a_category_description_and_reference():
    for definition in ROLE_CATALOG.values():
        assert definition.category in ("human", "service")
        assert definition.description.strip()
        assert definition.governing_reference.strip()


def test_service_roles_are_categorised_as_service():
    for role_id in (
        "service-account",
        "svc-identity",
        "svc-authorization",
        "svc-audit",
        "svc-knowledge-graph-writer",
    ):
        assert ROLE_CATALOG[role_id].category == "service"


def test_human_roles_are_categorised_as_human():
    for role_id in ("platform-user", "investigator", "decision-maker", "knowledge-steward"):
        assert ROLE_CATALOG[role_id].category == "human"


def test_is_known_role():
    assert is_known_role("platform-user") is True
    assert is_known_role("svc-audit") is True
    assert is_known_role("nonexistent-role") is False


def test_catalog_covers_every_role_defined_in_the_keycloak_realm_seed():
    """The catalog and the realm seed must not drift: every realm role is
    catalogued and no catalogued role is absent from the realm. This is what
    keeps FEAT-03-3 grounded in roles that actually exist rather than
    invented ones."""
    realm = json.loads(_REALM_SEED.read_text())
    seeded_role_ids = {role["name"] for role in realm["roles"]["realm"]}
    assert seeded_role_ids == set(ROLE_CATALOG)


def test_catalog_has_no_enforcement_surface():
    """The catalog is a vocabulary, not an authorization mechanism: a
    RoleDefinition exposes only descriptive fields and no decision/evaluate
    method (Sprint 5 design decision)."""
    definition = ROLE_CATALOG["platform-user"]
    public_attrs = {name for name in dir(definition) if not name.startswith("_")}
    assert public_attrs == {"role_id", "category", "description", "governing_reference"}
