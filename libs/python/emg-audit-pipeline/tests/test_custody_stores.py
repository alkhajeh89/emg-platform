"""InMemoryCustodyEventStore behavior (FEAT-04-3): append-only, centralized
global + per-evidence sequencing, hash-chain links, custody queries, and
per-principal idempotency isolation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from emg_audit_client import CustodyQuery, SubmittedCustodyEvent
from emg_audit_pipeline import GENESIS_PREV_HASH, InMemoryCustodyEventStore
from emg_errors import ValidationError

SP = "emg-svc-audit"


def _custody(
    custody_event_id: str = "c-1",
    *,
    evidence_id: str = "E1",
    custody_action: str = "transfer",
    custodian: str = "alice",
    prior_custodian: str | None = None,
    transfer_reason: str = "handoff",
    metadata: dict[str, str] | None = None,
) -> SubmittedCustodyEvent:
    return SubmittedCustodyEvent(
        custody_event_id=custody_event_id,
        evidence_id=evidence_id,
        custody_action=custody_action,  # type: ignore[arg-type]
        custodian=custodian,
        prior_custodian=prior_custodian,
        transfer_reason=transfer_reason,
        correlation_id="corr-1",
        metadata=metadata or {},
    )


def test_append_assigns_server_side_fields() -> None:
    store = InMemoryCustodyEventStore()
    e = store.append(_custody("c-1", custody_action="acquire"), source_principal=SP)
    assert e.chain_sequence == 1
    assert e.custody_sequence == 1
    assert e.source_principal == SP
    assert e.prev_hash == GENESIS_PREV_HASH
    assert len(e.event_hash) == 64
    assert e.transfer_timestamp.tzinfo is not None
    assert e.ingest_time.tzinfo is not None


def test_global_chain_sequence_is_monotonic_and_links() -> None:
    store = InMemoryCustodyEventStore()
    a = store.append(
        _custody("c-1", evidence_id="E1", custody_action="acquire"), source_principal=SP
    )
    b = store.append(
        _custody("c-2", evidence_id="E2", custody_action="acquire"), source_principal=SP
    )
    c = store.append(_custody("c-3", evidence_id="E1", custodian="carol"), source_principal=SP)
    assert [a.chain_sequence, b.chain_sequence, c.chain_sequence] == [1, 2, 3]
    assert b.prev_hash == a.event_hash
    assert c.prev_hash == b.event_hash


def test_per_evidence_custody_sequence_is_independent() -> None:
    store = InMemoryCustodyEventStore()
    a1 = store.append(
        _custody("c-1", evidence_id="E1", custody_action="acquire"), source_principal=SP
    )
    b1 = store.append(
        _custody("c-2", evidence_id="E2", custody_action="acquire"), source_principal=SP
    )
    a2 = store.append(_custody("c-3", evidence_id="E1"), source_principal=SP)
    a3 = store.append(_custody("c-4", evidence_id="E1"), source_principal=SP)
    b2 = store.append(_custody("c-5", evidence_id="E2"), source_principal=SP)
    assert [a1.custody_sequence, a2.custody_sequence, a3.custody_sequence] == [1, 2, 3]
    assert [b1.custody_sequence, b2.custody_sequence] == [1, 2]


def test_append_is_idempotent_by_principal_and_custody_event_id() -> None:
    store = InMemoryCustodyEventStore()
    first = store.append(_custody("dup", custodian="alice"), source_principal=SP)
    again = store.append(_custody("dup", custodian="someone-else"), source_principal=SP)
    assert again.event_hash == first.event_hash
    assert again.custodian == "alice"
    assert len(store.query(CustodyQuery())) == 1


def test_different_principals_same_custody_event_id_are_distinct() -> None:
    """Cross-principal idempotency isolation: one producer cannot suppress
    another's custody record by reusing its custody_event_id."""
    store = InMemoryCustodyEventStore()
    a = store.append(_custody("shared", evidence_id="E1"), source_principal="emg-svc-audit")
    b = store.append(_custody("shared", evidence_id="E9"), source_principal="emg-svc-identity")
    assert a.chain_sequence == 1 and b.chain_sequence == 2
    assert a.event_hash != b.event_hash
    assert len(store.query(CustodyQuery())) == 2


def test_source_principal_is_not_producer_supplied() -> None:
    """SubmittedCustodyEvent has no source_principal / chain fields — the store
    assigns them. This structurally prevents a producer forging chain state."""
    fields = set(SubmittedCustodyEvent.model_fields)
    for forbidden in {
        "source_principal",
        "chain_sequence",
        "custody_sequence",
        "transfer_timestamp",
        "ingest_time",
        "prev_hash",
        "event_hash",
    }:
        assert forbidden not in fields


def test_store_has_no_mutation_or_delete_api() -> None:
    store = InMemoryCustodyEventStore()
    public = {name for name in dir(store) if not name.startswith("_")}
    assert public == {"append", "query", "verify_integrity"}
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_query_by_evidence_and_custodian() -> None:
    store = InMemoryCustodyEventStore()
    store.append(_custody("c-1", evidence_id="E1", custodian="alice"), source_principal=SP)
    store.append(_custody("c-2", evidence_id="E2", custodian="bob"), source_principal=SP)
    store.append(_custody("c-3", evidence_id="E1", custodian="carol"), source_principal=SP)
    assert [e.custody_event_id for e in store.query(CustodyQuery(evidence_id="E1"))] == [
        "c-1",
        "c-3",
    ]
    assert [e.custody_event_id for e in store.query(CustodyQuery(custodian="bob"))] == ["c-2"]


def test_query_by_time_range_and_limit() -> None:
    store = InMemoryCustodyEventStore()
    first = store.append(_custody("c-1"), source_principal=SP)
    store.append(_custody("c-2"), source_principal=SP)
    just_after = first.transfer_timestamp + timedelta(microseconds=1)
    assert [e.custody_event_id for e in store.query(CustodyQuery(start_time=just_after))] == ["c-2"]
    far_future = datetime.now(timezone.utc) + timedelta(days=1)
    assert store.query(CustodyQuery(start_time=far_future)) == []
    for i in range(5):
        store.append(_custody(f"x-{i}"), source_principal=SP)
    assert len(store.query(CustodyQuery(limit=3))) == 3


def test_oversized_reason_is_rejected() -> None:
    store = InMemoryCustodyEventStore()
    with pytest.raises(ValidationError) as exc:
        store.append(_custody("c-1", transfer_reason="x" * 5000), source_principal=SP)
    assert exc.value.error_code == "CUSTODY_REASON_TOO_LONG"


def test_sensitive_custody_metadata_key_is_rejected() -> None:
    store = InMemoryCustodyEventStore()
    with pytest.raises(ValidationError) as exc:
        store.append(_custody("c-1", metadata={"password": "hunter2"}), source_principal=SP)
    assert exc.value.error_code == "CUSTODY_METADATA_SENSITIVE_KEY"


def test_freshly_built_ledger_verifies_intact() -> None:
    store = InMemoryCustodyEventStore()
    store.append(_custody("c-1", evidence_id="E1", custody_action="acquire"), source_principal=SP)
    store.append(
        _custody("c-2", evidence_id="E1", custodian="bob", prior_custodian="alice"),
        source_principal=SP,
    )
    report = store.verify_integrity()
    assert report.intact is True
    assert report.checked_count == 2
    assert report.first_broken_sequence is None
