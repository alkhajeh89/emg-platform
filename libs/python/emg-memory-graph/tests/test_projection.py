"""Semantic-layer projection + executor (Deliverable 10 / 8)."""

from __future__ import annotations

import pytest
from emg_memory_graph import (
    MemoryGraph,
    MemoryGraphExecutor,
    to_semantic_graph,
    to_semantic_node,
)
from emg_semantic_layer import (
    FilterCondition,
    FilterOperator,
    NodeSelector,
    SemanticFilter,
    SemanticQuery,
    SemanticQueryError,
    SemanticTraversal,
    TraversalStep,
)


def test_projection_shapes(lineage_graph: MemoryGraph) -> None:
    sg = to_semantic_graph(lineage_graph)
    assert len(sg.nodes) == lineage_graph.node_count
    assert len(sg.relationships) == lineage_graph.edge_count
    n = to_semantic_node(lineage_graph.node("dec"))  # type: ignore[arg-type]
    assert n.type == "decision"
    assert "confidence" in n.properties


def test_executor_select_by_type(lineage_graph: MemoryGraph) -> None:
    ex = MemoryGraphExecutor(lineage_graph)
    res = ex.execute(SemanticQuery(selector=NodeSelector(type="person")))
    assert [n.node_id for n in res.graph.nodes] == ["sara"]
    assert res.page.returned_count == 1


def test_executor_select_by_ids(lineage_graph: MemoryGraph) -> None:
    ex = MemoryGraphExecutor(lineage_graph)
    res = ex.execute(SemanticQuery(selector=NodeSelector(ids=("dec", "mtg"))))
    assert {n.node_id for n in res.graph.nodes} == {"dec", "mtg"}


def test_executor_filter(lineage_graph: MemoryGraph) -> None:
    ex = MemoryGraphExecutor(lineage_graph)
    flt = SemanticFilter(
        conditions=(FilterCondition(field="label", operator=FilterOperator.EQ, value="Sara"),)
    )
    res = ex.execute(SemanticQuery(selector=NodeSelector(filter=flt)))
    assert [n.node_id for n in res.graph.nodes] == ["sara"]


def test_executor_pagination(lineage_graph: MemoryGraph) -> None:
    from emg_semantic_layer import Pagination

    ex = MemoryGraphExecutor(lineage_graph)
    all_ids = tuple(n.node_id for n in lineage_graph.nodes)  # 8 nodes
    res = ex.execute(
        SemanticQuery(selector=NodeSelector(ids=all_ids), pagination=Pagination(limit=3, offset=0))
    )
    assert res.page.returned_count == 3
    assert res.page.has_more
    res2 = ex.execute(
        SemanticQuery(selector=NodeSelector(ids=all_ids), pagination=Pagination(limit=3, offset=6))
    )
    assert res2.page.returned_count == 2
    assert not res2.page.has_more


def test_executor_rejects_traversal(lineage_graph: MemoryGraph) -> None:
    ex = MemoryGraphExecutor(lineage_graph)
    q = SemanticQuery(
        selector=NodeSelector(type="decision"),
        traversal=SemanticTraversal(steps=(TraversalStep(relationship_types=("precedes",)),)),
    )
    with pytest.raises(SemanticQueryError):
        ex.execute(q)
