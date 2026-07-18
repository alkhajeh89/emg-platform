"""The Enterprise Memory Graph query engine (FEAT-05-6, Deliverable 8).

High-level, question-shaped APIs over an immutable `MemoryGraph`. Each answers one
of the sprint's target questions and returns immutable, evidence-carrying results:

  * who_approved(decision)          → who approved this?
  * why_decided(decision)           → why was this decision made? (backward lineage)
  * supporting_evidence(element)    → show all supporting evidence
  * historical_owners(node)         → show historical owners
  * changed_between(rev_a, rev_b)   → what changed between graph versions?
  * affected_projects(node)         → which projects are affected?
  * risks_from_policy(policy)       → which risks originate from this policy?
  * meetings_discussing(decision)   → which meetings discussed this decision?
  * participants(node)              → which people participated?
  * shortest_path(a, b)             → shortest relationship path between two entities

Relationship lookups run in O(deg); ``shortest_path`` is BFS in O(N + E). All
outputs are deterministically ordered.
"""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel, ConfigDict, Field

from .edges import MemoryEdge
from .enums import EdgeType
from .errors import NodeNotFoundError
from .evidence import EvidenceRef
from .graph import MemoryGraph
from .labels import SafeLabel
from .lineage import DecisionLineage, LineageTrace
from .nodes import MemoryNode
from .temporal import TemporalHistory
from .versioning import GraphDiff, GraphHistory

_APPROVAL_EDGES = frozenset({EdgeType.APPROVED.value, EdgeType.APPROVED_BY.value})
_DISCUSSION_EDGES = frozenset({EdgeType.DISCUSSED_IN.value, EdgeType.DISCUSSED.value})
_PARTICIPATION_EDGES = frozenset({EdgeType.PARTICIPATED_IN.value, EdgeType.HAS_PARTICIPANT.value})
_AFFECTS_EDGES = frozenset({EdgeType.AFFECTS.value, EdgeType.PART_OF.value})
_RISK_EDGES = frozenset(
    {EdgeType.ORIGINATES_FROM.value, EdgeType.AFFECTS.value, EdgeType.MITIGATES.value}
)


class RelatedNode(BaseModel):
    """A node related to a subject, with the edge that connects them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node: MemoryNode
    via_edge_id: SafeLabel
    edge_type: SafeLabel
    confidence: float = Field(ge=0.0, le=1.0)


class PathResult(BaseModel):
    """A shortest relationship path between two nodes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_ids: tuple[SafeLabel, ...]
    edge_ids: tuple[SafeLabel, ...]

    @property
    def length(self) -> int:
        """Number of hops (edges) in the path."""
        return len(self.edge_ids)


class MemoryQueryEngine:
    """Deterministic query engine over a `MemoryGraph`."""

    def __init__(
        self, graph: MemoryGraph, *, lineage_edge_types: frozenset[str] | None = None
    ) -> None:
        self._graph = graph
        self._lineage = DecisionLineage(graph, edge_types=lineage_edge_types)

    def _require(self, node_id: str) -> MemoryNode:
        node = self._graph.node(node_id)
        if node is None:
            raise NodeNotFoundError(f"unknown node: {node_id}")
        return node

    def node(self, node_id: str) -> MemoryNode | None:
        return self._graph.node(node_id)

    # --- evidence ------------------------------------------------------------
    def supporting_evidence(self, element_id: str) -> tuple[EvidenceRef, ...]:
        """All evidence supporting a node OR an edge (every assertion has some)."""
        node = self._graph.node(element_id)
        if node is not None:
            return node.evidence
        edge = self._graph.edge(element_id)
        if edge is not None:
            return edge.evidence
        raise NodeNotFoundError(f"unknown node or edge: {element_id}")

    # --- generic relationship lookup ----------------------------------------
    def _related(
        self, node_id: str, edge_types: frozenset[str], *, target_type: str | None = None
    ) -> tuple[RelatedNode, ...]:
        self._require(node_id)
        out: list[RelatedNode] = []
        for edge in self._graph.incident_edges(node_id):
            if edge.edge_type not in edge_types:
                continue
            other_id = edge.target_id if edge.source_id == node_id else edge.source_id
            other = self._graph.node(other_id)
            if other is None:
                continue
            if target_type is not None and other.node_type != target_type:
                continue
            out.append(
                RelatedNode(
                    node=other,
                    via_edge_id=edge.edge_id,
                    edge_type=edge.edge_type,
                    confidence=edge.confidence,
                )
            )
        return tuple(sorted(out, key=lambda r: (r.node.node_id, r.via_edge_id)))

    # --- question-shaped APIs ------------------------------------------------
    def who_approved(self, decision_id: str) -> tuple[RelatedNode, ...]:
        """Who approved this? Nodes connected by an approval edge."""
        return self._related(decision_id, _APPROVAL_EDGES)

    def why_decided(self, decision_id: str) -> LineageTrace:
        """Why was this decision made? The backward lineage (its antecedents)."""
        return self._lineage.backward(decision_id)

    def meetings_discussing(self, decision_id: str) -> tuple[RelatedNode, ...]:
        """Which meetings discussed this decision?"""
        return self._related(decision_id, _DISCUSSION_EDGES)

    def participants(self, node_id: str) -> tuple[RelatedNode, ...]:
        """Which people participated (in a meeting/decision/project)?"""
        return self._related(node_id, _PARTICIPATION_EDGES)

    def affected_projects(self, node_id: str) -> tuple[RelatedNode, ...]:
        """Which projects are affected by this node?"""
        return self._related(node_id, _AFFECTS_EDGES, target_type="project")

    def risks_from_policy(self, policy_id: str) -> tuple[RelatedNode, ...]:
        """Which risks originate from this policy?"""
        return self._related(policy_id, _RISK_EDGES, target_type="risk")

    def historical_owners(self, node_id: str, attribute: str = "owner") -> TemporalHistory | None:
        """Show historical owners: the temporal history of a node's owner (or any
        temporal attribute)."""
        return self._require(node_id).history_for(attribute)

    def changed_between(
        self, history: GraphHistory, from_revision_id: str, to_revision_id: str
    ) -> GraphDiff:
        """What changed between two graph versions?"""
        return history.diff(from_revision_id, to_revision_id)

    # --- shortest path (BFS) -------------------------------------------------
    def shortest_path(self, from_id: str, to_id: str) -> PathResult | None:
        """The shortest relationship path (fewest hops) between two entities,
        treating edges as undirected for reachability. None if unreachable.
        BFS: O(N + E)."""
        self._require(from_id)
        self._require(to_id)
        if from_id == to_id:
            return PathResult(node_ids=(from_id,), edge_ids=())
        prev_node: dict[str, str] = {}
        prev_edge: dict[str, MemoryEdge] = {}
        visited = {from_id}
        queue: deque[str] = deque([from_id])
        while queue:
            current = queue.popleft()
            for edge in self._graph.incident_edges(current):
                nxt = edge.target_id if edge.source_id == current else edge.source_id
                if nxt in visited:
                    continue
                visited.add(nxt)
                prev_node[nxt] = current
                prev_edge[nxt] = edge
                if nxt == to_id:
                    return self._reconstruct(from_id, to_id, prev_node, prev_edge)
                queue.append(nxt)
        return None

    @staticmethod
    def _reconstruct(
        from_id: str,
        to_id: str,
        prev_node: dict[str, str],
        prev_edge: dict[str, MemoryEdge],
    ) -> PathResult:
        node_chain: list[str] = [to_id]
        edge_chain: list[str] = []
        cursor = to_id
        while cursor != from_id:
            edge_chain.append(prev_edge[cursor].edge_id)
            cursor = prev_node[cursor]
            node_chain.append(cursor)
        node_chain.reverse()
        edge_chain.reverse()
        return PathResult(node_ids=tuple(node_chain), edge_ids=tuple(edge_chain))
