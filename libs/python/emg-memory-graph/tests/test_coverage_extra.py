"""Targeted tests for remaining branches (undirected lineage, edge merge, bounds)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from _mg_helpers import ASOF, T0, edge_input, ev, node_input
from emg_memory_graph import (
    DecisionLineage,
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    MemoryGraphBuilder,
    TemporalFact,
    TemporalHistory,
    TemporalValidity,
)
from emg_memory_graph.confidence import _dominant_source_type
from emg_memory_graph.limits import MAX_TEMPORAL_INTERVALS
from pydantic import ValidationError

T1 = datetime(2025, 2, 1, tzinfo=timezone.utc)


def test_undirected_lineage_traversal() -> None:
    b = MemoryGraphBuilder()
    e = edge_input("linked", "a", "b").model_copy(update={"direction": EdgeDirection.UNDIRECTED})
    g = b.build(
        nodes=(node_input("a", "x", "A"), node_input("b", "x", "B")), edges=(e,), as_of=ASOF
    ).graph
    lin = DecisionLineage(g)
    assert {n.node_id for n in lin.forward("a").nodes} == {"b"}
    assert {n.node_id for n in lin.backward("a").nodes} == {"b"}


def test_edge_merge_into_base_combines_evidence() -> None:
    b = MemoryGraphBuilder()
    nodes = (node_input("a", "x", "A"), node_input("p", "x", "P"))
    g = b.build(
        nodes=nodes, edges=(edge_input("owns", "a", "p", evidence=(ev("d1"),)),), as_of=ASOF
    ).graph
    # extend with the SAME edge (type+endpoints) carrying new evidence -> merge
    g2 = b.extend(
        g,
        edges=(edge_input("owns", "a", "p", evidence=(ev("d2", EvidenceSource.EMAIL),)),),
        as_of=ASOF,
    ).graph
    assert g2.edge_count == 1
    assert len(g2.edges[0].evidence) == 2


def test_node_label_kept_from_existing_on_extend() -> None:
    b = MemoryGraphBuilder()
    g = b.build(nodes=(node_input("p", "project", "OriginalName"),), as_of=ASOF).graph
    g2 = b.extend(
        g,
        nodes=(node_input("p", "project", "NewName", evidence=(ev("d2", EvidenceSource.EMAIL),)),),
        as_of=ASOF,
    ).graph
    assert g2.node("p").label == "OriginalName"  # type: ignore[union-attr]


def test_dominant_source_type_empty_default() -> None:
    assert _dominant_source_type(()) == "document"


def test_temporal_too_many_intervals_rejected() -> None:
    e = (
        EvidenceRef.create(
            source=EvidenceSource.PDF, locator="l", source_principal="s", captured_at=T0
        ),
    )
    facts = tuple(
        TemporalFact(
            value=str(i),
            validity=TemporalValidity(
                valid_from=datetime(2000 + i, 1, 1, tzinfo=timezone.utc),
                valid_until=datetime(2000 + i, 6, 1, tzinfo=timezone.utc),
            ),
            evidence=e,
            recorded_at=T0,
        )
        for i in range(MAX_TEMPORAL_INTERVALS + 1)
    )
    with pytest.raises(ValidationError):
        TemporalHistory(attribute="owner", facts=facts)


def test_history_with_change_metadata() -> None:
    from emg_memory_graph import Metadata

    e = (
        EvidenceRef.create(
            source=EvidenceSource.PDF, locator="l", source_principal="s", captured_at=T0
        ),
    )
    h = TemporalHistory(attribute="owner").with_change(
        value="a",
        effective_from=T0,
        evidence=e,
        recorded_at=T0,
        metadata=Metadata.from_mapping({"k": "v"}),
    )
    assert h.facts[0].metadata.get("k") == "v"


def test_lineage_between_no_path(lineage_graph) -> None:  # type: ignore[no-untyped-def]
    # appr has no outgoing lineage edge, so no path appr -> req
    assert DecisionLineage(lineage_graph).between("appr", "req") == ()
