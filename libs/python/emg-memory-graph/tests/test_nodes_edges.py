"""MemoryNode / MemoryEdge models + ontology adapters (Deliverable 1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_common_types import Classification
from emg_memory_graph import (
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    MemoryEdge,
    MemoryNode,
    TemporalHistory,
    TemporalValidity,
)
from emg_ontology import Entity, ProvenanceReference, Relationship
from pydantic import ValidationError

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2024, 6, 1, tzinfo=timezone.utc)
EV = (
    EvidenceRef.create(
        source=EvidenceSource.PDF, locator="l", source_principal="s", captured_at=T0
    ),
)
PROV = ProvenanceReference(source_principal="svc", event_id="evt-1", correlation_id=None)


def _node(**kw: object) -> MemoryNode:
    base = dict(
        node_id="n1",
        node_type="person",
        label="A",
        created_at=T0,
        updated_at=T0,
        source="svc",
        confidence=0.5,
        evidence=EV,
    )
    base.update(kw)
    return MemoryNode(**base)  # type: ignore[arg-type]


def test_node_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        _node(evidence=())


def test_node_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        _node(confidence=1.5)
    with pytest.raises(ValidationError):
        _node(confidence=-0.1)


def test_node_updated_before_created_rejected() -> None:
    with pytest.raises(ValidationError):
        _node(created_at=T1, updated_at=T0)


def test_node_aliases_sorted_unique() -> None:
    n = _node(aliases=("z", "a", "a"))
    assert n.aliases == ("a", "z")


def test_node_evidence_deduped_sorted() -> None:
    dup = EV + EV
    n = _node(evidence=dup)
    assert len(n.evidence) == 1


def test_node_duplicate_history_attribute_rejected() -> None:
    h = TemporalHistory(attribute="owner").with_change(
        value="a", effective_from=T0, evidence=EV, recorded_at=T0
    )
    with pytest.raises(ValidationError):
        _node(histories=(h, h))


def test_node_history_for() -> None:
    h = TemporalHistory(attribute="owner").with_change(
        value="a", effective_from=T0, evidence=EV, recorded_at=T0
    )
    n = _node(histories=(h,))
    assert n.history_for("owner") is h
    assert n.history_for("missing") is None


def test_node_from_entity() -> None:
    ent = Entity(
        entity_id="ent-1",
        entity_type="Project",
        classification=Classification.INTERNAL,
        trust_score=0.8,
        provenance_reference=PROV,
        owner="u1",
        effective_from=T0,
    )
    n = MemoryNode.from_entity(ent, label="Atlas", evidence=EV)
    assert n.node_id == "ent-1"
    assert n.node_type == "Project"
    assert n.confidence == 0.8
    assert n.source == "svc"
    assert n.owner == "u1"
    assert n.ontology_entity_id == "ent-1"
    assert n.created_at == T0


def test_node_immutable() -> None:
    n = _node()
    with pytest.raises(ValidationError):
        n.label = "x"  # type: ignore[misc]


def _edge(**kw: object) -> MemoryEdge:
    base = dict(
        edge_id="e1",
        edge_type="owns",
        source_id="a",
        target_id="b",
        evidence=EV,
        confidence=0.5,
        validity=TemporalValidity(valid_from=T0),
        created_at=T0,
        updated_at=T0,
    )
    base.update(kw)
    return MemoryEdge(**base)  # type: ignore[arg-type]


def test_edge_self_loop_rejected() -> None:
    with pytest.raises(ValidationError):
        _edge(source_id="a", target_id="a")


def test_edge_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        _edge(evidence=())


def test_edge_is_active_at() -> None:
    e = _edge(validity=TemporalValidity(valid_from=T0, valid_until=T1))
    assert e.is_active_at(T0)
    assert not e.is_active_at(T1)
    assert e.endpoints() == ("a", "b")


def test_edge_from_relationship() -> None:
    rel = Relationship(
        relationship_id="rel-1",
        relationship_type="owns",
        from_entity_id="a",
        from_entity_type="Person",
        to_entity_id="b",
        to_entity_type="Project",
        classification=Classification.INTERNAL,
        provenance_reference=PROV,
        effective_from=T0,
    )
    e = MemoryEdge.from_relationship(
        rel, evidence=EV, confidence=0.6, direction=EdgeDirection.DIRECTED
    )
    assert e.edge_id == "rel-1"
    assert e.source_id == "a" and e.target_id == "b"
    assert e.confidence == 0.6
