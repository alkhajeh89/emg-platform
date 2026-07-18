"""Temporal graph traversal + historical reconstruction (Deliverable 4)."""

from __future__ import annotations

from datetime import datetime, timezone

from _mg_helpers import ASOF, T0, edge_input, ev, node_input
from emg_memory_graph import (
    MemoryGraphBuilder,
    MemoryNode,
    TemporalHistory,
    active_edges_at,
    attribute_at,
    neighbors_at,
    node_exists_at,
    subgraph_as_of,
)

T1 = datetime(2025, 2, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, tzinfo=timezone.utc)
MID_24 = datetime(2024, 6, 1, tzinfo=timezone.utc)
MID_25 = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _graph_with_ownership_change() -> MemoryGraphBuilder:
    return MemoryGraphBuilder()


def test_active_edges_and_subgraph_as_of() -> None:
    b = MemoryGraphBuilder()
    # owns edge Ahmed->Project valid [T0, T1); then Mohammed->Project valid [T1, None)
    nodes = (
        node_input("proj", "project", "P"),
        node_input("ahmed", "person", "Ahmed"),
        node_input("moh", "person", "Mohammed"),
    )
    edges = (
        edge_input("owned_by", "proj", "ahmed", valid_from=T0, valid_until=T1),
        edge_input("owned_by", "proj", "moh", valid_from=T1),
    )
    g = b.build(nodes=nodes, edges=edges, as_of=ASOF).graph
    assert len(active_edges_at(g, MID_24)) == 1
    sub_2024 = subgraph_as_of(g, MID_24)
    assert sub_2024.neighbors("proj") == ("ahmed",)
    sub_2025 = subgraph_as_of(g, MID_25)
    assert sub_2025.neighbors("proj") == ("moh",)


def test_node_exists_at() -> None:
    b = MemoryGraphBuilder()
    late = datetime(2025, 1, 1, tzinfo=timezone.utc)
    g = b.build(nodes=(node_input("a", "person", "A", created_at=late),), as_of=ASOF).graph
    assert not node_exists_at(g, "a", T0)
    assert node_exists_at(g, "a", T2)
    assert not node_exists_at(g, "ghost", T2)


def test_neighbors_at() -> None:
    b = MemoryGraphBuilder()
    g = b.build(
        nodes=(node_input("a", "person", "A"), node_input("b", "person", "B")),
        edges=(edge_input("linked", "a", "b", valid_from=T0, valid_until=T1),),
        as_of=ASOF,
    ).graph
    assert neighbors_at(g, "a", MID_24) == ("b",)
    assert neighbors_at(g, "a", MID_25) == ()  # edge expired


def test_attribute_at_reconstruction() -> None:
    e = ev("hist")
    hist = (
        TemporalHistory(attribute="owner")
        .with_change(value="ahmed", effective_from=T0, evidence=(e,), recorded_at=T0)
        .with_change(value="mohammed", effective_from=T1, evidence=(e,), recorded_at=T1)
    )
    node = MemoryNode(
        node_id="proj",
        node_type="project",
        label="P",
        created_at=T0,
        updated_at=T1,
        source="s",
        confidence=0.5,
        evidence=(e,),
        histories=(hist,),
    )
    from emg_memory_graph import MemoryGraph

    g = MemoryGraph(nodes=(node,))
    assert attribute_at(g, "proj", "owner", MID_24).value == "ahmed"  # type: ignore[union-attr]
    assert attribute_at(g, "proj", "owner", MID_25).value == "mohammed"  # type: ignore[union-attr]
    assert attribute_at(g, "proj", "missing", MID_24) is None
    assert attribute_at(g, "ghost", "owner", MID_24) is None
