"""Live PostgreSQL GraphStore integration coverage for Phase 2 Sprint 4.

Skipped unless ``EMG_PERSISTENCE_TEST_POSTGRES_DSN`` is configured. These tests
use real psycopg connections, transaction scopes, and PostgresRevisionRepository
instances. Neo4j is deliberately absent from the entire suite.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest
from emg_memory_graph import (
    EMPTY_GRAPH,
    EvidenceRef,
    EvidenceSource,
    MemoryGraph,
    MemoryNode,
)
from emg_persistence import (
    PersistenceConflictError,
    PersistenceSettings,
    PostgresNeo4jGraphStore,
    build_graph_store,
)
from emg_persistence.migrate import run_migrations
from emg_persistence.postgres import (
    DirectConnectionProvider,
    PostgresMigrationExecutor,
    PostgresRevisionRepository,
    PostgresTransactionProvider,
    connect,
)
from emg_persistence.revisions import Revision, RevisionHead, RevisionRepository
from emg_platform_core import GraphStore, PrincipalRef, TenantId, TransactionStateError
from psycopg import Connection

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)

TENANT_A = TenantId.of("tenant-a")
TENANT_B = TenantId.of("tenant-b")
PRINCIPAL = PrincipalRef.service("ingest")
NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def _graph(*node_ids: str) -> MemoryGraph:
    nodes = []
    for node_id in node_ids:
        evidence = EvidenceRef.create(
            source=EvidenceSource.PDF,
            locator=f"document-{node_id}",
            source_principal="svc-ingest",
            captured_at=NOW,
        )
        nodes.append(
            MemoryNode(
                node_id=node_id,
                node_type="person",
                label=f"Node {node_id}",
                created_at=NOW,
                updated_at=NOW,
                source="svc-ingest",
                confidence=0.9,
                evidence=(evidence,),
            )
        )
    return MemoryGraph(nodes=tuple(nodes))


@pytest.fixture
def settings() -> PersistenceSettings:  # pragma: no cover - live DB only
    return PersistenceSettings(postgres_dsn=_PG_DSN)


@pytest.fixture(autouse=True)
def clean_database(settings: PersistenceSettings) -> Iterator[None]:  # pragma: no cover
    connection = connect(settings)
    run_migrations(PostgresMigrationExecutor(connection))
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE graph_revisions, graph_head")
    connection.commit()
    connection.close()
    try:
        yield
    finally:
        connection = connect(settings)
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE graph_revisions, graph_head")
        connection.commit()
        connection.close()


@pytest.fixture
def store(settings: PersistenceSettings) -> GraphStore:  # pragma: no cover
    return build_graph_store(settings)


def _revision_count(settings: PersistenceSettings, tenant: TenantId) -> int:
    connection = connect(settings)
    try:
        return PostgresRevisionRepository(connection).revision_count(tenant)
    finally:
        connection.close()


class _HookedRepository(PostgresRevisionRepository):
    def __init__(
        self,
        connection: Connection[Any],
        *,
        before_revalidate: Callable[[], None] | None = None,
        before_append: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(connection)
        self._before_revalidate = before_revalidate
        self._before_append = before_append

    def revalidate_head(self, tenant: TenantId, expected: RevisionHead) -> bool:
        if self._before_revalidate is not None:
            callback, self._before_revalidate = self._before_revalidate, None
            callback()
        return super().revalidate_head(tenant, expected)

    def append_revision(self, revision: Revision) -> RevisionHead:
        if self._before_append is not None:
            callback, self._before_append = self._before_append, None
            callback()
        return super().append_revision(revision)


def _hooked_store(
    settings: PersistenceSettings,
    *,
    before_revalidate: Callable[[], None] | None = None,
    before_append: Callable[[], None] | None = None,
) -> GraphStore:
    transactions = PostgresTransactionProvider(DirectConnectionProvider(settings))

    def repository_factory(connection: Connection[Any]) -> RevisionRepository:
        return _HookedRepository(
            connection,
            before_revalidate=before_revalidate,
            before_append=before_append,
        )

    return PostgresNeo4jGraphStore(
        transactions,
        repository_factory=repository_factory,
        clock=lambda: NOW,
    )


@requires_postgres
def test_first_subsequent_write_and_read_after_write(
    store: GraphStore, settings: PersistenceSettings
) -> None:  # pragma: no cover
    first = _graph("a")
    second = _graph("a", "b")

    first_receipt = store.write(TENANT_A, first, principal=PRINCIPAL)
    second_receipt = store.write(TENANT_A, second, principal=PRINCIPAL)

    assert first_receipt.content_hash == first.content_hash()
    assert second_receipt.content_hash == second.content_hash()
    assert second_receipt.node_count == 2
    assert store.read(TENANT_A).content_hash() == second.content_hash()
    assert _revision_count(settings, TENANT_A) == 2


@requires_postgres
def test_transaction_commit_and_receipt(store: GraphStore) -> None:  # pragma: no cover
    graph = _graph("committed")

    with store.transaction(TENANT_A, PRINCIPAL) as transaction:
        assert transaction.read() == EMPTY_GRAPH
        transaction.stage(graph)
        assert transaction.read() is graph
        with pytest.raises(TransactionStateError):
            _ = transaction.receipt

    assert transaction.receipt.content_hash == graph.content_hash()
    assert store.read(TENANT_A).content_hash() == graph.content_hash()


@requires_postgres
def test_transaction_caller_exception_rolls_back(store: GraphStore) -> None:  # pragma: no cover
    initial = _graph("initial")
    store.write(TENANT_A, initial, principal=PRINCIPAL)

    with (
        pytest.raises(RuntimeError, match="caller failed"),
        store.transaction(TENANT_A, PRINCIPAL) as transaction,
    ):
        transaction.stage(_graph("replacement"))
        raise RuntimeError("caller failed")

    assert store.read(TENANT_A).content_hash() == initial.content_hash()
    with pytest.raises(TransactionStateError):
        _ = transaction.receipt


@requires_postgres
def test_no_op_and_repeated_historical_content_hash(
    store: GraphStore, settings: PersistenceSettings
) -> None:  # pragma: no cover
    first = _graph("a")
    second = _graph("b")
    store.write(TENANT_A, first, principal=PRINCIPAL)

    no_op = store.write(TENANT_A, first, principal=PRINCIPAL)
    assert no_op.content_hash == first.content_hash()
    assert _revision_count(settings, TENANT_A) == 1

    store.write(TENANT_A, second, principal=PRINCIPAL)
    repeated = store.write(TENANT_A, first, principal=PRINCIPAL)
    assert repeated.content_hash == first.content_hash()
    assert _revision_count(settings, TENANT_A) == 3


@requires_postgres
def test_stale_no_op_revalidation_race(
    store: GraphStore, settings: PersistenceSettings
) -> None:  # pragma: no cover
    original = _graph("original")
    advanced = _graph("advanced")
    store.write(TENANT_A, original, principal=PRINCIPAL)

    def advance_head() -> None:
        store.write(TENANT_A, advanced, principal=PRINCIPAL)

    racing_store = _hooked_store(
        settings,
        before_revalidate=advance_head,
    )
    with pytest.raises(PersistenceConflictError, match="head changed"):
        racing_store.write(TENANT_A, original, principal=PRINCIPAL)

    assert store.read(TENANT_A).content_hash() == advanced.content_hash()
    assert _revision_count(settings, TENANT_A) == 2


@requires_postgres
def test_cas_conflict_from_concurrent_head_advance(
    store: GraphStore, settings: PersistenceSettings
) -> None:  # pragma: no cover
    original = _graph("original")
    winner = _graph("winner")
    loser = _graph("loser")
    store.write(TENANT_A, original, principal=PRINCIPAL)

    def advance_head() -> None:
        store.write(TENANT_A, winner, principal=PRINCIPAL)

    racing_store = _hooked_store(
        settings,
        before_append=advance_head,
    )
    with pytest.raises(PersistenceConflictError, match="head advanced"):
        racing_store.write(TENANT_A, loser, principal=PRINCIPAL)

    assert store.read(TENANT_A).content_hash() == winner.content_hash()
    assert _revision_count(settings, TENANT_A) == 2


@requires_postgres
def test_tenant_enumeration_and_isolation(store: GraphStore) -> None:  # pragma: no cover
    store.write(TENANT_B, _graph("b-1", "b-2"), principal=PRINCIPAL)
    store.write(TENANT_A, _graph("a-1"), principal=PRINCIPAL)

    assert store.tenants() == (TENANT_A, TENANT_B)
    assert store.read(TENANT_A).node_count == 1
    assert store.read(TENANT_B).node_count == 2


class _CountingTransactionProvider(PostgresTransactionProvider):
    def __init__(self, connections: DirectConnectionProvider) -> None:
        super().__init__(connections)
        self.scopes = 0
        self.events: list[str] = []

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        self.scopes += 1
        self.events.append("begin")
        with super().transaction() as connection:
            yield connection
        self.events.append("committed")


@requires_postgres
def test_one_connection_and_transaction_per_operation_without_neo4j(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover
    connection_count = 0

    def counted_connect(config: PersistenceSettings) -> Connection[Any]:
        nonlocal connection_count
        connection_count += 1
        return connect(config)

    connections = DirectConnectionProvider(settings, connection_factory=counted_connect)
    transactions = _CountingTransactionProvider(connections)
    store: GraphStore = PostgresNeo4jGraphStore(transactions, clock=lambda: NOW)

    receipt = store.write(TENANT_A, _graph("a"), principal=PRINCIPAL)

    assert receipt.content_hash == _graph("a").content_hash()
    assert connection_count == 1
    assert transactions.scopes == 1
    assert transactions.events == ["begin", "committed"]
    assert settings.neo4j_uri is None
