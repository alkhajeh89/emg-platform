"""Evidence references + integrity (FEAT-05-6, Deliverable 6)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_memory_graph import EvidenceRef, EvidenceSource
from emg_ontology import ProvenanceReference
from pydantic import ValidationError

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_create_is_deterministic() -> None:
    a = EvidenceRef.create(
        source=EvidenceSource.EMAIL, locator="msg-1", source_principal="svc", captured_at=T0
    )
    b = EvidenceRef.create(
        source=EvidenceSource.EMAIL, locator="msg-1", source_principal="svc", captured_at=T0
    )
    assert a.evidence_id == b.evidence_id
    assert a.evidence_id.startswith("ev-")


def test_distinct_source_or_locator_distinct_id() -> None:
    a = EvidenceRef.create(
        source=EvidenceSource.EMAIL, locator="x", source_principal="s", captured_at=T0
    )
    b = EvidenceRef.create(
        source=EvidenceSource.PDF, locator="x", source_principal="s", captured_at=T0
    )
    c = EvidenceRef.create(
        source=EvidenceSource.EMAIL, locator="y", source_principal="s", captured_at=T0
    )
    assert len({a.evidence_id, b.evidence_id, c.evidence_id}) == 3


def test_all_supported_sources() -> None:
    for src in EvidenceSource:
        e = EvidenceRef.create(source=src, locator="l", source_principal="s", captured_at=T0)
        assert e.source is src


def test_from_provenance_bridges_audit_trail() -> None:
    prov = ProvenanceReference(
        source_principal="svc-ingest", event_id="evt-9", correlation_id="corr-9"
    )
    e = EvidenceRef.from_provenance(
        prov, source=EvidenceSource.SHAREPOINT, locator="doc-1", captured_at=T0
    )
    assert e.source_principal == "svc-ingest"
    assert e.event_id == "evt-9"
    assert e.correlation_id == "corr-9"
    assert e.source is EvidenceSource.SHAREPOINT


def test_evidence_is_immutable() -> None:
    e = EvidenceRef.create(
        source=EvidenceSource.PDF, locator="l", source_principal="s", captured_at=T0
    )
    with pytest.raises(ValidationError):
        e.locator = "other"  # type: ignore[misc]


def test_control_char_locator_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef.create(
            source=EvidenceSource.PDF, locator="bad\x00", source_principal="s", captured_at=T0
        )
