"""Relationship catalog + model tests (FEAT-05-1): catalog shape, endpoint
compatibility, the envelope on the Relationship model, and effective dating."""

from __future__ import annotations

import pytest
from emg_ontology import (
    RELATIONSHIP_CATALOG,
    Cardinality,
    Direction,
    Mutability,
    Relationship,
    is_known_relationship_type,
)
from pydantic import ValidationError

APPROVED_TYPES = {
    "HOLDS",
    "OWNED_BY",
    "MITIGATED_BY",
    "GOVERNS",
    "REQUIRES",
    "DERIVED_FROM",
    "REFERENCES",
    "IMPACTS",
}


def test_catalog_contains_exactly_the_approved_types() -> None:
    assert set(RELATIONSHIP_CATALOG) == APPROVED_TYPES


@pytest.mark.parametrize("rtype", sorted(APPROVED_TYPES))
def test_every_rule_is_fully_specified(rtype) -> None:
    rule = RELATIONSHIP_CATALOG[rtype]
    assert rule.source_types and rule.target_types
    assert isinstance(rule.cardinality, Cardinality)
    assert isinstance(rule.mutability, Mutability)
    assert rule.direction is Direction.DIRECTED
    assert isinstance(rule.self_loop_allowed, bool)


def test_expected_endpoint_shapes() -> None:
    assert RELATIONSHIP_CATALOG["HOLDS"].source_types == frozenset({"Person"})
    assert RELATIONSHIP_CATALOG["HOLDS"].target_types == frozenset({"Role"})
    assert "BusinessUnit" in RELATIONSHIP_CATALOG["OWNED_BY"].target_types
    assert RELATIONSHIP_CATALOG["MITIGATED_BY"].source_types == frozenset({"Risk"})
    assert RELATIONSHIP_CATALOG["REQUIRES"].source_types == frozenset({"Regulation"})
    assert RELATIONSHIP_CATALOG["REFERENCES"].target_types == frozenset({"Evidence"})


def test_is_known_relationship_type() -> None:
    assert is_known_relationship_type("HOLDS")
    assert not is_known_relationship_type("BEFRIENDS")


def test_relationship_model_requires_envelope(prov, now) -> None:
    with pytest.raises(ValidationError):
        Relationship(
            relationship_id="r",
            relationship_type="HOLDS",
            from_entity_id="p",
            from_entity_type="Person",
            to_entity_id="ro",
            to_entity_type="Role",
            # missing classification + provenance_reference + effective_from
        )


def test_relationship_is_frozen_and_forbids_extra(prov, now) -> None:
    rel = Relationship(
        relationship_id="r",
        relationship_type="HOLDS",
        from_entity_id="p",
        from_entity_type="Person",
        to_entity_id="ro",
        to_entity_type="Role",
        classification="INTERNAL",
        provenance_reference=prov,
        effective_from=now,
    )
    with pytest.raises(ValidationError):
        rel.classification = "SECRET"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Relationship(
            relationship_id="r",
            relationship_type="HOLDS",
            from_entity_id="p",
            from_entity_type="Person",
            to_entity_id="ro",
            to_entity_type="Role",
            classification="INTERNAL",
            provenance_reference=prov,
            effective_from=now,
            sneaky="x",  # type: ignore[call-arg]
        )
