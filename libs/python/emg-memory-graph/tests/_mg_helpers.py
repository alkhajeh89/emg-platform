"""Shared test builders (importable under pytest importlib mode via conftest's
sys.path insertion). Fixtures live in conftest.py; reusable constructors here."""

from __future__ import annotations

from datetime import datetime, timezone

from emg_memory_graph import (
    EdgeInput,
    EvidenceRef,
    EvidenceSource,
    NodeInput,
    TemporalValidity,
)

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
MID = datetime(2025, 2, 1, tzinfo=timezone.utc)
ASOF = datetime(2024, 6, 1, tzinfo=timezone.utc)


def ev(
    locator: str,
    source: EvidenceSource = EvidenceSource.PDF,
    *,
    captured_at: datetime = T0,
    principal: str = "svc-ingest",
    with_audit: bool = True,
) -> EvidenceRef:
    return EvidenceRef.create(
        source=source,
        locator=locator,
        source_principal=principal,
        captured_at=captured_at,
        event_id=("evt-" + locator) if with_audit else None,
        correlation_id=("corr-" + locator) if with_audit else None,
    )


def node_input(
    node_id: str,
    node_type: str,
    label: str,
    *,
    evidence: tuple[EvidenceRef, ...] | None = None,
    created_at: datetime = T0,
    conflict_count: int = 0,
) -> NodeInput:
    return NodeInput(
        node_id=node_id,
        node_type=node_type,
        label=label,
        evidence=evidence or (ev(node_id),),
        created_at=created_at,
        source="svc-ingest",
        conflict_count=conflict_count,
    )


def edge_input(
    edge_type: str,
    source_id: str,
    target_id: str,
    *,
    evidence: tuple[EvidenceRef, ...] | None = None,
    valid_from: datetime = T0,
    valid_until: datetime | None = None,
    created_at: datetime = T0,
) -> EdgeInput:
    return EdgeInput(
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        evidence=evidence or (ev(f"{source_id}-{target_id}"),),
        validity=TemporalValidity(valid_from=valid_from, valid_until=valid_until),
        created_at=created_at,
    )
