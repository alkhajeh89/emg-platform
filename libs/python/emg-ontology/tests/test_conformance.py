"""Conformance validator tests (FEAT-05-1, TASK-05-3): the "an ontology
conformance test rejects a non-conforming write" acceptance criterion, one
required rejection category at a time, plus the accept paths."""

from __future__ import annotations

import pytest
from emg_common_types import Classification
from emg_ontology import (
    OntologyConformanceError,
    Person,
    assert_entity_conformant,
    assert_relationship_conformant,
    new_entity_id,
    validate_entity,
    validate_relationship,
)
from emg_ontology.conformance import (
    CODE_CARDINALITY_VIOLATION,
    CODE_CLASSIFICATION_DOMINANCE,
    CODE_DANGLING_ENDPOINT,
    CODE_EXTRA_FIELD,
    CODE_INVALID_EFFECTIVE_DATES,
    CODE_INVALID_SOURCE_TYPE,
    CODE_INVALID_TARGET_TYPE,
    CODE_MISSING_CLASSIFICATION,
    CODE_MISSING_PROVENANCE,
    CODE_MISSING_TRUST_SCORE,
    CODE_SELF_LOOP_PROHIBITED,
    CODE_TRUST_SCORE_OUT_OF_RANGE,
    CODE_UNKNOWN_ENTITY_TYPE,
    CODE_UNKNOWN_RELATIONSHIP_TYPE,
)


def _codes(report) -> set[str]:
    return {e.code for e in report.errors}


# --- entity acceptance -----------------------------------------------------


def test_valid_entity_payload_accepted(entity_payload) -> None:
    assert validate_entity(entity_payload("Person")).ok
    assert validate_entity(entity_payload("Risk")).ok


def test_constructed_model_is_accepted(prov, now) -> None:
    p = Person(
        entity_id=new_entity_id(),
        classification="INTERNAL",
        trust_score=0.5,
        provenance_reference=prov,
        owner="bu",
        effective_from=now,
    )
    assert validate_entity(p).ok


# --- entity rejections -----------------------------------------------------


def test_unknown_entity_type_rejected(entity_payload) -> None:
    report = validate_entity(entity_payload("Dragon"))
    assert not report.ok and CODE_UNKNOWN_ENTITY_TYPE in _codes(report)


def test_missing_classification_rejected(entity_payload) -> None:
    payload = entity_payload("Person")
    del payload["classification"]
    assert CODE_MISSING_CLASSIFICATION in _codes(validate_entity(payload))


def test_missing_trust_score_rejected(entity_payload) -> None:
    payload = entity_payload("Person")
    del payload["trust_score"]
    assert CODE_MISSING_TRUST_SCORE in _codes(validate_entity(payload))


def test_missing_provenance_rejected(entity_payload) -> None:
    payload = entity_payload("Person")
    del payload["provenance_reference"]
    assert CODE_MISSING_PROVENANCE in _codes(validate_entity(payload))


@pytest.mark.parametrize("bad", [-0.1, 1.1, 5.0])
def test_trust_score_out_of_range_rejected(entity_payload, bad) -> None:
    assert CODE_TRUST_SCORE_OUT_OF_RANGE in _codes(
        validate_entity(entity_payload("Person", trust_score=bad))
    )


def test_invalid_lifecycle_rejected(entity_payload) -> None:
    report = validate_entity(entity_payload("Person", lifecycle_status="floating"))
    assert not report.ok


def test_invalid_effective_dates_rejected(entity_payload) -> None:
    payload = entity_payload(
        "Person",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-01-01T00:00:00Z",
    )
    assert CODE_INVALID_EFFECTIVE_DATES in _codes(validate_entity(payload))


def test_mass_assignment_rejected(entity_payload) -> None:
    report = validate_entity(entity_payload("Person", is_admin=True, secret_backdoor="x"))
    assert CODE_EXTRA_FIELD in _codes(report)


# --- relationship acceptance -----------------------------------------------


def test_valid_relationship_accepted(relationship_payload) -> None:
    assert validate_relationship(relationship_payload("HOLDS")).ok


# --- relationship rejections -----------------------------------------------


def test_unknown_relationship_type_rejected(relationship_payload) -> None:
    report = validate_relationship(relationship_payload("BEFRIENDS"))
    assert CODE_UNKNOWN_RELATIONSHIP_TYPE in _codes(report)


def test_invalid_source_type_rejected(relationship_payload) -> None:
    report = validate_relationship(relationship_payload("HOLDS", from_entity_type="System"))
    assert CODE_INVALID_SOURCE_TYPE in _codes(report)


def test_invalid_target_type_rejected(relationship_payload) -> None:
    report = validate_relationship(relationship_payload("HOLDS", to_entity_type="Organization"))
    assert CODE_INVALID_TARGET_TYPE in _codes(report)


def test_self_loop_rejected(relationship_payload) -> None:
    report = validate_relationship(
        relationship_payload(
            "MITIGATED_BY",
            from_entity_type="Risk",
            to_entity_type="Control",
            from_entity_id="x",
            to_entity_id="x",
        )
    )
    assert CODE_SELF_LOOP_PROHIBITED in _codes(report)


def test_dangling_endpoint_rejected(relationship_payload) -> None:
    report = validate_relationship(
        relationship_payload("HOLDS", from_entity_id="p-1", to_entity_id="ro-missing"),
        known_entity_ids={"p-1"},
    )
    assert CODE_DANGLING_ENDPOINT in _codes(report)


def test_no_dangling_when_both_endpoints_known(relationship_payload) -> None:
    report = validate_relationship(
        relationship_payload("HOLDS", from_entity_id="p-1", to_entity_id="ro-1"),
        known_entity_ids={"p-1", "ro-1"},
    )
    assert report.ok


def test_classification_dominance_rejected(relationship_payload) -> None:
    # Edge is INTERNAL but an endpoint is SECRET.
    report = validate_relationship(
        relationship_payload("HOLDS", classification="INTERNAL"),
        from_classification=Classification.SECRET,
    )
    assert CODE_CLASSIFICATION_DOMINANCE in _codes(report)


def test_classification_dominance_ok_when_edge_dominates(relationship_payload) -> None:
    report = validate_relationship(
        relationship_payload("HOLDS", classification="SECRET"),
        from_classification=Classification.INTERNAL,
        to_classification=Classification.SECRET,
    )
    assert report.ok


def test_cardinality_violation_rejected(relationship_payload) -> None:
    # OWNED_BY is N:1 — a source owned by a *different* business unit already.
    report = validate_relationship(
        relationship_payload(
            "OWNED_BY",
            from_entity_id="p-1",
            from_entity_type="Person",
            to_entity_id="bu-2",
            to_entity_type="BusinessUnit",
        ),
        existing_edges=[("p-1", "bu-1")],
    )
    assert CODE_CARDINALITY_VIOLATION in _codes(report)


def test_cardinality_ok_when_same_target(relationship_payload) -> None:
    report = validate_relationship(
        relationship_payload(
            "OWNED_BY",
            from_entity_id="p-1",
            from_entity_type="Person",
            to_entity_id="bu-1",
            to_entity_type="BusinessUnit",
        ),
        existing_edges=[("p-1", "bu-1")],
    )
    assert report.ok


# --- raising helpers --------------------------------------------------------


def test_assert_entity_raises_typed_error(entity_payload) -> None:
    with pytest.raises(OntologyConformanceError) as exc:
        assert_entity_conformant(entity_payload("Dragon"))
    assert exc.value.error_code == CODE_UNKNOWN_ENTITY_TYPE
    assert exc.value.errors  # typed machine-readable errors present


def test_assert_relationship_raises_typed_error(relationship_payload) -> None:
    with pytest.raises(OntologyConformanceError):
        assert_relationship_conformant(relationship_payload("HOLDS", from_entity_type="System"))


def test_assert_conformant_passes_silently(entity_payload) -> None:
    assert assert_entity_conformant(entity_payload("Person")) is None
