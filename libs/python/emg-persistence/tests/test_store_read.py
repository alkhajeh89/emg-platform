"""PostgreSQL-authoritative persistent graph read path (Task 3A)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from emg_memory_graph import EMPTY_GRAPH, EvidenceRef, EvidenceSource, MemoryGraph, MemoryNode
from emg_persistence import PersistenceError
from emg_persistence.neo4j.projection import Neo4jGraphProjection, ProjectionHead
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


class _CountingRepository(InMemoryRevisionRepository):
    def __init__(self) -> None:
        super().__init__()
        self.head_requests: list[TenantId] = []
        self.revision_requests: list[tuple[TenantId, int]] = []

    def get_head(self, tenant: TenantId):  # type: ignore[no-untyped-def]
        self.head_requests.append(tenant)
        return super().get_head(tenant)

    def get_revision(self, tenant: TenantId, revision_number: int):  # type: ignore[no-untyped-def]
        self.revision_requests.append((tenant, revision_number))
        return super().get_revision(tenant, revision_number)


class _Projection:
    def __init__(
        self,
        *,
        heads: dict[TenantId, ProjectionHead | None] | None = None,
        graphs: dict[TenantId, MemoryGraph] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.heads = heads or {}
        self.graphs = graphs or {}
        self.unavailable = unavailable
        self.head_requests: list[TenantId] = []
        self.reconstruct_requests: list[TenantId] = []
        self.repair_requests: list[TenantId] = []
        self.repair_revisions: list[Revision | None] = []

    def get_projection_head(self, tenant: TenantId) -> ProjectionHead | None:
        self.head_requests.append(tenant)
        if self.unavailable:
            raise PersistenceError("Neo4j unavailable")
        return self.heads.get(tenant)

    def reconstruct(self, tenant: TenantId) -> MemoryGraph:
        self.reconstruct_requests.append(tenant)
        return self.graphs.get(tenant, EMPTY_GRAPH)

    def read_repair(self, tenant, *, load_head, load_revision):  # type: ignore[no-untyped-def]
        self.repair_requests.append(tenant)
        head = load_head(tenant)
        assert head is not None
        revision = load_revision(tenant, head[0])
        self.repair_revisions.append(revision)
        return self.graphs.get(tenant, EMPTY_GRAPH)


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


def _store(
    repository: RevisionRepository,
    *,
    projection: _Projection | None = None,
) -> tuple[PostgresNeo4jGraphStore, _Transactions]:
    transactions = _Transactions()

    def repository_factory(_connection: Connection[Any]) -> RevisionRepository:
        return repository

    return (
        PostgresNeo4jGraphStore(
            transactions,
            repository_factory=repository_factory,
            projection=cast(Neo4jGraphProjection | None, projection),
        ),
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
    assert transactions.calls == 2


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


def test_matching_projection_avoids_authoritative_snapshot_materialization() -> None:
    graph = _graph()
    repository = _CountingRepository()
    repository.create_first_revision(_revision(graph))
    projection = _Projection(
        heads={
            TENANT: ProjectionHead(
                tenant=TENANT,
                revision_number=1,
                content_hash=graph.content_hash(),
            )
        },
        graphs={TENANT: graph},
    )
    store, transactions = _store(repository, projection=projection)

    result = store.read(TENANT)

    assert result is graph
    assert repository.head_requests == [TENANT]
    assert repository.revision_requests == []
    assert projection.head_requests == [TENANT]
    assert projection.reconstruct_requests == [TENANT]
    assert transactions.calls == 1


def test_lagging_projection_loads_head_snapshot_once_and_repairs() -> None:
    graph = _graph()
    revision = _revision(graph)
    repository = _CountingRepository()
    repository.create_first_revision(revision)
    projection = _Projection()
    store, _ = _store(repository, projection=projection)

    result = store.read(TENANT)

    assert result == graph
    assert repository.revision_requests == [(TENANT, 1)]
    assert projection.repair_requests == [TENANT]
    assert projection.repair_revisions == [revision]


def test_unavailable_projection_loads_head_snapshot_once_without_repair() -> None:
    graph = _graph()
    repository = _CountingRepository()
    repository.create_first_revision(_revision(graph))
    projection = _Projection(unavailable=True)
    store, _ = _store(repository, projection=projection)

    result = store.read(TENANT)

    assert result == graph
    assert repository.revision_requests == [(TENANT, 1)]
    assert projection.repair_requests == []


def test_missing_authoritative_head_does_not_consult_projection() -> None:
    repository = _CountingRepository()
    projection = _Projection()
    store, transactions = _store(repository, projection=projection)

    assert store.read(TENANT) is EMPTY_GRAPH
    assert repository.head_requests == [TENANT]
    assert repository.revision_requests == []
    assert projection.head_requests == []
    assert transactions.calls == 1


def test_historical_read_bypasses_projection() -> None:
    graph = _graph()
    repository = _CountingRepository()
    repository.create_first_revision(_revision(graph))
    projection = _Projection(unavailable=True)
    store, _ = _store(repository, projection=projection)

    historical = store.read_revision(TENANT, 1)

    assert historical.graph == graph
    assert projection.head_requests == []
    assert repository.revision_requests == [(TENANT, 1)]


def test_projection_read_is_tenant_scoped() -> None:
    tenant_b = TenantId.of("other")
    graph_a = _graph()
    graph_b = MemoryGraph()
    repository = _CountingRepository()
    repository.create_first_revision(_revision(graph_a))
    projection = _Projection(
        heads={
            TENANT: ProjectionHead(
                tenant=TENANT,
                revision_number=1,
                content_hash=graph_a.content_hash(),
            ),
            tenant_b: ProjectionHead(
                tenant=tenant_b,
                revision_number=1,
                content_hash=graph_b.content_hash(),
            ),
        },
        graphs={TENANT: graph_a, tenant_b: graph_b},
    )
    store, _ = _store(repository, projection=projection)

    assert store.read(TENANT) is graph_a
    assert projection.head_requests == [TENANT]
    assert projection.reconstruct_requests == [TENANT]


@pytest.mark.parametrize(
    "projection_head",
    [
        ProjectionHead(tenant=TENANT, revision_number=2, content_hash="b" * 64),
        ProjectionHead(tenant=TENANT, revision_number=1, content_hash="c" * 64),
    ],
)
def test_projection_revision_or_hash_mismatch_falls_back_without_weakening_integrity(
    projection_head: ProjectionHead,
) -> None:
    graph = _graph()
    repository = _CountingRepository()
    repository.create_first_revision(_revision(graph))
    projection = _Projection(heads={TENANT: projection_head}, graphs={TENANT: EMPTY_GRAPH})
    store, _ = _store(repository, projection=projection)

    result = store.read(TENANT)

    assert result == graph
    assert repository.revision_requests == [(TENANT, 1)]
    assert projection.repair_requests == []
