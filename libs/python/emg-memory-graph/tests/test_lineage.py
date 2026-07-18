"""Decision lineage traversal (Deliverable 5)."""

from __future__ import annotations

import pytest
from emg_memory_graph import DecisionLineage, MemoryGraph, NodeNotFoundError


def test_backward_lineage(lineage_graph: MemoryGraph) -> None:
    lin = DecisionLineage(lineage_graph)
    trace = lin.backward("dec")
    reached = {n.node_id for n in trace.nodes}
    assert "mtg" in reached and "req" in reached
    assert trace.direction == "backward"
    assert trace.origin == "dec"


def test_forward_lineage(lineage_graph: MemoryGraph) -> None:
    lin = DecisionLineage(lineage_graph)
    trace = lin.forward("req")
    reached = {n.node_id for n in trace.nodes}
    assert {"mtg", "dec", "appr"} <= reached


def test_lineage_depths_ordered(lineage_graph: MemoryGraph) -> None:
    trace = DecisionLineage(lineage_graph).forward("req")
    depths = [n.depth for n in trace.nodes]
    assert depths == sorted(depths)
    mtg = next(n for n in trace.nodes if n.node_id == "mtg")
    assert mtg.depth == 1


def test_between_simple_paths(lineage_graph: MemoryGraph) -> None:
    paths = DecisionLineage(lineage_graph).between("req", "appr")
    assert len(paths) >= 1
    assert paths[0].node_ids[0] == "req"
    assert paths[0].node_ids[-1] == "appr"


def test_edge_type_restriction(lineage_graph: MemoryGraph) -> None:
    lin = DecisionLineage(lineage_graph, edge_types=frozenset({"precedes"}))
    trace = lin.forward("req")
    # only precedes edges followed: req -> mtg -> dec (not resulted_in -> appr)
    reached = {n.node_id for n in trace.nodes}
    assert "mtg" in reached and "dec" in reached
    assert "appr" not in reached


def test_unknown_node_raises(lineage_graph: MemoryGraph) -> None:
    with pytest.raises(NodeNotFoundError):
        DecisionLineage(lineage_graph).forward("ghost")
    with pytest.raises(NodeNotFoundError):
        DecisionLineage(lineage_graph).between("req", "ghost")


def test_cycle_terminates() -> None:
    from _mg_helpers import ASOF, edge_input, node_input
    from emg_memory_graph import MemoryGraphBuilder

    b = MemoryGraphBuilder()
    g = b.build(
        nodes=(node_input("a", "x", "A"), node_input("b", "x", "B")),
        edges=(edge_input("precedes", "a", "b"), edge_input("precedes", "b", "a")),
        as_of=ASOF,
    ).graph
    trace = DecisionLineage(g).forward("a")
    assert {n.node_id for n in trace.nodes} == {"b"}
