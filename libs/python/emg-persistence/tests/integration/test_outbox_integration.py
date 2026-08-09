"""Live PostgreSQL atomic revision/outbox coverage for Phase 2 Sprint 5."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from _outbox_helpers import make_outbox_event
from _persistence_integration_helpers import truncate_persistence_tables
from emg_memory_graph import EvidenceRef, EvidenceSource, MemoryGraph, MemoryNode
from emg_persistence import PersistenceSettings, PostgresNeo4jGraphStore
from emg_persistence.outbox import OutboxEvent
from emg_persistence.postgres import (
    DirectConnectionProvider,
    PostgresMigrationExecutor,
    PostgresOutboxRepository,
    PostgresTransactionProvider,
    connect,
)
from emg_persistence.provisioning import run_knowledge_graph_migrations
from emg_platform_core import GraphStore, PrincipalRef, TenantId
from psycopg import sql
from psycopg.errors import UniqueViolation

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)

TENANT_A = TenantId.of("tenant-a")
TENANT_B = TenantId.of("tenant-b")
PRINCIPAL = PrincipalRef.service("ingest")
NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _graph(node_id: str) -> MemoryGraph:
    evidence = EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator=f"document-{node_id}",
        source_principal="svc-ingest",
        captured_at=NOW,
    )
    return MemoryGraph(
        nodes=(
            MemoryNode(
                node_id=node_id,
                node_type="person",
                label=f"Node {node_id}",
                created_at=NOW,
                updated_at=NOW,
                source="svc-ingest",
                confidence=0.9,
                evidence=(evidence,),
            ),
        )
    )


@pytest.fixture
def settings() -> PersistenceSettings:  # pragma: no cover - live DB only
    return PersistenceSettings(postgres_dsn=_PG_DSN)


@pytest.fixture(autouse=True)
def clean_database(settings: PersistenceSettings) -> Iterator[None]:  # pragma: no cover
    connection = connect(settings)
    run_knowledge_graph_migrations(PostgresMigrationExecutor(connection))
    truncate_persistence_tables(connection)
    connection.commit()
    connection.close()
    try:
        yield
    finally:
        connection = connect(settings)
        truncate_persistence_tables(connection)
        connection.commit()
        connection.close()


def _rows(settings: PersistenceSettings, table: str) -> list[tuple[Any, ...]]:
    assert table in {"graph_revisions", "outbox"}
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table)))
            return list(cursor.fetchall())
    finally:
        connection.close()


def _store(settings: PersistenceSettings) -> GraphStore:
    transactions = PostgresTransactionProvider(DirectConnectionProvider(settings))
    return PostgresNeo4jGraphStore(transactions, clock=lambda: NOW)


@requires_postgres
def test_first_and_subsequent_revisions_commit_with_complete_outbox_payload(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover
    store = _store(settings)

    store.write(TENANT_A, _graph("first"), principal=PRINCIPAL)
    second = _graph("second")
    store.write(TENANT_A, second, principal=PRINCIPAL)

    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT revision_number, content_hash, event_type, schema_version, "
                "idempotency_key, payload, published_at FROM outbox "
                "WHERE tenant_id = %(tenant)s ORDER BY revision_number",
                {"tenant": TENANT_A.value},
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    assert [row[0] for row in rows] == [1, 2]
    assert rows[1][1] == second.content_hash()
    assert rows[1][2:5] == ("graph.revision.committed", 1, "tenant-a:2")
    assert rows[1][5] == {
        "tenant_id": "tenant-a",
        "revision_number": 2,
        "content_hash": second.content_hash(),
        "parent_hash": rows[0][1],
        "principal_id": PRINCIPAL.principal_id,
        "principal_kind": PRINCIPAL.kind.value,
        "node_count": 1,
        "edge_count": 0,
        "created_at": NOW.isoformat(),
    }
    assert rows[1][6] is None


class _FailAfterAppendOutbox(PostgresOutboxRepository):
    def append(self, event: OutboxEvent) -> None:
        super().append(event)
        raise RuntimeError("force owning transaction rollback")


@requires_postgres
def test_failure_after_outbox_insert_rolls_back_revision_and_event(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover
    transactions = PostgresTransactionProvider(DirectConnectionProvider(settings))
    store: GraphStore = PostgresNeo4jGraphStore(
        transactions,
        outbox_repository_factory=_FailAfterAppendOutbox,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="force owning transaction rollback"):
        store.write(TENANT_A, _graph("rolled-back"), principal=PRINCIPAL)

    assert _rows(settings, "graph_revisions") == []
    assert _rows(settings, "outbox") == []


@requires_postgres
def test_no_op_creates_no_additional_outbox_event(settings: PersistenceSettings) -> None:
    store = _store(settings)
    graph = _graph("same")

    store.write(TENANT_A, graph, principal=PRINCIPAL)
    store.write(TENANT_A, graph, principal=PRINCIPAL)

    assert len(_rows(settings, "graph_revisions")) == 1
    assert len(_rows(settings, "outbox")) == 1


@requires_postgres
def test_outbox_events_are_isolated_and_ordered_per_tenant(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover
    store = _store(settings)
    store.write(TENANT_B, _graph("b-1"), principal=PRINCIPAL)
    store.write(TENANT_A, _graph("a-1"), principal=PRINCIPAL)
    store.write(TENANT_B, _graph("b-2"), principal=PRINCIPAL)

    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id, revision_number, idempotency_key FROM outbox "
                "ORDER BY tenant_id, revision_number"
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    assert rows == [
        ("tenant-a", 1, "tenant-a:1"),
        ("tenant-b", 1, "tenant-b:1"),
        ("tenant-b", 2, "tenant-b:2"),
    ]


@requires_postgres
def test_duplicate_idempotency_key_is_rejected_and_transaction_rolls_back(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover
    transactions = PostgresTransactionProvider(DirectConnectionProvider(settings))
    first = make_outbox_event(event_id=uuid4(), idempotency_key="duplicate")
    duplicate = make_outbox_event(event_id=uuid4(), idempotency_key="duplicate")

    with pytest.raises(UniqueViolation), transactions.transaction() as connection:
        repository = PostgresOutboxRepository(connection)
        repository.append(first)
        repository.append(duplicate)

    assert _rows(settings, "outbox") == []
