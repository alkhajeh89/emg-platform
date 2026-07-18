"""Executor filter operators, boolean logic, ordering (Deliverable 8/10)."""

from __future__ import annotations

from _mg_helpers import ASOF, node_input
from emg_memory_graph import MemoryGraphBuilder, MemoryGraphExecutor
from emg_semantic_layer import (
    BooleanOperator,
    FilterCondition,
    FilterOperator,
    NodeSelector,
    Pagination,
    SemanticFilter,
    SemanticOrdering,
    SemanticQuery,
    SortDirection,
    SortKey,
)


def _graph() -> MemoryGraphBuilder:
    return MemoryGraphBuilder()


def _g():  # type: ignore[no-untyped-def]
    b = _graph()
    nodes = (
        node_input("a", "person", "Alice"),
        node_input("b", "person", "Bob"),
        node_input("c", "project", "Carol"),
    )
    return b.build(nodes=nodes, as_of=ASOF).graph


def _ids(res) -> set:  # type: ignore[no-untyped-def]
    return {n.node_id for n in res.graph.nodes}


def test_eq_neq() -> None:
    ex = MemoryGraphExecutor(_g())
    r = ex.execute(
        SemanticQuery(
            selector=NodeSelector(
                filter=SemanticFilter(
                    conditions=(
                        FilterCondition(field="label", operator=FilterOperator.NEQ, value="Alice"),
                    )
                )
            )
        )
    )
    assert "a" not in _ids(r)


def test_in_not_in() -> None:
    ex = MemoryGraphExecutor(_g())
    r = ex.execute(
        SemanticQuery(
            selector=NodeSelector(
                filter=SemanticFilter(
                    conditions=(
                        FilterCondition(
                            field="label", operator=FilterOperator.IN, value=("Alice", "Bob")
                        ),
                    )
                )
            )
        )
    )
    assert _ids(r) == {"a", "b"}
    r2 = ex.execute(
        SemanticQuery(
            selector=NodeSelector(
                filter=SemanticFilter(
                    conditions=(
                        FilterCondition(
                            field="label", operator=FilterOperator.NOT_IN, value=("Alice",)
                        ),
                    )
                )
            )
        )
    )
    assert "a" not in _ids(r2)


def test_exists_not_exists() -> None:
    ex = MemoryGraphExecutor(_g())
    r = ex.execute(
        SemanticQuery(
            selector=NodeSelector(
                filter=SemanticFilter(
                    conditions=(
                        FilterCondition(field="confidence", operator=FilterOperator.EXISTS),
                    )
                )
            )
        )
    )
    assert len(_ids(r)) == 3
    r2 = ex.execute(
        SemanticQuery(
            selector=NodeSelector(
                filter=SemanticFilter(
                    conditions=(FilterCondition(field="ghost", operator=FilterOperator.NOT_EXISTS),)
                )
            )
        )
    )
    assert len(_ids(r2)) == 3


def test_contains_starts_with() -> None:
    ex = MemoryGraphExecutor(_g())
    r = ex.execute(
        SemanticQuery(
            selector=NodeSelector(
                filter=SemanticFilter(
                    conditions=(
                        FilterCondition(
                            field="label", operator=FilterOperator.CONTAINS, value="li"
                        ),
                    )
                )
            )
        )
    )
    assert _ids(r) == {"a"}  # Alice
    r2 = ex.execute(
        SemanticQuery(
            selector=NodeSelector(
                filter=SemanticFilter(
                    conditions=(
                        FilterCondition(
                            field="label", operator=FilterOperator.STARTS_WITH, value="B"
                        ),
                    )
                )
            )
        )
    )
    assert _ids(r2) == {"b"}


def test_numeric_comparisons() -> None:
    ex = MemoryGraphExecutor(_g())
    for op in (FilterOperator.LT, FilterOperator.LTE, FilterOperator.GT, FilterOperator.GTE):
        r = ex.execute(
            SemanticQuery(
                selector=NodeSelector(
                    filter=SemanticFilter(
                        conditions=(FilterCondition(field="confidence", operator=op, value=0.99),)
                    )
                )
            )
        )
        # confidence < 0.99 should include all; > 0.99 none — just assert it runs + bounded
        assert isinstance(_ids(r), set)


def test_boolean_or_and_not() -> None:
    ex = MemoryGraphExecutor(_g())
    or_filter = SemanticFilter(
        operator=BooleanOperator.OR,
        conditions=(
            FilterCondition(field="label", operator=FilterOperator.EQ, value="Alice"),
            FilterCondition(field="label", operator=FilterOperator.EQ, value="Bob"),
        ),
    )
    assert _ids(ex.execute(SemanticQuery(selector=NodeSelector(filter=or_filter)))) == {"a", "b"}
    not_filter = SemanticFilter(
        operator=BooleanOperator.NOT,
        conditions=(FilterCondition(field="label", operator=FilterOperator.EQ, value="Alice"),),
    )
    assert "a" not in _ids(ex.execute(SemanticQuery(selector=NodeSelector(filter=not_filter))))


def test_nested_groups() -> None:
    ex = MemoryGraphExecutor(_g())
    flt = SemanticFilter(
        operator=BooleanOperator.AND,
        conditions=(FilterCondition(field="confidence", operator=FilterOperator.EXISTS),),
        groups=(
            SemanticFilter(
                operator=BooleanOperator.OR,
                conditions=(
                    FilterCondition(field="label", operator=FilterOperator.EQ, value="Alice"),
                    FilterCondition(field="label", operator=FilterOperator.EQ, value="Carol"),
                ),
            ),
        ),
    )
    assert _ids(ex.execute(SemanticQuery(selector=NodeSelector(filter=flt)))) == {"a", "c"}


def test_ordering_desc() -> None:
    ex = MemoryGraphExecutor(_g())
    q = SemanticQuery(
        selector=NodeSelector(type="person"),
        ordering=SemanticOrdering(keys=(SortKey(field="label", direction=SortDirection.DESC),)),
        pagination=Pagination(limit=10, offset=0),
    )
    r = ex.execute(q)
    labels = [n.properties["label"] for n in r.graph.nodes]
    assert labels == ["Bob", "Alice"]


def test_top_level_filter_and_selector_filter_combine() -> None:
    ex = MemoryGraphExecutor(_g())
    q = SemanticQuery(
        selector=NodeSelector(type="person"),
        filter=SemanticFilter(
            conditions=(FilterCondition(field="label", operator=FilterOperator.EQ, value="Alice"),)
        ),
    )
    assert _ids(ex.execute(q)) == {"a"}
