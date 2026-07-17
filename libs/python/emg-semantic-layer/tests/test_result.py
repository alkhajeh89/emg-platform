"""Result-model tests (FEAT-05-4): output shape, page consistency, immutability,
and the executor extension point (a test double — the library ships none)."""

from __future__ import annotations

import pytest
from emg_semantic_layer import (
    NodeSelector,
    PageInfo,
    SemanticGraph,
    SemanticNode,
    SemanticQuery,
    SemanticQueryExecutor,
    SemanticResult,
)
from pydantic import ValidationError


def test_page_info_rejects_returned_gt_limit() -> None:
    with pytest.raises(ValidationError):
        PageInfo(limit=2, offset=0, returned_count=3)


def test_result_requires_page_count_to_match_nodes(simple_graph: SemanticGraph) -> None:
    with pytest.raises(ValidationError):
        SemanticResult(
            graph=simple_graph,  # 3 nodes
            page=PageInfo(limit=10, offset=0, returned_count=2),
        )


def test_result_is_consistent_and_immutable(simple_graph: SemanticGraph) -> None:
    result = SemanticResult(
        graph=simple_graph,
        page=PageInfo(limit=10, offset=0, returned_count=3, has_more=False),
    )
    assert result.page.returned_count == len(result.graph.nodes)
    with pytest.raises(ValidationError):
        result.page = PageInfo(limit=1, offset=0, returned_count=0)


def test_executor_protocol_is_structural() -> None:
    """A conforming in-memory double satisfies the protocol without subclassing;
    the library itself ships no executor implementation."""

    class InMemoryExecutor:
        def execute(self, query: SemanticQuery) -> SemanticResult:
            empty = SemanticGraph()
            return SemanticResult(
                graph=empty,
                page=PageInfo(
                    limit=query.pagination.limit, offset=query.pagination.offset, returned_count=0
                ),
            )

    ex = InMemoryExecutor()
    assert isinstance(ex, SemanticQueryExecutor)
    out = ex.execute(SemanticQuery(selector=NodeSelector(type="Person")))
    assert isinstance(out, SemanticResult)
    assert out.page.returned_count == 0


def test_non_executor_fails_protocol_check() -> None:
    class NotAnExecutor:
        pass

    assert not isinstance(NotAnExecutor(), SemanticQueryExecutor)


def test_single_node_result_ok() -> None:
    graph = SemanticGraph(nodes=(SemanticNode(node_id="p1", type="Person"),))
    result = SemanticResult(graph=graph, page=PageInfo(limit=10, offset=0, returned_count=1))
    assert result.graph.node("p1") is not None
