"""Custody chain integrity (FEAT-04-3): detection of mutation, deletion,
global-chain sequence breaks, per-evidence sequence gaps, and schema-violating
stored rows — always as an explicit failure result, never a raised exception."""

from __future__ import annotations

from datetime import datetime, timezone

from emg_audit_client import CustodyEvent, SubmittedCustodyEvent
from emg_audit_pipeline import (
    GENESIS_PREV_HASH,
    InMemoryCustodyEventStore,
    compute_custody_hash,
    verify_custody_chain,
)

SP = "emg-svc-audit"


def _custody(cid: str, evidence_id: str = "E1", custodian: str = "alice") -> SubmittedCustodyEvent:
    return SubmittedCustodyEvent(
        custody_event_id=cid,
        evidence_id=evidence_id,
        custody_action="transfer",
        custodian=custodian,
        transfer_reason="handoff",
    )


def _seed(store: InMemoryCustodyEventStore, n: int, evidence_id: str = "E1") -> None:
    for i in range(n):
        store.append(
            _custody(f"c-{i}", evidence_id=evidence_id, custodian=f"h{i}"), source_principal=SP
        )


def test_intact_chain_reports_intact() -> None:
    store = InMemoryCustodyEventStore()
    _seed(store, 3)
    assert store.verify_integrity().intact is True


def test_mutation_is_detected() -> None:
    store = InMemoryCustodyEventStore()
    _seed(store, 3)
    original = store._events[1]  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(1, original.model_copy(update={"custodian": "MALLORY"}))
    report = store.verify_integrity()
    assert report.intact is False
    assert "mutated" in report.detail


def test_deleted_middle_event_breaks_the_chain() -> None:
    store = InMemoryCustodyEventStore()
    _seed(store, 3)
    store._unsafe_delete_for_tamper_test(1)  # delete the middle custody event
    report = store.verify_integrity()
    assert report.intact is False


def test_non_increasing_global_sequence_is_detected() -> None:
    """A reordered / duplicated global chain_sequence is rejected."""
    store = InMemoryCustodyEventStore()
    _seed(store, 2)
    dup = store._events[1].model_copy(update={"chain_sequence": 1})  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(1, dup)
    report = store.verify_integrity()
    assert report.intact is False


def test_per_evidence_sequence_gap_is_detected() -> None:
    """Construct a chain that is globally hash-valid but has a per-evidence
    custody_sequence gap (1, 3 for one evidence item) — the per-evidence gap
    detector must catch it even though the global chain links are intact."""
    ts = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def build(chain_seq: int, custody_seq: int, prev_hash: str, cid: str) -> CustodyEvent:
        submitted = _custody(cid, evidence_id="E1", custodian=f"h{custody_seq}")
        event_hash = compute_custody_hash(
            custody_event_id=cid,
            source_principal=SP,
            chain_sequence=chain_seq,
            custody_sequence=custody_seq,
            transfer_timestamp=ts,
            ingest_time=ts,
            submitted=submitted,
            prev_hash=prev_hash,
        )
        return CustodyEvent(
            custody_event_id=cid,
            source_principal=SP,
            chain_sequence=chain_seq,
            custody_sequence=custody_seq,
            transfer_timestamp=ts,
            ingest_time=ts,
            prev_hash=prev_hash,
            event_hash=event_hash,
            evidence_id="E1",
            custody_action="transfer",
            custodian=f"h{custody_seq}",
            transfer_reason="handoff",
        )

    e1 = build(1, 1, GENESIS_PREV_HASH, "c-1")
    e2 = build(2, 3, e1.event_hash, "c-2")  # custody_sequence jumps 1 -> 3 (gap at 2)
    report = verify_custody_chain([e1, e2])
    assert report.intact is False
    assert "gap" in report.detail


def test_schema_violating_row_is_reported_not_raised() -> None:
    """A stored custody row whose fields cannot re-hash (e.g. via the Postgres
    verify path parsing a tampered row) is reported as intact=false, never a
    raised 500. Exercised here through the in-memory verifier with a record
    whose stored hash cannot match any recomputation."""
    store = InMemoryCustodyEventStore()
    _seed(store, 2)
    broken = store._events[1].model_copy(update={"event_hash": "not-a-real-hash"})  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(1, broken)
    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence == 2
