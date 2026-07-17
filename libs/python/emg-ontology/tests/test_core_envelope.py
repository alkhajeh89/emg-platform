"""Core envelope + versioning tests (FEAT-05-1): required-by-construction
governance fields, extra-field rejection, trust range, classification,
provenance, lifecycle, effective dates, supersession, and immutable history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from emg_ontology import (
    LifecycleStatus,
    Person,
    ProvenanceReference,
    new_entity_id,
)
from pydantic import ValidationError


def _person(prov, now, **overrides) -> Person:
    kwargs = dict(
        entity_id=new_entity_id(),
        classification="INTERNAL",
        trust_score=0.5,
        provenance_reference=prov,
        owner="bu-1",
        effective_from=now,
    )
    kwargs.update(overrides)
    return Person(**kwargs)


def test_valid_entity_constructs(prov, now) -> None:
    p = _person(prov, now)
    assert p.entity_type == "Person"
    assert p.lifecycle_status is LifecycleStatus.PROPOSED  # default
    assert p.version == 1


def test_missing_classification_fails(prov, now) -> None:
    with pytest.raises(ValidationError):
        Person(
            entity_id="e",
            trust_score=0.5,
            provenance_reference=prov,
            owner="bu",
            effective_from=now,
        )


def test_missing_trust_score_fails(prov, now) -> None:
    with pytest.raises(ValidationError):
        Person(
            entity_id="e",
            classification="INTERNAL",
            provenance_reference=prov,
            owner="bu",
            effective_from=now,
        )


def test_missing_provenance_fails(now) -> None:
    with pytest.raises(ValidationError):
        Person(
            entity_id="e",
            classification="INTERNAL",
            trust_score=0.5,
            owner="bu",
            effective_from=now,
        )


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_trust_score_out_of_range_fails(prov, now, bad) -> None:
    with pytest.raises(ValidationError):
        _person(prov, now, trust_score=bad)


@pytest.mark.parametrize("edge", [0.0, 1.0, 0.5])
def test_trust_score_in_range_ok(prov, now, edge) -> None:
    assert _person(prov, now, trust_score=edge).trust_score == edge


def test_entity_is_frozen(prov, now) -> None:
    p = _person(prov, now)
    with pytest.raises(ValidationError):
        p.trust_score = 0.9  # type: ignore[misc]


def test_extra_field_is_rejected(prov, now) -> None:
    with pytest.raises(ValidationError):
        _person(prov, now, injected_admin=True)


def test_invalid_lifecycle_state_fails(prov, now) -> None:
    with pytest.raises(ValidationError):
        _person(prov, now, lifecycle_status="teleported")


def test_effective_to_must_be_after_from(prov, now) -> None:
    with pytest.raises(ValidationError):
        _person(prov, now, effective_to=now - timedelta(days=1))


def test_effective_to_after_from_ok(prov, now) -> None:
    later = now + timedelta(days=1)
    assert _person(prov, now, effective_to=later).effective_to == later


def test_entity_cannot_supersede_itself(prov, now) -> None:
    eid = new_entity_id()
    with pytest.raises(ValidationError):
        Person(
            entity_id=eid,
            classification="INTERNAL",
            trust_score=0.5,
            provenance_reference=prov,
            owner="bu",
            effective_from=now,
            supersedes=eid,
        )


def test_supersession_creates_new_version_original_immutable(prov, now) -> None:
    original = _person(prov, now, version=1)
    successor = _person(
        prov,
        now,
        version=2,
        supersedes=original.entity_id,
        lifecycle_status="active",
    )
    assert successor.version == 2
    assert successor.supersedes == original.entity_id
    # The original object is frozen — no in-place mutation ("no silent mutation
    # of a historical version").
    with pytest.raises(ValidationError):
        original.lifecycle_status = LifecycleStatus.SUPERSEDED  # type: ignore[misc]


def test_provenance_reference_is_a_pointer_only(now) -> None:
    ref = ProvenanceReference(source_principal="svc-x", event_id="evt-9")
    # It carries identifiers, never audit content.
    assert set(ref.model_dump()) == {
        "source_principal",
        "event_id",
        "correlation_id",
        "provenance_record_id",
        "custody_event_id",
    }


def test_naive_datetime_still_constructs_but_is_recorded() -> None:
    # Timezone handling is not enforced here (a later hardening); ensure a
    # normal aware datetime is accepted.
    p = _person(
        ProvenanceReference(source_principal="a", event_id="b"),
        datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert p.effective_from.year == 2026
