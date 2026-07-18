"""Decision lineage (FEAT-05-6, Deliverable 5).

Traces cause-and-effect chains such as Requirement → Meeting → Discussion →
Decision → Approval → Implementation, in BOTH directions:

  * ``backward(node)`` — the antecedents that led to a node (its causes).
  * ``forward(node)``  — the consequences that flowed from it.
  * ``between(a, b)``  — every simple directed lineage path from a to b.

Traversal follows *directed* edges (an undirected lineage edge is followed either
way), optionally restricted to a set of lineage edge types, with a visited-set so
cycles terminate and a configurable depth bound. Everything is deterministic:
results are ordered by (depth, id).

Complexity: ``backward``/``forward`` are O(V + E) over the reachable sub-graph;
``between`` enumerates simple paths and is bounded by `MAX_PATH_RESULTS` and
`MAX_LINEAGE_DEPTH` to stay tractable.
"""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel, ConfigDict

from .edges import MemoryEdge
from .enums import EdgeDirection
from .errors import NodeNotFoundError, TraversalLimitError
from .graph import MemoryGraph
from .labels import SafeLabel
from .limits import MAX_LINEAGE_DEPTH, MAX_PATH_RESULTS


class LineageNode(BaseModel):
    """A node reached during lineage traversal, with its BFS depth from the origin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: SafeLabel
    node_type: SafeLabel
    depth: int


class LineageEdgeRef(BaseModel):
    """A directed edge traversed during lineage, in causal orientation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge_id: SafeLabel
    edge_type: SafeLabel
    from_id: SafeLabel
    to_id: SafeLabel


class LineageTrace(BaseModel):
    """An immutable lineage traversal result from one origin in one direction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: SafeLabel
    direction: SafeLabel  # "forward" | "backward"
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdgeRef, ...]


class LineagePath(BaseModel):
    """One simple directed lineage path (sequence of node ids, causal order)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_ids: tuple[SafeLabel, ...]


class DecisionLineage:
    """Bidirectional lineage tracer over a `MemoryGraph`."""

    def __init__(
        self,
        graph: MemoryGraph,
        *,
        edge_types: frozenset[str] | None = None,
        max_depth: int = MAX_LINEAGE_DEPTH,
    ) -> None:
        self._graph = graph
        self._edge_types = edge_types
        self._max_depth = min(max_depth, MAX_LINEAGE_DEPTH)

    def _permitted(self, edge: MemoryEdge) -> bool:
        return self._edge_types is None or edge.edge_type in self._edge_types

    def _successors(self, node_id: str) -> list[tuple[MemoryEdge, str]]:
        """Directed lineage successors (node flows TO)."""
        out: list[tuple[MemoryEdge, str]] = []
        for edge in self._graph.out_edges(node_id):
            if not self._permitted(edge):
                continue
            if edge.source_id == node_id:
                out.append((edge, edge.target_id))
            elif edge.direction is EdgeDirection.UNDIRECTED:
                out.append((edge, edge.source_id))
        return out

    def _predecessors(self, node_id: str) -> list[tuple[MemoryEdge, str]]:
        """Directed lineage predecessors (nodes that flow INTO node_id)."""
        out: list[tuple[MemoryEdge, str]] = []
        for edge in self._graph.in_edges(node_id):
            if not self._permitted(edge):
                continue
            if edge.target_id == node_id:
                out.append((edge, edge.source_id))
            elif edge.direction is EdgeDirection.UNDIRECTED:
                out.append((edge, edge.target_id))
        return out

    def _require(self, node_id: str) -> None:
        if not self._graph.has_node(node_id):
            raise NodeNotFoundError(f"unknown node: {node_id}")

    def _bfs(self, origin: str, direction: str) -> LineageTrace:
        self._require(origin)
        step = self._successors if direction == "forward" else self._predecessors
        visited: set[str] = {origin}
        depth_of: dict[str, int] = {origin: 0}
        edges: dict[str, LineageEdgeRef] = {}
        queue: deque[str] = deque([origin])
        while queue:
            current = queue.popleft()
            if depth_of[current] >= self._max_depth:
                continue
            for edge, nxt in step(current):
                # Record the edge in causal (from -> to) orientation.
                frm, to = (current, nxt) if direction == "forward" else (nxt, current)
                edges[edge.edge_id] = LineageEdgeRef(
                    edge_id=edge.edge_id, edge_type=edge.edge_type, from_id=frm, to_id=to
                )
                if nxt not in visited:
                    visited.add(nxt)
                    depth_of[nxt] = depth_of[current] + 1
                    queue.append(nxt)
        nodes = tuple(
            LineageNode(node_id=nid, node_type=self._graph.node(nid).node_type, depth=depth_of[nid])  # type: ignore[union-attr]
            for nid in visited
            if nid != origin
        )
        return LineageTrace(
            origin=origin,
            direction=direction,
            nodes=tuple(sorted(nodes, key=lambda n: (n.depth, n.node_id))),
            edges=tuple(sorted(edges.values(), key=lambda e: e.edge_id)),
        )

    def forward(self, node_id: str) -> LineageTrace:
        """Consequences that flowed from `node_id` (downstream lineage)."""
        return self._bfs(node_id, "forward")

    def backward(self, node_id: str) -> LineageTrace:
        """Antecedents that led to `node_id` (upstream lineage)."""
        return self._bfs(node_id, "backward")

    def between(self, from_id: str, to_id: str) -> tuple[LineagePath, ...]:
        """Every simple directed lineage path from `from_id` to `to_id`,
        deterministically ordered. Bounded by MAX_PATH_RESULTS."""
        self._require(from_id)
        self._require(to_id)
        paths: list[tuple[str, ...]] = []

        def dfs(current: str, path: tuple[str, ...], seen: frozenset[str]) -> None:
            if len(paths) >= MAX_PATH_RESULTS:
                raise TraversalLimitError(f"too many lineage paths (max {MAX_PATH_RESULTS})")
            if current == to_id:
                paths.append(path)
                return
            if len(path) > self._max_depth:
                return
            for _edge, nxt in sorted(self._successors(current), key=lambda es: es[1]):
                if nxt not in seen:
                    dfs(nxt, (*path, nxt), seen | {nxt})

        dfs(from_id, (from_id,), frozenset({from_id}))
        paths.sort()
        return tuple(LineagePath(node_ids=p) for p in paths)
