"""Graph query engine (Deliverable 8)."""

from __future__ import annotations

import pytest
from emg_memory_graph import MemoryGraph, MemoryQueryEngine, NodeNotFoundError


def test_who_approved(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    approvers = q.who_approved("dec")
    assert [r.node.label for r in approvers] == ["Sara"]
    assert approvers[0].edge_type == "approved_by"


def test_why_decided_backward(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    trace = q.why_decided("dec")
    assert "mtg" in {n.node_id for n in trace.nodes}


def test_supporting_evidence_for_node_and_edge(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    assert len(q.supporting_evidence("dec")) >= 1
    edge_id = lineage_graph.edges[0].edge_id
    assert len(q.supporting_evidence(edge_id)) >= 1
    with pytest.raises(NodeNotFoundError):
        q.supporting_evidence("ghost")


def test_meetings_discussing(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    assert [r.node.label for r in q.meetings_discussing("dec")] == ["M1"]


def test_participants(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    assert [r.node.label for r in q.participants("mtg")] == ["Sara"]


def test_risks_from_policy(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    assert [r.node.label for r in q.risks_from_policy("pol")] == ["K1"]


def test_affected_projects(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    assert [r.node.node_id for r in q.affected_projects("risk")] == ["proj"]


def test_shortest_path(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    path = q.shortest_path("req", "appr")
    assert path is not None
    assert path.node_ids[0] == "req" and path.node_ids[-1] == "appr"
    assert path.length == 3
    # self path
    assert q.shortest_path("req", "req").node_ids == ("req",)  # type: ignore[union-attr]


def test_shortest_path_unreachable() -> None:
    from _mg_helpers import ASOF, node_input
    from emg_memory_graph import MemoryGraphBuilder

    g = (
        MemoryGraphBuilder()
        .build(nodes=(node_input("a", "x", "A"), node_input("b", "x", "B")), as_of=ASOF)
        .graph
    )
    assert MemoryQueryEngine(g).shortest_path("a", "b") is None


def test_historical_owners(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    assert q.historical_owners("proj") is None  # no owner history on this fixture
    with pytest.raises(NodeNotFoundError):
        q.historical_owners("ghost")


def test_unknown_node_related(lineage_graph: MemoryGraph) -> None:
    q = MemoryQueryEngine(lineage_graph)
    with pytest.raises(NodeNotFoundError):
        q.who_approved("ghost")
