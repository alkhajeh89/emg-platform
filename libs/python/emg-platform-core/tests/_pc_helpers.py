"""Deterministic sample-graph constructors built on the emg-memory-graph public
API (MemoryGraphBuilder / NodeInput / EvidenceRef), so platform-core tests use
real, evidence-linked graphs rather than hand-rolled fixtures."""

from __future__ import annotations

from datetime import datetime, timezone

from emg_memory_graph import (
    EMPTY_GRAPH,
    EvidenceRef,
    EvidenceSource,
    MemoryGraph,
    MemoryGraphBuilder,
    NodeInput,
)

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _evidence() -> EvidenceRef:
    return EvidenceRef.create(
        source=EvidenceSource.PDF, locator="loc", source_principal="svc", captured_at=T0
    )


def _node(node_id: str) -> NodeInput:
    return NodeInput(
        node_id=node_id,
        node_type="person",
        label=node_id,
        evidence=(_evidence(),),
        created_at=T0,
        source="svc",
    )


def sample_graph(*node_ids: str) -> MemoryGraph:
    """A deterministic MemoryGraph with one node per id (no edges). Empty ids ->
    the shared EMPTY_GRAPH."""
    if not node_ids:
        return EMPTY_GRAPH
    return MemoryGraphBuilder().build(nodes=tuple(_node(n) for n in node_ids), as_of=T0).graph


def extend_graph(graph: MemoryGraph, node_id: str) -> MemoryGraph:
    """Return a new graph with one additional node merged in (read-modify-write
    building block for the concurrency tests)."""
    return MemoryGraphBuilder().extend(graph, nodes=(_node(node_id),), as_of=T0).graph
