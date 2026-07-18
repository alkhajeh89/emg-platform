"""Deterministic graph builder: dedup, merge, incremental (Deliverable 2)."""

from __future__ import annotations

from datetime import datetime, timezone

from _mg_helpers import ASOF, T0, edge_input, ev, node_input
from emg_memory_graph import EvidenceSource, MemoryGraphBuilder


def test_build_basic() -> None:
    b = MemoryGraphBuilder()
    res = b.build(
        nodes=(node_input("a", "person", "A"), node_input("p", "project", "P")),
        edges=(edge_input("owns", "a", "p"),),
        as_of=ASOF,
    )
    assert res.graph.node_count == 2
    assert res.graph.edge_count == 1
    assert res.nodes_created == 2
    assert res.edges_created == 1


def test_duplicate_observations_merge_evidence() -> None:
    b = MemoryGraphBuilder()
    n1 = node_input("p", "project", "P", evidence=(ev("d1"),))
    n2 = node_input("p", "project", "P", evidence=(ev("d2", EvidenceSource.EMAIL),))
    res = b.build(nodes=(n1, n2), as_of=ASOF)
    assert res.graph.node_count == 1
    assert res.node_inputs_merged == 1
    assert len(res.graph.node("p").evidence) == 2  # type: ignore[union-attr]


def test_incremental_extend_matches_single_batch() -> None:
    b = MemoryGraphBuilder()
    n1 = node_input("p", "project", "P", evidence=(ev("d1"),))
    n2 = node_input("p", "project", "P", evidence=(ev("d2", EvidenceSource.EMAIL),))
    one = b.build(nodes=(n1, n2), as_of=ASOF).graph
    step = b.build(nodes=(n1,), as_of=ASOF).graph
    two = b.extend(step, nodes=(n2,), as_of=ASOF).graph
    assert one.content_hash() == two.content_hash()


def test_more_evidence_raises_confidence() -> None:
    b = MemoryGraphBuilder()
    one = b.build(nodes=(node_input("p", "project", "P", evidence=(ev("d1"),)),), as_of=ASOF).graph
    two = b.extend(
        one,
        nodes=(node_input("p", "project", "P", evidence=(ev("d2", EvidenceSource.JIRA),)),),
        as_of=ASOF,
    ).graph
    assert two.node("p").confidence >= one.node("p").confidence  # type: ignore[union-attr]


def test_undirected_edge_orientation_collapses() -> None:
    from emg_memory_graph import EdgeDirection

    b = MemoryGraphBuilder()
    e1 = edge_input("linked", "a", "b")
    e2 = edge_input("linked", "b", "a")
    e1 = e1.model_copy(update={"direction": EdgeDirection.UNDIRECTED})
    e2 = e2.model_copy(update={"direction": EdgeDirection.UNDIRECTED})
    res = b.build(
        nodes=(node_input("a", "person", "A"), node_input("b", "person", "B")),
        edges=(e1, e2),
        as_of=ASOF,
    )
    assert res.graph.edge_count == 1  # both orientations -> one edge id


def test_created_updated_timestamps_min_max() -> None:
    b = MemoryGraphBuilder()
    early = datetime(2023, 1, 1, tzinfo=timezone.utc)
    n1 = node_input("p", "project", "P", evidence=(ev("d1"),), created_at=early)
    n2 = node_input("p", "project", "P", evidence=(ev("d2", EvidenceSource.EMAIL),), created_at=T0)
    res = b.build(nodes=(n1, n2), as_of=ASOF)
    node = res.graph.node("p")
    assert node.created_at == early  # type: ignore[union-attr]


def test_from_ontology_order_independent() -> None:
    from emg_common_types import Classification
    from emg_ontology import Entity, ProvenanceReference, Relationship

    prov = ProvenanceReference(source_principal="svc", event_id="evt-1", correlation_id=None)
    e1 = Entity(
        entity_id="ent-1",
        entity_type="Project",
        classification=Classification.INTERNAL,
        trust_score=0.8,
        provenance_reference=prov,
        owner="u",
        effective_from=T0,
    )
    e2 = Entity(
        entity_id="ent-2",
        entity_type="Person",
        classification=Classification.INTERNAL,
        trust_score=0.7,
        provenance_reference=prov,
        owner="u",
        effective_from=T0,
    )
    rel = Relationship(
        relationship_id="rel-1",
        relationship_type="owns",
        from_entity_id="ent-2",
        from_entity_type="Person",
        to_entity_id="ent-1",
        to_entity_type="Project",
        classification=Classification.INTERNAL,
        provenance_reference=prov,
        effective_from=T0,
    )
    b = MemoryGraphBuilder()
    g1 = b.from_ontology(entities=(e1, e2), relationships=(rel,), as_of=ASOF).graph
    g2 = b.from_ontology(entities=(e2, e1), relationships=(rel,), as_of=ASOF).graph
    assert g1.content_hash() == g2.content_hash()
    assert g1.node("ent-1").ontology_entity_id == "ent-1"  # type: ignore[union-attr]


def test_from_ontology_extends_base() -> None:
    from emg_common_types import Classification
    from emg_ontology import Entity, ProvenanceReference

    prov = ProvenanceReference(source_principal="svc", event_id="evt-1", correlation_id=None)
    e1 = Entity(
        entity_id="ent-1",
        entity_type="Project",
        classification=Classification.INTERNAL,
        trust_score=0.8,
        provenance_reference=prov,
        owner="u",
        effective_from=T0,
    )
    b = MemoryGraphBuilder()
    base = b.build(nodes=(node_input("x", "person", "X"),), as_of=ASOF).graph
    res = b.from_ontology(entities=(e1,), as_of=ASOF, base=base)
    assert res.graph.has_node("x")
    assert res.graph.has_node("ent-1")
