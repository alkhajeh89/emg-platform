"""Temporal memory: validity intervals + never-overwrite histories (Deliverable 4)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_memory_graph import (
    EvidenceRef,
    EvidenceSource,
    TemporalFact,
    TemporalHistory,
    TemporalValidity,
)
from pydantic import ValidationError

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2025, 2, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 1, tzinfo=timezone.utc)
EV = (
    EvidenceRef.create(
        source=EvidenceSource.PDF, locator="l", source_principal="s", captured_at=T0
    ),
)


def test_validity_contains_open_and_closed() -> None:
    closed = TemporalValidity(valid_from=T0, valid_until=T1)
    assert closed.contains(T0)
    assert not closed.contains(T1)  # half-open
    assert not closed.contains(datetime(2023, 1, 1, tzinfo=timezone.utc))
    open_iv = TemporalValidity(valid_from=T0)
    assert open_iv.is_open
    assert open_iv.contains(T2)


def test_validity_rejects_inverted() -> None:
    with pytest.raises(ValidationError):
        TemporalValidity(valid_from=T1, valid_until=T0)


def test_validity_overlaps() -> None:
    a = TemporalValidity(valid_from=T0, valid_until=T1)
    b = TemporalValidity(valid_from=datetime(2024, 6, 1, tzinfo=timezone.utc), valid_until=T2)
    c = TemporalValidity(valid_from=T1, valid_until=T2)  # adjacent, no overlap
    assert a.overlaps(b)
    assert not a.overlaps(c)
    assert TemporalValidity(valid_from=T0).overlaps(TemporalValidity(valid_from=T1))


def test_history_never_overwrites_and_reconstructs() -> None:
    h = TemporalHistory(attribute="owner").with_change(
        value="ahmed", effective_from=T0, evidence=EV, recorded_at=T0
    )
    h2 = h.with_change(value="mohammed", effective_from=T1, evidence=EV, recorded_at=T1)
    # original history object is unchanged (immutability)
    assert len(h.facts) == 1 and h.facts[0].validity.is_open
    # reconstructed timeline
    a = h2.as_of(datetime(2024, 6, 1, tzinfo=timezone.utc))
    assert a is not None
    assert a.value == "ahmed"
    m = h2.as_of(datetime(2025, 6, 1, tzinfo=timezone.utc))
    assert m is not None
    assert m.value == "mohammed"
    assert h2.current(T2).value == "mohammed"
    assert len(h2.timeline()) == 2


def test_history_as_of_before_start_is_none() -> None:
    h = TemporalHistory(attribute="owner").with_change(
        value="ahmed", effective_from=T1, evidence=EV, recorded_at=T1
    )
    assert h.as_of(T0) is None


def test_history_rejects_overlapping_intervals() -> None:
    f1 = TemporalFact(
        value="a",
        validity=TemporalValidity(valid_from=T0, valid_until=T2),
        evidence=EV,
        recorded_at=T0,
    )
    f2 = TemporalFact(
        value="b",
        validity=TemporalValidity(valid_from=T1, valid_until=T2),
        evidence=EV,
        recorded_at=T1,
    )
    with pytest.raises(ValidationError):
        TemporalHistory(attribute="owner", facts=(f1, f2))


def test_history_only_last_open() -> None:
    f1 = TemporalFact(
        value="a", validity=TemporalValidity(valid_from=T0), evidence=EV, recorded_at=T0
    )
    f2 = TemporalFact(
        value="b", validity=TemporalValidity(valid_from=T1), evidence=EV, recorded_at=T1
    )
    with pytest.raises(ValidationError):
        TemporalHistory(attribute="owner", facts=(f1, f2))


def test_fact_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        TemporalFact(
            value="a", validity=TemporalValidity(valid_from=T0), evidence=(), recorded_at=T0
        )
