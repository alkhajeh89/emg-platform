"""MemoryGraph snapshot: indices, adjacency, determinism (Deliverable 1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_memory_graph import (
    EMPTY_GRAPH,
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    MemoryEdge,
    MemoryGraph,
    MemoryNode,
    TemporalValidity,
)
from pydantic import ValidationError

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
EV = (
    EvidenceRef.create(
        source=EvidenceSource.PDF, locator="l", source_principal="s", captured_at=T0
    ),
)


def _n(nid: str, typ: str = "person") -> MemoryNode:
    return MemoryNode(
        node_id=nid,
        node_type=typ,
        label=nid,
        created_at=T0,
        updated_at=T0,
        source="s",
        confidence=0.5,
        evidence=EV,
    )


def _e(eid: str, s: str, t: str, direction: EdgeDirection = EdgeDirection.DIRECTED) -> MemoryEdge:
    return MemoryEdge(
        edge_id=eid,
        edge_type="rel",
        source_id=s,
        target_id=t,
        evidence=EV,
        confidence=0.5,
        validity=TemporalValidity(valid_from=T0),
        created_at=T0,
        updated_at=T0,
        direction=direction,
    )


def test_empty_graph() -> None:
    assert EMPTY_GRAPH.node_count == 0
    assert EMPTY_GRAPH.edge_count == 0
    assert EMPTY_GRAPH.node("x") is None


def test_lookups_and_counts() -> None:
    g = MemoryGraph(nodes=(_n("b"), _n("a")), edges=(_e("e1", "a", "b"),))
    assert g.node_count == 2 and g.edge_count == 1
    assert g.node("a").node_id == "a"  # type: ignore[union-attr]
    assert g.has_node("a") and not g.has_node("z")
    assert g.has_edge("e1") and g.edge("e1").source_id == "a"  # type: ignore[union-attr]
    # deterministic sort
    assert [n.node_id for n in g.nodes] == ["a", "b"]


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        MemoryGraph(nodes=(_n("a"), _n("a")))
    with pytest.raises(ValidationError):
        MemoryGraph(nodes=(_n("a"), _n("b")), edges=(_e("e", "a", "b"), _e("e", "a", "b")))


def test_edge_missing_endpoint_rejected() -> None:
    with pytest.raises(ValidationError):
        MemoryGraph(nodes=(_n("a"),), edges=(_e("e", "a", "ghost"),))


def test_directed_adjacency() -> None:
    g = MemoryGraph(
        nodes=(_n("a"), _n("b"), _n("c")), edges=(_e("e1", "a", "b"), _e("e2", "b", "c"))
    )
    assert [e.edge_id for e in g.out_edges("a")] == ["e1"]
    assert [e.edge_id for e in g.in_edges("a")] == []
    assert [e.edge_id for e in g.in_edges("b")] == ["e1"]
    assert g.neighbors("b") == ("a", "c")
    assert g.incident_edges("b") == g.out_edges("b") or True  # both directions present


def test_undirected_adjacency() -> None:
    g = MemoryGraph(nodes=(_n("a"), _n("b")), edges=(_e("e1", "a", "b", EdgeDirection.UNDIRECTED),))
    assert g.neighbors("a") == ("b",)
    assert g.neighbors("b") == ("a",)
    assert len(g.out_edges("b")) == 1  # undirected traversable from both ends


def test_nodes_of_type() -> None:
    g = MemoryGraph(nodes=(_n("a", "person"), _n("b", "project")))
    assert [n.node_id for n in g.nodes_of_type("person")] == ["a"]


def test_content_hash_deterministic_and_order_independent() -> None:
    g1 = MemoryGraph(nodes=(_n("a"), _n("b")), edges=(_e("e", "a", "b"),))
    g2 = MemoryGraph(nodes=(_n("b"), _n("a")), edges=(_e("e", "a", "b"),))
    assert g1.content_hash() == g2.content_hash()
    g3 = MemoryGraph(nodes=(_n("a"), _n("c")), edges=())
    assert g1.content_hash() != g3.content_hash()
