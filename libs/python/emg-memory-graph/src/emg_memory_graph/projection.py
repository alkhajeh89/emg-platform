"""Bridge to the Semantic Layer (FEAT-05-6, Deliverable 10 / Deliverable 8).

Projects an immutable `MemoryGraph` into an `emg_semantic_layer.SemanticGraph`, so
the memory graph is queryable through the platform's generic, storage-independent
query/traversal model — and, in a later sprint, its visualization. This is a
one-way, lossless-enough projection: node/edge ids, types, classification and the
key scalar properties (confidence, source, label, timestamps) are carried across.

`MemoryGraphExecutor` implements the `SemanticQueryExecutor` protocol for node
selection (ids / type / filter), boolean filters, ordering and pagination over the
projected graph. Multi-step traversal is intentionally delegated to
`MemoryQueryEngine` (which traverses the native adjacency directly); a traversal
query here raises `SemanticQueryError` with that guidance rather than partially
implementing it.
"""

from __future__ import annotations

from typing import cast

from emg_semantic_layer import (
    FilterOperator,
    PageInfo,
    PropertyValue,
    SemanticFilter,
    SemanticGraph,
    SemanticNode,
    SemanticQuery,
    SemanticQueryError,
    SemanticRelationship,
    SemanticResult,
    SortDirection,
)
from emg_semantic_layer.filters import FilterCondition

from .edges import MemoryEdge
from .graph import MemoryGraph
from .nodes import MemoryNode


def to_semantic_node(node: MemoryNode) -> SemanticNode:
    """Project a `MemoryNode` into a `SemanticNode` with its scalar properties."""
    properties: dict[str, PropertyValue] = {
        "label": node.label,
        "confidence": node.confidence,
        "source": node.source,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }
    for item in node.metadata.items:
        properties[f"meta.{item.key}"] = item.value
    return SemanticNode(
        node_id=node.node_id,
        type=node.node_type,
        classification=node.classification,
        properties=properties,
    )


def to_semantic_relationship(edge: MemoryEdge) -> SemanticRelationship:
    """Project a `MemoryEdge` into a `SemanticRelationship`."""
    properties: dict[str, PropertyValue] = {
        "confidence": edge.confidence,
        "direction": edge.direction.value,
        "valid_from": edge.validity.valid_from.isoformat(),
        "valid_until": (
            edge.validity.valid_until.isoformat() if edge.validity.valid_until else None
        ),
    }
    return SemanticRelationship(
        relationship_id=edge.edge_id,
        type=edge.edge_type,
        source_id=edge.source_id,
        target_id=edge.target_id,
        properties=properties,
    )


def to_semantic_graph(graph: MemoryGraph) -> SemanticGraph:
    """Project the whole memory graph into a `SemanticGraph`."""
    return SemanticGraph(
        nodes=tuple(to_semantic_node(n) for n in graph.nodes),
        relationships=tuple(to_semantic_relationship(e) for e in graph.edges),
    )


def _cmp(a: PropertyValue, b: object) -> int:
    """Deterministic comparison for LT/GT operators; only for comparable scalars."""
    if a is None:
        return -1
    return (a > b) - (a < b)  # type: ignore[operator]


def _match_condition(node: SemanticNode, cond: FilterCondition) -> bool:
    present = cond.field in node.properties
    value = node.properties.get(cond.field)
    op = cond.operator
    if op is FilterOperator.EXISTS:
        return present
    if op is FilterOperator.NOT_EXISTS:
        return not present
    if op is FilterOperator.EQ:
        return value == cond.value
    if op is FilterOperator.NEQ:
        return value != cond.value
    if op is FilterOperator.IN:
        return isinstance(cond.value, tuple | list) and value in cond.value
    if op is FilterOperator.NOT_IN:
        return not (isinstance(cond.value, tuple | list) and value in cond.value)
    if op is FilterOperator.CONTAINS:
        return isinstance(value, str) and isinstance(cond.value, str) and cond.value in value
    if op is FilterOperator.STARTS_WITH:
        return (
            isinstance(value, str) and isinstance(cond.value, str) and value.startswith(cond.value)
        )
    if not present or value is None or cond.value is None:
        return False
    if op is FilterOperator.LT:
        return _cmp(value, cond.value) < 0
    if op is FilterOperator.LTE:
        return _cmp(value, cond.value) <= 0
    if op is FilterOperator.GT:
        return _cmp(value, cond.value) > 0
    if op is FilterOperator.GTE:
        return _cmp(value, cond.value) >= 0
    raise SemanticQueryError(f"unsupported operator: {op}")  # pragma: no cover


def _match_filter(node: SemanticNode, flt: SemanticFilter) -> bool:
    results = [_match_condition(node, c) for c in flt.conditions]
    results += [_match_filter(node, g) for g in flt.groups]
    if not results:
        return True
    op = flt.operator.value
    if op == "and":
        return all(results)
    if op == "or":
        return any(results)
    return not any(results)  # not


class MemoryGraphExecutor:
    """A `SemanticQueryExecutor` over a projected memory graph (selection, filter,
    ordering, pagination). Traversal is delegated to `MemoryQueryEngine`."""

    def __init__(self, graph: MemoryGraph) -> None:
        self._graph = graph
        self._semantic = to_semantic_graph(graph)

    def execute(self, query: SemanticQuery) -> SemanticResult:
        if query.traversal is not None:
            raise SemanticQueryError(
                "MemoryGraphExecutor does not execute traversals; use MemoryQueryEngine "
                "for path/lineage traversal over the memory graph."
            )
        nodes = list(self._semantic.nodes)
        sel = query.selector
        if sel.ids:
            wanted = set(sel.ids)
            nodes = [n for n in nodes if n.node_id in wanted]
        if sel.type is not None:
            nodes = [n for n in nodes if n.type == sel.type]
        if sel.filter is not None:
            nodes = [n for n in nodes if _match_filter(n, sel.filter)]
        if query.filter is not None:
            nodes = [n for n in nodes if _match_filter(n, query.filter)]

        # Ordering (by a single property field is sufficient here); default node_id.
        if query.ordering is not None and query.ordering.keys:
            key = query.ordering.keys[0]
            reverse = key.direction is SortDirection.DESC
            nodes.sort(
                key=lambda n: (n.properties.get(key.field) is None, _sort_key(n, key.field)),
                reverse=reverse,
            )
        else:
            nodes.sort(key=lambda n: n.node_id)

        total = len(nodes)
        offset, limit = query.pagination.offset, query.pagination.limit
        page_nodes = nodes[offset : offset + limit]
        page_ids = {n.node_id for n in page_nodes}
        rels = tuple(
            r
            for r in self._semantic.relationships
            if r.source_id in page_ids and r.target_id in page_ids
        )
        result_graph = SemanticGraph(nodes=tuple(page_nodes), relationships=rels)
        page = PageInfo(
            limit=limit,
            offset=offset,
            returned_count=len(page_nodes),
            has_more=offset + limit < total,
        )
        return SemanticResult(graph=result_graph, page=page)


def _sort_key(node: SemanticNode, field: str) -> PropertyValue:
    value = node.properties.get(field)
    return cast(PropertyValue, value if value is not None else "")
