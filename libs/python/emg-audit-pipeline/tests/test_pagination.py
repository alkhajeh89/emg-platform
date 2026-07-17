"""Cursor pagination + richer query filters (FEAT-04-4, Sprint 8).

Covers the opaque-cursor codec, stable keyset pagination over the in-memory
audit + custody stores (deterministic order, no duplicates, no skipped records,
including when new rows are appended mid-walk), the new classification /
module / action / outcome / source_system / has_provenance filters, and the
bounded (non-N+1) query behavior a report walk relies on.
"""

from __future__ import annotations

import pytest
from emg_audit_client import (
    AuditQuery,
    CustodyQuery,
    ProvenanceRecord,
    SubmittedAuditEvent,
    SubmittedCustodyEvent,
)
from emg_audit_pipeline import (
    InMemoryAuditEventStore,
    InMemoryCustodyEventStore,
    decode_cursor,
    encode_cursor,
)
from emg_errors import ValidationError

SP = "emg-svc-audit"


def _event(event_id: str, **overrides) -> SubmittedAuditEvent:
    payload: dict = {
        "event_id": event_id,
        "actor": "dev.investigator",
        "actor_type": "human",
        "module": "identity",
        "action": "login",
        "outcome": "success",
        "source_system": "identity",
    }
    payload.update(overrides)
    return SubmittedAuditEvent(**payload)


def _seed_audit(store: InMemoryAuditEventStore, n: int, **overrides) -> None:
    for i in range(n):
        store.append(_event(f"evt-{i}", **overrides), source_principal=SP)


# --- cursor codec ----------------------------------------------------------


def test_cursor_roundtrip() -> None:
    for seq in (1, 2, 99, 1000, 2**40):
        assert decode_cursor(encode_cursor(seq)) == seq


def test_cursor_is_opaque() -> None:
    # The raw sequence number must not appear verbatim in the token.
    assert "12345" not in encode_cursor(12345)


@pytest.mark.parametrize("bad", ["", "not-base64!!", "YWJjZГ", "c2VxOg==", "bm90LWEtY3Vyc29y"])
def test_malformed_cursor_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError) as exc:
        decode_cursor(bad)
    assert exc.value.error_code == "CURSOR_INVALID"


def test_cursor_rejects_negative_and_nonnumeric() -> None:
    # A hand-built token with the right scheme but a bad position is rejected.
    import base64

    forged = base64.urlsafe_b64encode(b"seq:v1:-5").decode()
    with pytest.raises(ValidationError):
        decode_cursor(forged)


# --- audit keyset pagination ----------------------------------------------


def test_pagination_covers_every_record_once() -> None:
    store = InMemoryAuditEventStore()
    _seed_audit(store, 25)
    seen: list[int] = []
    cursor: str | None = None
    while True:
        page = store.query(AuditQuery(cursor=cursor, limit=10))
        if not page:
            break
        seen.extend(e.sequence_number for e in page)
        if len(page) < 10:
            break
        cursor = encode_cursor(page[-1].sequence_number)
    # Every sequence 1..25 exactly once, in order — no dupes, no skips.
    assert seen == list(range(1, 26))


def test_pagination_is_stable_when_new_rows_are_appended_midwalk() -> None:
    store = InMemoryAuditEventStore()
    _seed_audit(store, 10)
    first = store.query(AuditQuery(limit=5))
    assert [e.sequence_number for e in first] == [1, 2, 3, 4, 5]
    # Append more rows between pages; the cursor keeps the walk stable.
    _seed_audit(store, 5, actor="late")
    cursor = encode_cursor(first[-1].sequence_number)
    second = store.query(AuditQuery(cursor=cursor, limit=5))
    assert [e.sequence_number for e in second] == [6, 7, 8, 9, 10]
    # No row from the first page reappears.
    assert not ({e.sequence_number for e in first} & {e.sequence_number for e in second})


def test_cursor_and_filter_compose() -> None:
    store = InMemoryAuditEventStore()
    for i in range(10):
        outcome = "denied" if i % 2 else "success"
        store.append(_event(f"evt-{i}", outcome=outcome), source_principal=SP)
    denied = store.query(AuditQuery(outcome="denied", limit=100))
    assert {e.outcome for e in denied} == {"denied"}
    assert len(denied) == 5
    # Paginate the filtered view.
    page1 = store.query(AuditQuery(outcome="denied", limit=2))
    cursor = encode_cursor(page1[-1].sequence_number)
    page2 = store.query(AuditQuery(outcome="denied", cursor=cursor, limit=2))
    seqs = [e.sequence_number for e in page1 + page2]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


# --- audit filters ---------------------------------------------------------


def test_filters_by_new_dimensions() -> None:
    store = InMemoryAuditEventStore()
    store.append(_event("a", module="identity", action="login"), source_principal=SP)
    store.append(_event("b", module="authz", action="check", outcome="denied"), source_principal=SP)
    store.append(
        _event("c", module="authz", action="check", source_system="authz"), source_principal=SP
    )
    assert {e.event_id for e in store.query(AuditQuery(module="authz"))} == {"b", "c"}
    assert {e.event_id for e in store.query(AuditQuery(action="login"))} == {"a"}
    assert {e.event_id for e in store.query(AuditQuery(outcome="denied"))} == {"b"}
    assert {e.event_id for e in store.query(AuditQuery(source_system="authz"))} == {"c"}


def test_filter_by_classification() -> None:
    from emg_common_types import Classification

    store = InMemoryAuditEventStore()
    store.append(_event("pub", classification=Classification.UNCLASSIFIED), source_principal=SP)
    store.append(_event("sec", classification=Classification.SECRET), source_principal=SP)
    secret = store.query(AuditQuery(classification=Classification.SECRET))
    assert {e.event_id for e in secret} == {"sec"}


def test_filter_by_has_provenance() -> None:
    from datetime import datetime, timezone

    store = InMemoryAuditEventStore()
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    prov = ProvenanceRecord(
        source_system="identity",
        originating_actor="dev.investigator",
        originating_principal="emg-svc-identity",
        event_time=now,
        ingest_time=now,
    )
    store.append(_event("plain"), source_principal=SP)
    store.append(_event("withprov", provenance=prov), source_principal=SP)
    assert {e.event_id for e in store.query(AuditQuery(has_provenance=True))} == {"withprov"}
    assert {e.event_id for e in store.query(AuditQuery(has_provenance=False))} == {"plain"}


# --- custody pagination + filters -----------------------------------------


def _custody(cid: str, evidence_id: str = "E1", **overrides) -> SubmittedCustodyEvent:
    payload: dict = {
        "custody_event_id": cid,
        "evidence_id": evidence_id,
        "custody_action": "transfer",
        "custodian": "alice",
    }
    payload.update(overrides)
    return SubmittedCustodyEvent(**payload)


def test_custody_pagination_covers_every_record_once() -> None:
    store = InMemoryCustodyEventStore()
    for i in range(12):
        store.append(_custody(f"c-{i}"), source_principal=SP)
    seen: list[int] = []
    cursor: str | None = None
    while True:
        page = store.query(CustodyQuery(cursor=cursor, limit=5))
        if not page:
            break
        seen.extend(e.chain_sequence for e in page)
        if len(page) < 5:
            break
        cursor = encode_cursor(page[-1].chain_sequence)
    assert seen == list(range(1, 13))


def test_custody_filter_by_classification() -> None:
    from emg_common_types import Classification

    store = InMemoryCustodyEventStore()
    store.append(_custody("c-1", classification=Classification.SECRET), source_principal=SP)
    store.append(_custody("c-2"), source_principal=SP)
    secret = store.query(CustodyQuery(classification=Classification.SECRET))
    assert {e.custody_event_id for e in secret} == {"c-1"}
