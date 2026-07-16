"""Hash-chain integrity / tamper detection (FEAT-04-1). Proves that
out-of-band mutation of a stored event is detected, satisfying US-04's
'no code path can delete or mutate a published event' via detection where
prevention is not absolute (superuser caveat).

Sprint 6 security-review fix (Priority 4): a schema-violating tamper must be
reported as intact=false with a populated first_broken_sequence, never raised
as an unhandled exception."""

from __future__ import annotations

from emg_audit_pipeline import InMemoryAuditEventStore, verify_chain

SP = "emg-svc-identity"


def _seed(store: InMemoryAuditEventStore, make_submitted, n: int = 3) -> None:
    for i in range(n):
        store.append(make_submitted(f"evt-{i}", actor=f"actor-{i}"), source_principal=SP)


def test_tampering_with_a_field_is_detected(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    _seed(store, make_submitted)
    # Simulate an out-of-band mutation: rewrite event 2's actor while leaving
    # its stored event_hash unchanged (as a DB-level tamper would).
    original = store._events[1]  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(1, original.model_copy(update={"actor": "attacker"}))

    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence == 2


def test_tampering_with_the_event_hash_is_detected(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    _seed(store, make_submitted, n=2)
    original = store._events[0]  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(0, original.model_copy(update={"event_hash": "0" * 64}))

    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence == 1


def test_tampering_with_prev_hash_is_detected(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    _seed(store, make_submitted)
    original = store._events[2]  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(2, original.model_copy(update={"prev_hash": "f" * 64}))

    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence == 3


def test_tampering_with_sequence_number_is_detected(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    _seed(store, make_submitted)
    # Rewrite event 2's sequence so ordering is no longer strictly increasing.
    original = store._events[1]  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(1, original.model_copy(update={"sequence_number": 1}))

    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence is not None


def test_deleted_middle_event_breaks_the_chain(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    _seed(store, make_submitted)
    # Simulate deletion of the middle event (seq 2): the surviving list is
    # [1, 3]; event 3's prev_hash no longer matches event 1's hash.
    events = store._events  # type: ignore[attr-defined]
    del events[1]

    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence == 3


def test_schema_violating_tamper_is_reported_not_raised(make_submitted) -> None:
    """A stored record mutated to a schema-invalid value (e.g. an outcome
    outside the allowed set, or a non-datetime timestamp) must be reported as
    an integrity failure, never raise (Priority 4)."""
    store = InMemoryAuditEventStore()
    _seed(store, make_submitted)

    bad_outcome = store._events[1].model_copy(update={"outcome": "hacked"})  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(1, bad_outcome)
    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence == 2
    assert "tamper" in report.detail

    store2 = InMemoryAuditEventStore()
    _seed(store2, make_submitted)
    bad_ts = store2._events[0].model_copy(update={"timestamp": "not-a-datetime"})  # type: ignore[attr-defined]
    store2._unsafe_replace_for_tamper_test(0, bad_ts)
    report2 = store2.verify_integrity()
    assert report2.intact is False
    assert report2.first_broken_sequence == 1


def test_empty_chain_is_intact() -> None:
    report = verify_chain([])
    assert report.intact is True
    assert report.checked_count == 0
