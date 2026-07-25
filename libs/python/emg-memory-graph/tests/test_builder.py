"""Deterministic graph builder: dedup, merge, incremental (Deliverable 2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from _mg_helpers import ASOF, T0, edge_input, ev, node_input
from emg_common_types import Classification
from emg_memory_graph import (
    EdgeDirection,
    EdgeInput,
    EvidenceSource,
    MemoryGraphBuilder,
    MergeConflictError,
    diff_graphs,
    edge_id_for,
)

T1 = T0 + timedelta(days=30)
T2 = T1 + timedelta(days=30)


def relationship_edge(
    edge_type: str, source_id: str, target_id: str, relationship_id: str, **kwargs: object
) -> EdgeInput:
    base = edge_input(edge_type, source_id, target_id, **kwargs)
    return EdgeInput.model_validate(
        {
            **base.model_dump(),
            "relationship_id": relationship_id,
        }
    )


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


def test_edge_input_without_relationship_id_keeps_generated_id() -> None:
    edge = edge_input("owns", "a", "b")
    assert edge.edge_id() == edge_id_for("owns", "a", "b")


def test_distinct_relationship_ids_preserve_adjacent_assertions() -> None:
    b = MemoryGraphBuilder()
    nodes = (node_input("a", "person", "A"), node_input("b", "project", "B"))
    first = relationship_edge(
        "owns",
        "a",
        "b",
        "rel-1",
        evidence=(ev("first"),),
        valid_from=T0,
        valid_until=T1,
    )
    second = relationship_edge(
        "owns",
        "a",
        "b",
        "rel-1#v2",
        evidence=(ev("second"),),
        valid_from=T1,
        valid_until=T2,
        created_at=T1,
    )

    result = b.build(nodes=nodes, edges=(first, second), as_of=ASOF)

    assert result.graph.edge_count == 2
    assert result.edge_inputs_merged == 0
    assert [edge.edge_id for edge in result.graph.edges] == ["rel-1", "rel-1#v2"]
    assert result.graph.edge("rel-1").validity == first.validity  # type: ignore[union-attr]
    assert result.graph.edge("rel-1#v2").validity == second.validity  # type: ignore[union-attr]
    assert [e.locator for e in result.graph.edge("rel-1").evidence] == [  # type: ignore[union-attr]
        "first"
    ]
    assert [e.locator for e in result.graph.edge("rel-1#v2").evidence] == [  # type: ignore[union-attr]
        "second"
    ]


def test_same_relationship_assertion_merges_evidence() -> None:
    b = MemoryGraphBuilder()
    nodes = (node_input("a", "person", "A"), node_input("b", "project", "B"))
    first = relationship_edge("owns", "a", "b", "rel-1", evidence=(ev("first"),))
    second = relationship_edge("owns", "a", "b", "rel-1", evidence=(ev("second"),))

    result = b.build(nodes=nodes, edges=(first, second), as_of=ASOF)

    assert result.graph.edge_count == 1
    assert result.edge_inputs_merged == 1
    assert {e.locator for e in result.graph.edges[0].evidence} == {"first", "second"}


@pytest.mark.parametrize(
    ("update", "field"),
    [
        ({"validity": edge_input("owns", "a", "b", valid_from=T1).validity}, "validity"),
        ({"target_id": "c"}, "endpoints"),
        ({"direction": EdgeDirection.UNDIRECTED}, "direction"),
        ({"edge_type": "owned_by"}, "edge_type"),
        ({"classification": Classification.CONFIDENTIAL}, "classification"),
    ],
)
def test_same_relationship_id_rejects_conflicting_immutable_fields(
    update: dict[str, object], field: str
) -> None:
    first = relationship_edge("owns", "a", "b", "rel-1")
    conflicting = first.model_copy(update=update)

    with pytest.raises(MergeConflictError, match=rf"rel-1.*{field}"):
        MemoryGraphBuilder().build(edges=(first, conflicting), as_of=ASOF)


def test_existing_edge_rejects_conflicting_validity() -> None:
    b = MemoryGraphBuilder()
    nodes = (node_input("a", "person", "A"), node_input("b", "project", "B"))
    first = relationship_edge("owns", "a", "b", "rel-1")
    base = b.build(nodes=nodes, edges=(first,), as_of=ASOF).graph
    conflicting = relationship_edge("owns", "a", "b", "rel-1", valid_from=T1, created_at=T1)

    with pytest.raises(MergeConflictError, match=r"rel-1.*validity"):
        b.extend(base, edges=(conflicting,), as_of=ASOF)


def test_relationship_versions_are_order_and_batch_independent() -> None:
    b = MemoryGraphBuilder()
    nodes = (node_input("a", "person", "A"), node_input("b", "project", "B"))
    first = relationship_edge(
        "owns",
        "a",
        "b",
        "rel-1",
        valid_until=T1,
    )
    second = relationship_edge(
        "owns",
        "a",
        "b",
        "rel-1#v2",
        valid_from=T1,
        created_at=T1,
    )

    forward = b.build(nodes=nodes, edges=(first, second), as_of=ASOF).graph
    reverse = b.build(nodes=tuple(reversed(nodes)), edges=(second, first), as_of=ASOF).graph
    incremental = b.extend(
        b.build(nodes=nodes, edges=(first,), as_of=ASOF).graph,
        edges=(second,),
        as_of=ASOF,
    ).graph

    assert forward.content_hash() == reverse.content_hash()
    assert forward.content_hash() == incremental.content_hash()


def test_relationship_version_is_added_in_graph_diff() -> None:
    b = MemoryGraphBuilder()
    nodes = (node_input("a", "person", "A"), node_input("b", "project", "B"))
    first = relationship_edge("owns", "a", "b", "rel-1", valid_until=T1)
    second = relationship_edge(
        "owns",
        "a",
        "b",
        "rel-1#v2",
        valid_from=T1,
        created_at=T1,
    )
    before = b.build(nodes=nodes, edges=(first,), as_of=ASOF).graph
    after = b.extend(before, edges=(second,), as_of=ASOF).graph

    diff = diff_graphs(before, after)
    assert diff.added_edges == ("rel-1#v2",)
    assert diff.modified_edges == ()


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
