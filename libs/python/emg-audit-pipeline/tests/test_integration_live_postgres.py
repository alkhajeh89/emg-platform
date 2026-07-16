"""Opt-in PostgreSQL append-only + concurrency integration test (FEAT-04-1).

Skipped by default (no database in unit-test CI). Run it against a real local
Postgres created by docker-compose + tools/seed-data/postgres/001_audit_events.sql:

    docker compose up -d postgres
    export EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS=1
    export EMG_AUDIT_TEST_POSTGRES_DSN="postgresql://emg_audit_app:\
emg_audit_local_dev_only_do_not_use_in_prod@localhost:5432/emg"
    pytest libs/python/emg-audit-pipeline/tests/test_integration_live_postgres.py

It proves, against the real append-only table and INSERT/SELECT-only role:
persistence + readback, centralized sequence/hash assignment, per-principal
event_id idempotency, integrity verification, that the application role cannot
UPDATE or DELETE a published event, and — Sprint 6 security-review fix,
Priority 1 — that many CONCURRENT appends (each on its own connection) all
succeed with unique + contiguous sequence numbers, a single valid hash chain,
and no unhandled database exception.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from emg_audit_client import AuditQuery, SubmittedAuditEvent

_RUN = os.environ.get("EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS") == "1"
_DSN = os.environ.get("EMG_AUDIT_TEST_POSTGRES_DSN", "")
_SP = "emg-svc-identity"

pytestmark = pytest.mark.skipif(
    not _RUN, reason="set EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS=1 (and a DSN) to run"
)


def _submitted(event_id: str, actor: str = "dev.investigator") -> SubmittedAuditEvent:
    return SubmittedAuditEvent(
        event_id=event_id,
        actor=actor,
        actor_type="human",
        module="identity",
        action="login",
        outcome="success",
        correlation_id="corr-1",
        source_system="identity",
    )


@pytest.fixture
def store():
    import psycopg
    from emg_audit_pipeline import PostgresAuditEventStore

    conn = psycopg.connect(_DSN)
    yield PostgresAuditEventStore(conn)
    conn.close()


def test_persist_and_readback(store):
    eid = f"evt-{uuid.uuid4()}"
    persisted = store.append(_submitted(eid), source_principal=_SP)
    assert persisted.sequence_number >= 1
    assert persisted.source_principal == _SP
    assert len(persisted.event_hash) == 64
    results = store.query(AuditQuery(correlation_id="corr-1", limit=1000))
    assert any(e.event_id == eid for e in results)


def test_idempotent_by_principal_and_event_id(store):
    eid = f"evt-{uuid.uuid4()}"
    first = store.append(_submitted(eid, actor="alice"), source_principal=_SP)
    second = store.append(_submitted(eid, actor="bob"), source_principal=_SP)
    assert first.event_hash == second.event_hash
    assert first.actor == "alice"


def test_different_principals_same_event_id_distinct(store):
    eid = f"evt-{uuid.uuid4()}"
    a = store.append(_submitted(eid, actor="a"), source_principal="emg-svc-identity")
    b = store.append(_submitted(eid, actor="b"), source_principal="emg-svc-authorization")
    assert a.sequence_number != b.sequence_number
    assert a.event_hash != b.event_hash


def test_integrity_intact(store):
    for _ in range(3):
        store.append(_submitted(f"evt-{uuid.uuid4()}"), source_principal=_SP)
    report = store.verify_integrity()
    assert report.intact is True


def test_application_role_cannot_update_or_delete(store):
    """Append-only at the DB layer: the INSERT/SELECT-only application role
    must be denied UPDATE and DELETE."""
    import psycopg

    eid = f"evt-{uuid.uuid4()}"
    store.append(_submitted(eid), source_principal=_SP)
    conn = psycopg.connect(_DSN)
    try:
        with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE audit_events SET actor = 'x' WHERE event_id = %s", (eid,))
        conn.rollback()
        with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM audit_events WHERE event_id = %s", (eid,))
        conn.rollback()
    finally:
        conn.close()


def test_concurrent_appends_are_serialized_without_forking_the_chain():
    """Priority 1: many concurrent appends, each on its own connection, all
    succeed; sequence numbers are unique and contiguous over the batch; exactly
    one valid hash chain results; and no append raises an unhandled DB
    exception."""
    import psycopg
    from emg_audit_pipeline import PostgresAuditEventStore

    n = 25
    correlation = f"concurrency-{uuid.uuid4()}"

    def _one(i: int) -> int:
        conn = psycopg.connect(_DSN)
        try:
            store = PostgresAuditEventStore(conn)
            event = SubmittedAuditEvent(
                event_id=f"evt-{uuid.uuid4()}",
                actor=f"actor-{i}",
                actor_type="service",
                module="identity",
                action="concurrent_append",
                outcome="success",
                correlation_id=correlation,
                source_system="identity",
            )
            persisted = store.append(event, source_principal=_SP)
            return persisted.sequence_number
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=n) as pool:
        sequence_numbers = list(pool.map(_one, range(n)))

    # All appends succeeded (no unhandled exception propagated out of map).
    assert len(sequence_numbers) == n
    # Sequence numbers assigned to this batch are unique.
    assert len(set(sequence_numbers)) == n
    # ...and contiguous over the batch (no gaps within the range they occupy).
    lo, hi = min(sequence_numbers), max(sequence_numbers)
    assert set(sequence_numbers) == set(range(lo, hi + 1))

    # Exactly one valid hash chain over the whole store.
    verify_conn = psycopg.connect(_DSN)
    try:
        report = PostgresAuditEventStore(verify_conn).verify_integrity()
    finally:
        verify_conn.close()
    assert report.intact is True
