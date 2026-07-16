"""Opt-in PostgreSQL custody-ledger + provenance-migration integration test
(FEAT-04-2, FEAT-04-3).

Skipped by default (no database in unit-test CI). Run against a real local
Postgres created by docker-compose + the tools/seed-data/postgres/*.sql scripts
(001 then 002 then 003, in filename order):

    docker compose up -d postgres
    export EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS=1
    export EMG_AUDIT_TEST_POSTGRES_DSN="postgresql://emg_audit_app:\
emg_audit_local_dev_only_do_not_use_in_prod@localhost:5432/emg"
    pytest libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_custody.py

It proves, against the real append-only custody table and INSERT/SELECT-only
role: persistence + readback, centralized global + per-evidence sequencing,
per-principal idempotency, integrity, that the application role cannot UPDATE or
DELETE a published custody event, and — FEAT-04-3 — that many CONCURRENT custody
appends (each on its own connection) all succeed with unique + contiguous global
sequence numbers, a single valid hash chain, and no unhandled DB exception. It
also proves the FEAT-04-2 provenance migration is backward compatible: a
version-2 audit event with provenance persists and re-verifies, and a version-1
event (no provenance) still verifies intact alongside it.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from emg_audit_client import (
    CustodyQuery,
    ProvenanceRecord,
    SubmittedAuditEvent,
    SubmittedCustodyEvent,
)

_RUN = os.environ.get("EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS") == "1"
_DSN = os.environ.get("EMG_AUDIT_TEST_POSTGRES_DSN", "")
_SP = "emg-svc-audit"

pytestmark = pytest.mark.skipif(
    not _RUN, reason="set EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS=1 (and a DSN) to run"
)


def _custody(cid: str, evidence_id: str = "E1", custodian: str = "alice") -> SubmittedCustodyEvent:
    return SubmittedCustodyEvent(
        custody_event_id=cid,
        evidence_id=evidence_id,
        custody_action="transfer",
        custodian=custodian,
        transfer_reason="handoff",
        correlation_id="corr-1",
    )


@pytest.fixture
def custody_store():
    import psycopg
    from emg_audit_pipeline import PostgresCustodyEventStore

    conn = psycopg.connect(_DSN)
    yield PostgresCustodyEventStore(conn)
    conn.close()


def test_custody_persist_and_readback(custody_store):
    eid = f"E-{uuid.uuid4()}"
    a = custody_store.append(
        _custody(f"c-{uuid.uuid4()}", evidence_id=eid, custodian="alice"), source_principal=_SP
    )
    b = custody_store.append(
        _custody(f"c-{uuid.uuid4()}", evidence_id=eid, custodian="bob"), source_principal=_SP
    )
    assert a.custody_sequence == 1 and b.custody_sequence == 2
    results = custody_store.query(CustodyQuery(evidence_id=eid, limit=1000))
    assert {e.custodian for e in results} == {"alice", "bob"}


def test_custody_idempotent_by_principal(custody_store):
    cid = f"c-{uuid.uuid4()}"
    first = custody_store.append(_custody(cid, custodian="alice"), source_principal=_SP)
    second = custody_store.append(_custody(cid, custodian="bob"), source_principal=_SP)
    assert first.event_hash == second.event_hash
    assert first.custodian == "alice"


def test_custody_integrity_intact(custody_store):
    eid = f"E-{uuid.uuid4()}"
    for _ in range(3):
        custody_store.append(_custody(f"c-{uuid.uuid4()}", evidence_id=eid), source_principal=_SP)
    assert custody_store.verify_integrity().intact is True


def test_custody_application_role_cannot_update_or_delete(custody_store):
    import psycopg

    cid = f"c-{uuid.uuid4()}"
    custody_store.append(_custody(cid), source_principal=_SP)
    conn = psycopg.connect(_DSN)
    try:
        with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "UPDATE evidence_custody_events SET custodian = 'x' WHERE custody_event_id = %s",
                (cid,),
            )
        conn.rollback()
        with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM evidence_custody_events WHERE custody_event_id = %s", (cid,))
        conn.rollback()
    finally:
        conn.close()


def test_concurrent_custody_appends_are_serialized_without_forking(custody_store):
    """FEAT-04-3: many concurrent custody appends, each on its own connection,
    all succeed; global chain_sequence values are unique and contiguous over the
    batch; one valid hash chain results; no append raises."""
    import psycopg
    from emg_audit_pipeline import PostgresCustodyEventStore

    n = 25
    eid = f"E-{uuid.uuid4()}"

    def _one(i: int) -> int:
        conn = psycopg.connect(_DSN)
        try:
            store = PostgresCustodyEventStore(conn)
            ev = _custody(f"c-{uuid.uuid4()}", evidence_id=eid, custodian=f"h{i}")
            return store.append(ev, source_principal=_SP).chain_sequence
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=n) as pool:
        sequences = list(pool.map(_one, range(n)))

    assert len(sequences) == n
    assert len(set(sequences)) == n
    lo, hi = min(sequences), max(sequences)
    assert set(sequences) == set(range(lo, hi + 1))

    verify_conn = psycopg.connect(_DSN)
    try:
        assert PostgresCustodyEventStore(verify_conn).verify_integrity().intact is True
    finally:
        verify_conn.close()


# --- FEAT-04-2 provenance migration backward-compatibility (against real DB) --


@pytest.fixture
def audit_store():
    import psycopg
    from emg_audit_pipeline import PostgresAuditEventStore

    conn = psycopg.connect(_DSN)
    yield PostgresAuditEventStore(conn)
    conn.close()


def _audit(event_id: str, *, provenance=None) -> SubmittedAuditEvent:
    return SubmittedAuditEvent(
        event_id=event_id,
        actor="dev.investigator",
        actor_type="human",
        module="identity",
        action="login",
        outcome="success",
        correlation_id="corr-mig",
        source_system="identity",
        provenance=provenance,
    )


def test_provenance_migration_v1_and_v2_coexist_and_verify(audit_store):
    """After 002 runs, a version-1 event (no provenance) and a version-2 event
    (with provenance) both persist and the whole chain verifies intact —
    proving the additive columns did not break existing hashing."""
    v1 = audit_store.append(_audit(f"evt-{uuid.uuid4()}"), source_principal="emg-svc-identity")
    prov = ProvenanceRecord(
        source_system="identity",
        originating_actor="dev.investigator",
        originating_principal="emg-svc-identity",
        event_time=datetime(2026, 7, 1, 11, 59, tzinfo=timezone.utc),
        ingest_time=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        evidence_origin="sensor-A",
        collection_method="automated",
    )
    v2 = audit_store.append(
        _audit(f"evt-{uuid.uuid4()}", provenance=prov), source_principal="emg-svc-identity"
    )
    assert v1.schema_version == 1 and v1.provenance is None
    assert v2.schema_version == 2 and v2.provenance is not None
    assert audit_store.verify_integrity().intact is True
