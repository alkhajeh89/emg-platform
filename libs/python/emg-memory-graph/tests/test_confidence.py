"""Confidence engine (Deliverable 7)."""

from __future__ import annotations

from datetime import datetime, timezone

from emg_memory_graph import (
    ConfidenceBand,
    ConfidenceEngine,
    ConfidencePolicy,
    EvidenceRef,
    EvidenceSource,
)

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def _ev(loc: str, src: EvidenceSource = EvidenceSource.PDF) -> EvidenceRef:
    return EvidenceRef.create(
        source=src, locator=loc, source_principal="svc", captured_at=T0, event_id="e-" + loc
    )


def test_multiple_sources_higher_than_single() -> None:
    eng = ConfidenceEngine()
    single = eng.assess((_ev("a"),), as_of=T0)
    multi = eng.assess(
        (_ev("a"), _ev("b", EvidenceSource.EMAIL), _ev("c", EvidenceSource.JIRA)), as_of=T0
    )
    assert multi.score > single.score
    assert single.distinct_source_count == 1
    assert multi.distinct_source_count == 3


def test_conflict_reduces_and_bands_conflicted() -> None:
    eng = ConfidenceEngine()
    clean = eng.assess((_ev("a"), _ev("b", EvidenceSource.EMAIL)), as_of=T0)
    conflict = eng.assess((_ev("a"), _ev("b", EvidenceSource.EMAIL)), as_of=T0, conflict_count=2)
    assert conflict.score < clean.score
    assert conflict.band is ConfidenceBand.CONFLICTED
    assert conflict.conflict_count == 2


def test_deterministic() -> None:
    eng = ConfidenceEngine()
    a = eng.assess((_ev("a"),), as_of=T0)
    b = eng.assess((_ev("a"),), as_of=T0)
    assert a.model_dump() == b.model_dump()


def test_bands_high_medium_low() -> None:
    eng = ConfidenceEngine(ConfidencePolicy(high_band=0.9, medium_band=0.6))
    assert eng._band(0.95, 0, 3) is ConfidenceBand.HIGH  # noqa: SLF001
    assert eng._band(0.7, 0, 3) is ConfidenceBand.MEDIUM  # noqa: SLF001
    assert eng._band(0.3, 0, 3) is ConfidenceBand.LOW  # noqa: SLF001


def test_explanation_present() -> None:
    a = ConfidenceEngine().assess((_ev("a"),), as_of=T0)
    assert "composite=" in a.explanation
    assert a.trust.score == a.score


def test_manual_entry_source_type() -> None:
    a = ConfidenceEngine().assess((_ev("a", EvidenceSource.MANUAL_ENTRY),), as_of=T0)
    assert 0.0 <= a.score <= 1.0
