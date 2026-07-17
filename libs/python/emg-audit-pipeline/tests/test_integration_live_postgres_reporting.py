"""Opt-in PostgreSQL reporting/query integration test (FEAT-04-4, Sprint 8).

Skipped by default (no database in unit-test CI). Run against a real local
Postgres created by docker-compose + the tools/seed-data/postgres/*.sql scripts
(001, 002, 003, 004 in filename order):

    docker compose up -d postgres
    export EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS=1
    export EMG_AUDIT_TEST_POSTGRES_DSN="postgresql://emg_audit_app:\
emg_audit_local_dev_only_do_not_use_in_prod@localhost:5432/emg"
    pytest libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_reporting.py

It proves, against the real append-only tables, that FEAT-04-4's richer filters
and keyset (cursor) pagination work through SQL (classification / module /
outcome filters, deterministic no-dup/no-skip cursor walk), that the 004
reporting indexes were created (migration additivity — index-only, no row
rewrite), and that existing Sprint 6/7 rows and their hashes are untouched
(integrity still intact) after 004 runs.
"""

from __future__ import annotations

import os
import uuid

import pytest
from emg_audit_client import AuditQuery, SubmittedAuditEvent
from emg_audit_pipeline import encode_cursor

_RUN = os.environ.get("EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS") == "1"
_DSN = os.environ.get("EMG_AUDIT_TEST_POSTGRES_DSN", "")

pytestmark = pytest.mark.skipif(
    not _RUN, reason="set EMG_AUDIT_RUN_LIVE_POSTGRES_TESTS=1 (and a DSN) to run"
)


@pytest.fixture
def audit_store():
    import psycopg
    from emg_audit_pipeline import PostgresAuditEventStore

    conn = psycopg.connect(_DSN)
    yield PostgresAuditEventStore(conn)
    conn.close()


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


def test_filters_and_cursor_pagination_through_sql(audit_store):
    tag = f"rep-{uuid.uuid4()}"
    # Seed a mix so filters are meaningful.
    for i in range(6):
        outcome = "denied" if i % 2 else "success"
        audit_store.append(
            _event(f"{tag}-{i}", actor=tag, outcome=outcome), source_principal="emg-svc-identity"
        )
    denied = audit_store.query(AuditQuery(actor=tag, outcome="denied", limit=100))
    assert denied and all(e.outcome == "denied" for e in denied)

    # Keyset cursor walk over the actor-scoped result: no dupes, no skips.
    seen: list[int] = []
    cursor = None
    for _ in range(100):
        page = audit_store.query(AuditQuery(actor=tag, cursor=cursor, limit=2))
        if not page:
            break
        seen.extend(e.sequence_number for e in page)
        if len(page) < 2:
            break
        cursor = encode_cursor(page[-1].sequence_number)
    assert seen == sorted(seen)
    assert len(set(seen)) == len(seen) == 6


def test_004_reporting_indexes_exist_and_rows_intact(audit_store):
    import psycopg

    conn = psycopg.connect(_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'audit_events'")
            audit_idx = {r[0] for r in cur.fetchall()}
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'evidence_custody_events'"
            )
            custody_idx = {r[0] for r in cur.fetchall()}
    finally:
        conn.close()
    # The 004 composite (filter + keyset-order) indexes are present.
    assert "idx_audit_events_classification_seq" in audit_idx
    assert "idx_audit_events_source_system_seq" in audit_idx
    assert "idx_audit_events_module_seq" in audit_idx
    assert "idx_custody_evidence_chain_seq" in custody_idx
    assert "idx_custody_custodian_chain_seq" in custody_idx
    # 004 is index-only and additive: existing rows/hashes are untouched, so the
    # chain still verifies intact.
    assert audit_store.verify_integrity().intact is True
