"""Temporal graph traversal + historical reconstruction (FEAT-05-6, Deliverable 4).

Because facts are never overwritten (see `temporal.py`), the graph can always be
reconstructed as it stood at any past instant. These are pure functions over a
`MemoryGraph`:

  * ``active_edges_at`` — edges whose valid interval contains a moment.
  * ``subgraph_as_of`` — the immutable sub-graph that was "true" at a moment
    (nodes that existed then + edges valid then).
  * ``neighbors_at`` — neighbours reachable over edges valid at a moment.
  * ``attribute_at`` — the value of a node attribute (e.g. ``"owner"``) at a
    moment, from that node's `TemporalHistory`.

Complexity: ``active_edges_at`` / ``subgraph_as_of`` are O(N + E); ``neighbors_at``
is O(deg); ``attribute_at`` is O(k) over a node's bounded timeline.
"""

from __future__ import annotations

from datetime import datetime

from .edges import MemoryEdge
from .graph import MemoryGraph
from .temporal import TemporalFact


def node_exists_at(graph: MemoryGraph, node_id: str, moment: datetime) -> bool:
    """A node exists at `moment` iff it was created at or before `moment`."""
    node = graph.node(node_id)
    return node is not None and node.created_at <= moment


def active_edges_at(graph: MemoryGraph, moment: datetime) -> tuple[MemoryEdge, ...]:
    """All edges whose valid interval contains `moment`, deterministically ordered."""
    return tuple(e for e in graph.edges if e.is_active_at(moment))


def subgraph_as_of(graph: MemoryGraph, moment: datetime) -> MemoryGraph:
    """The immutable sub-graph as it stood at `moment`: nodes that existed then and
    edges valid then (whose endpoints also existed). A new `MemoryGraph` snapshot."""
    live_nodes = tuple(n for n in graph.nodes if n.created_at <= moment)
    live_ids = {n.node_id for n in live_nodes}
    live_edges = tuple(
        e
        for e in graph.edges
        if e.is_active_at(moment) and e.source_id in live_ids and e.target_id in live_ids
    )
    return MemoryGraph(nodes=live_nodes, edges=live_edges)


def neighbors_at(graph: MemoryGraph, node_id: str, moment: datetime) -> tuple[str, ...]:
    """Ids of nodes reachable from `node_id` over edges valid at `moment`."""
    result: set[str] = set()
    for edge in graph.incident_edges(node_id):
        if not edge.is_active_at(moment):
            continue
        other = edge.target_id if edge.source_id == node_id else edge.source_id
        if node_exists_at(graph, other, moment):
            result.add(other)
    result.discard(node_id)
    return tuple(sorted(result))


def attribute_at(
    graph: MemoryGraph, node_id: str, attribute: str, moment: datetime
) -> TemporalFact | None:
    """The value a node's attribute held at `moment` (historical reconstruction),
    or None if the node/attribute had no value then."""
    node = graph.node(node_id)
    if node is None:
        return None
    history = node.history_for(attribute)
    return history.as_of(moment) if history is not None else None
