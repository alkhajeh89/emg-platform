"""Domain entity tests (FEAT-05-1): every Organizational and Risk & Safety
entity constructs with the envelope, pins its type tag, and rejects a forged
type or a missing envelope."""

from __future__ import annotations

import pytest
from emg_ontology import (
    ENTITY_REGISTRY,
    BusinessUnit,
    Control,
    Evidence,
    Incident,
    Organization,
    Person,
    Policy,
    Process,
    Project,
    Regulation,
    Risk,
    Role,
    System,
    new_entity_id,
    validate_entity,
)
from pydantic import ValidationError

ORGANIZATIONAL = [Organization, BusinessUnit, Person, Role, System, Project, Process]
RISK_SAFETY = [Risk, Control, Policy, Regulation, Incident, Evidence]


def _kwargs(prov, now) -> dict:
    return dict(
        entity_id=new_entity_id(),
        classification="INTERNAL",
        trust_score=0.6,
        provenance_reference=prov,
        owner="bu-1",
        effective_from=now,
    )


@pytest.mark.parametrize("model", ORGANIZATIONAL + RISK_SAFETY)
def test_every_domain_entity_constructs_and_pins_type(model, prov, now) -> None:
    inst = model(**_kwargs(prov, now))
    assert inst.entity_type == model.__name__
    assert inst.classification.value == "INTERNAL"


@pytest.mark.parametrize("model", ORGANIZATIONAL + RISK_SAFETY)
def test_forged_type_tag_is_rejected(model, prov, now) -> None:
    with pytest.raises(ValidationError):
        model(**_kwargs(prov, now), entity_type="SomethingElse")


@pytest.mark.parametrize("model", ORGANIZATIONAL + RISK_SAFETY)
def test_every_domain_entity_missing_envelope_is_nonconformant(model) -> None:
    report = validate_entity({"entity_type": model.__name__, "entity_id": new_entity_id()})
    assert not report.ok


def test_all_thirteen_domain_types_plus_three_refs_registered() -> None:
    for model in ORGANIZATIONAL + RISK_SAFETY:
        assert model.__name__ in ENTITY_REGISTRY
    for ref in ("AuditEventRef", "ProvenanceRecordRef", "CustodyRecordRef"):
        assert ref in ENTITY_REGISTRY


def test_archetype_assignment() -> None:
    assert Person.archetype == "Actor"
    assert Policy.archetype == "Artifact"
    assert Incident.archetype == "Event"
