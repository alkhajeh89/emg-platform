"""PostgreSQL-authoritative persistent graph read path (Task 3A)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from emg_memory_graph import EMPTY_GRAPH, EvidenceRef, EvidenceSource, MemoryGraph, MemoryNode
from emg_persistence import PersistenceError
from emg_persistence.revisions import InMemoryRevisionRepository, Revision, RevisionRepository
from emg_persistence.store import PostgresNeo4jGraphStore
from emg_platform_core import PrincipalRef, TenantId
from psycopg import Connection, OperationalError

TENANT = TenantId.of("acme")
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Transactions:
    def __init__(self) -> None:
        self.calls = 0

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        self.calls += 1
        yield cast(Connection[Any], object())


def _graph() -> MemoryGraph:
    evidence = EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator="document-1",
        source_principal="svc-ingest",
        captured_at=T0,
    )
    node = MemoryNode(
        node_id="node-1",
        node_type="person",
        label="Example",
        created_at=T0,
        updated_at=T0,
        source="svc-ingest",
        confidence=0.9,
        evidence=(evidence,),
    )
    return MemoryGraph(nodes=(node,))


def _revision(graph: MemoryGraph, *, content_hash: str | None = None) -> Revision:
    return Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash=content_hash or graph.content_hash(),
        parent_hash=None,
        principal=PrincipalRef.service("ingest"),
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        graph_json=graph.model_dump(mode="json"),
        created_at=T0,
    )


def _store(repository: RevisionRepository) -> tuple[PostgresNeo4jGraphStore, _Transactions]:
    transactions = _Transactions()

    def repository_factory(_connection: Connection[Any]) -> RevisionRepository:
        return repository

    return (
        PostgresNeo4jGraphStore(transactions, repository_factory=repository_factory),
        transactions,
    )


def test_existing_tenant_returns_deserialized_snapshot() -> None:
    graph = _graph()
    repository = InMemoryRevisionRepository()
    repository.create_first_revision(_revision(graph))
    store, transactions = _store(repository)

    result = store.read(TENANT)

    assert result == graph
    assert result is not graph
    assert result.content_hash() == graph.content_hash()
    assert transactions.calls == 1


def test_missing_tenant_returns_empty_graph() -> None:
    store, transactions = _store(InMemoryRevisionRepository())

    assert store.read(TENANT) is EMPTY_GRAPH
    assert transactions.calls == 1


def test_invalid_snapshot_raises_persistence_error() -> None:
    graph = _graph()
    revision = _revision(graph).model_copy(update={"graph_json": {"nodes": "invalid"}})
    repository = InMemoryRevisionRepository()
    repository.create_first_revision(revision)
    store, _ = _store(repository)

    with pytest.raises(PersistenceError, match="invalid graph snapshot"):
        store.read(TENANT)


def test_snapshot_hash_mismatch_raises_persistence_error() -> None:
    graph = _graph()
    repository = InMemoryRevisionRepository()
    repository.create_first_revision(_revision(graph, content_hash="a" * 64))
    store, _ = _store(repository)

    with pytest.raises(PersistenceError, match="graph snapshot hash mismatch"):
        store.read(TENANT)


def test_missing_head_revision_raises_persistence_error() -> None:
    graph = _graph()
    revision = _revision(graph)
    repository = InMemoryRevisionRepository()
    assert repository.compare_and_set_head(TENANT, None, revision.head()) is True
    store, _ = _store(repository)

    with pytest.raises(PersistenceError, match="head revision 1 is missing"):
        store.read(TENANT)


class _FailingRepository(InMemoryRevisionRepository):
    def get_head(self, tenant: TenantId) -> None:
        del tenant
        raise OperationalError("database unavailable")


def test_repository_failure_is_translated() -> None:
    store, _ = _store(_FailingRepository())

    with pytest.raises(PersistenceError, match="failed to read authoritative graph") as caught:
        store.read(TENANT)

    assert isinstance(caught.value.__cause__, OperationalError)


def test_transaction_provider_context_shape() -> None:
    transactions = _Transactions()
    assert isinstance(transactions.transaction(), AbstractContextManager)
