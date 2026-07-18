"""The immutable Enterprise Memory Graph snapshot (FEAT-05-6, Deliverable 1).

`MemoryGraph` is a frozen value object: a set of nodes and edges plus derived
adjacency indices computed once at construction. It is a *snapshot* — mutations
produce a new graph (see the builder and versioning modules), never an in-place
change.

Complexity:
  * construction / index build: O(N + E)
  * ``node`` / ``edge`` / ``has_*`` lookups: O(1)
  * ``out_edges`` / ``in_edges`` / ``incident_edges`` / ``neighbors``: O(deg)
  * ``content_hash``: O((N + E) log(N + E)) (sorted canonical serialization)

All collections are normalized to sorted-unique tuples so equality, hashing and
serialization are deterministic across machines and runs.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, PrivateAttr, field_validator, model_validator

from .edges import MemoryEdge
from .enums import EdgeDirection
from .limits import MAX_EDGES, MAX_NODES
from .nodes import MemoryNode


class MemoryGraph(BaseModel):
    """An immutable snapshot of nodes and edges with derived adjacency indices."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[MemoryNode, ...] = ()
    edges: tuple[MemoryEdge, ...] = ()

    _node_index: dict[str, MemoryNode] = PrivateAttr(default_factory=dict)
    _edge_index: dict[str, MemoryEdge] = PrivateAttr(default_factory=dict)
    _out: dict[str, list[MemoryEdge]] = PrivateAttr(default_factory=dict)
    _in: dict[str, list[MemoryEdge]] = PrivateAttr(default_factory=dict)

    @field_validator("nodes")
    @classmethod
    def _unique_sorted_nodes(cls, value: tuple[MemoryNode, ...]) -> tuple[MemoryNode, ...]:
        if len(value) > MAX_NODES:
            raise ValueError(f"too many nodes (max {MAX_NODES})")
        by_id = {n.node_id: n for n in value}
        if len(by_id) != len(value):
            raise ValueError("duplicate node_id in graph")
        return tuple(sorted(by_id.values(), key=lambda n: n.node_id))

    @field_validator("edges")
    @classmethod
    def _unique_sorted_edges(cls, value: tuple[MemoryEdge, ...]) -> tuple[MemoryEdge, ...]:
        if len(value) > MAX_EDGES:
            raise ValueError(f"too many edges (max {MAX_EDGES})")
        by_id = {e.edge_id: e for e in value}
        if len(by_id) != len(value):
            raise ValueError("duplicate edge_id in graph")
        return tuple(sorted(by_id.values(), key=lambda e: e.edge_id))

    @model_validator(mode="after")
    def _build_indices(self) -> MemoryGraph:
        node_index = {n.node_id: n for n in self.nodes}
        edge_index: dict[str, MemoryEdge] = {}
        out: dict[str, list[MemoryEdge]] = {nid: [] for nid in node_index}
        inc: dict[str, list[MemoryEdge]] = {nid: [] for nid in node_index}
        for edge in self.edges:
            if edge.source_id not in node_index:
                raise ValueError(f"edge {edge.edge_id} references missing source {edge.source_id}")
            if edge.target_id not in node_index:
                raise ValueError(f"edge {edge.edge_id} references missing target {edge.target_id}")
            edge_index[edge.edge_id] = edge
            out[edge.source_id].append(edge)
            inc[edge.target_id].append(edge)
            if edge.direction is EdgeDirection.UNDIRECTED:
                out[edge.target_id].append(edge)
                inc[edge.source_id].append(edge)
        self._node_index = node_index
        self._edge_index = edge_index
        self._out = out
        self._in = inc
        return self

    # --- lookups (O(1)) ------------------------------------------------------
    def node(self, node_id: str) -> MemoryNode | None:
        return self._node_index.get(node_id)

    def edge(self, edge_id: str) -> MemoryEdge | None:
        return self._edge_index.get(edge_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._node_index

    def has_edge(self, edge_id: str) -> bool:
        return edge_id in self._edge_index

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    # --- adjacency (O(deg)) --------------------------------------------------
    def out_edges(self, node_id: str) -> tuple[MemoryEdge, ...]:
        """Edges traversable FROM `node_id` (directed source, or either endpoint
        of an undirected edge). Deterministically ordered by edge_id."""
        return tuple(sorted(self._out.get(node_id, ()), key=lambda e: e.edge_id))

    def in_edges(self, node_id: str) -> tuple[MemoryEdge, ...]:
        """Edges leading INTO `node_id` (directed target, or either endpoint of an
        undirected edge). Deterministically ordered by edge_id."""
        return tuple(sorted(self._in.get(node_id, ()), key=lambda e: e.edge_id))

    def incident_edges(self, node_id: str) -> tuple[MemoryEdge, ...]:
        """All edges touching `node_id`, in either direction (deduped, sorted)."""
        seen = {e.edge_id: e for e in self._out.get(node_id, ())}
        seen.update({e.edge_id: e for e in self._in.get(node_id, ())})
        return tuple(sorted(seen.values(), key=lambda e: e.edge_id))

    def neighbors(self, node_id: str) -> tuple[str, ...]:
        """Ids of nodes reachable from `node_id` over any incident edge (both
        directions). Deterministically sorted."""
        result: set[str] = set()
        for edge in self._out.get(node_id, ()):
            result.add(edge.target_id if edge.source_id == node_id else edge.source_id)
        for edge in self._in.get(node_id, ()):
            result.add(edge.source_id if edge.target_id == node_id else edge.target_id)
        result.discard(node_id)
        return tuple(sorted(result))

    def nodes_of_type(self, node_type: str) -> tuple[MemoryNode, ...]:
        """All nodes of a given type (O(N))."""
        return tuple(n for n in self.nodes if n.node_type == node_type)

    # --- identity ------------------------------------------------------------
    def content_hash(self) -> str:
        """A deterministic SHA-256 over the canonical serialization of every node
        and edge. Two graphs with identical content hash to the same value on any
        machine — the basis for revision identity and snapshot comparison."""
        hasher = hashlib.sha256()
        for node in self.nodes:  # already sorted by node_id
            hasher.update(node.model_dump_json().encode("utf-8"))
            hasher.update(b"\x00")
        hasher.update(b"\x01")
        for edge in self.edges:  # already sorted by edge_id
            hasher.update(edge.model_dump_json().encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()


EMPTY_GRAPH = MemoryGraph()
