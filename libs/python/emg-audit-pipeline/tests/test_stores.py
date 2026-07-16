"""InMemoryAuditEventStore behavior (FEAT-04-1): append-only, centralized
sequencing + chaining, US-04 queries, and per-principal event_id idempotency
(Sprint 6 security-review fix, Priority 5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from emg_audit_client import AuditQuery
from emg_audit_pipeline import GENESIS_PREV_HASH, InMemoryAuditEventStore

SP = "emg-svc-identity"  # a representative authenticated producer principal


def test_append_assigns_server_side_fields(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    persisted = store.append(make_submitted("evt-1"), source_principal=SP)
    assert persisted.sequence_number == 1
    assert persisted.source_principal == SP
    assert persisted.prev_hash == GENESIS_PREV_HASH
    assert len(persisted.event_hash) == 64
    assert persisted.timestamp.tzinfo is not None  # UTC-aware, server-assigned
    assert persisted.ingest_time.tzinfo is not None


def test_sequence_is_monotonic_and_chain_links(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    first = store.append(make_submitted("evt-1"), source_principal=SP)
    second = store.append(make_submitted("evt-2"), source_principal=SP)
    third = store.append(make_submitted("evt-3"), source_principal=SP)
    assert [first.sequence_number, second.sequence_number, third.sequence_number] == [1, 2, 3]
    # each event's prev_hash chains to the previous event's hash
    assert second.prev_hash == first.event_hash
    assert third.prev_hash == second.event_hash


def test_append_is_idempotent_by_principal_and_event_id(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    first = store.append(make_submitted("evt-dup", actor="a"), source_principal=SP)
    # Same principal re-submitting the same event_id (even with different
    # content) is a no-op and returns the original persisted record.
    again = store.append(make_submitted("evt-dup", actor="b"), source_principal=SP)
    assert again.event_hash == first.event_hash
    assert again.actor == "a"
    assert store.query(AuditQuery()) == [first]


def test_different_principals_same_event_id_are_distinct_events(make_submitted) -> None:
    """P5: one producer cannot suppress another's event by reusing its
    event_id — different source_principals with the same event_id create two
    distinct, separately-sequenced events."""
    store = InMemoryAuditEventStore()
    a = store.append(make_submitted("shared-id", actor="a"), source_principal="emg-svc-identity")
    b = store.append(
        make_submitted("shared-id", actor="b"), source_principal="emg-svc-authorization"
    )
    assert a.sequence_number == 1
    assert b.sequence_number == 2
    assert a.event_hash != b.event_hash
    assert len(store.query(AuditQuery())) == 2


def test_store_has_no_mutation_or_delete_api() -> None:
    store = InMemoryAuditEventStore()
    public = {name for name in dir(store) if not name.startswith("_")}
    assert public == {"append", "query", "verify_integrity"}
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_query_by_actor(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    store.append(make_submitted("evt-1", actor="alice"), source_principal=SP)
    store.append(make_submitted("evt-2", actor="bob"), source_principal=SP)
    results = store.query(AuditQuery(actor="alice"))
    assert [e.event_id for e in results] == ["evt-1"]


def test_query_by_correlation_id(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    store.append(make_submitted("evt-1", correlation_id="corr-A"), source_principal=SP)
    store.append(make_submitted("evt-2", correlation_id="corr-B"), source_principal=SP)
    results = store.query(AuditQuery(correlation_id="corr-B"))
    assert [e.event_id for e in results] == ["evt-2"]


def test_query_by_time_range(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    e1 = store.append(make_submitted("evt-1"), source_principal=SP)
    store.append(make_submitted("evt-2"), source_principal=SP)
    # start_time inclusive, end_time exclusive
    just_after = e1.timestamp + timedelta(microseconds=1)
    results = store.query(AuditQuery(start_time=just_after))
    assert [e.event_id for e in results] == ["evt-2"]

    far_future = datetime.now(timezone.utc) + timedelta(days=1)
    assert store.query(AuditQuery(start_time=far_future)) == []


def test_query_limit(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    for i in range(5):
        store.append(make_submitted(f"evt-{i}"), source_principal=SP)
    assert len(store.query(AuditQuery(limit=3))) == 3


def test_freshly_built_store_verifies_intact(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    for i in range(3):
        store.append(make_submitted(f"evt-{i}"), source_principal=SP)
    report = store.verify_integrity()
    assert report.intact is True
    assert report.checked_count == 3
    assert report.first_broken_sequence is None
