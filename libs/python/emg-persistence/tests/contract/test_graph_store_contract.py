"""Shared GraphStore contract tests that require no live databases.

The same behavioral assertions run against the Phase 1 in-memory reference and
the Sprint 4 persistent store backed by a controlled RevisionRepository double.
Live PostgreSQL contract coverage is intentionally deferred to the next task.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from _outbox_helpers import RecordingOutboxRepository
from emg_memory_graph import (
    EMPTY_GRAPH,
    EvidenceRef,
    EvidenceSource,
    MemoryGraph,
    MemoryNode,
)
from emg_persistence.revisions import InMemoryRevisionRepository, RevisionRepository
from emg_persistence.store import PostgresNeo4jGraphStore
from emg_platform_core import (
    GraphStore,
    InMemoryGraphStore,
    PrincipalRef,
    TenantId,
    TransactionStateError,
)
from psycopg import Connection

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


class _ControlledTransactions:
    def __init__(self) -> None:
        self.calls = 0

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        self.calls += 1
        yield cast(Connection[Any], object())


@dataclass(frozen=True)
class _Harness:
    store: GraphStore
    revisions: InMemoryRevisionRepository | None


@pytest.fixture(params=("in-memory", "persistent"))
def graph_store(request: pytest.FixtureRequest) -> _Harness:
    if request.param == "in-memory":
        return _Harness(InMemoryGraphStore(), None)

    revisions = InMemoryRevisionRepository()
    outbox = RecordingOutboxRepository()

    def repository_factory(_connection: Connection[Any]) -> RevisionRepository:
        return revisions

    store = PostgresNeo4jGraphStore(
        _ControlledTransactions(),
        repository_factory=repository_factory,
        outbox_repository_factory=lambda _connection: outbox,
        clock=lambda: NOW,
    )
    return _Harness(store, revisions)


def test_runtime_protocol_and_required_signatures(graph_store: _Harness) -> None:
    store = graph_store.store

    assert isinstance(store, GraphStore)
    expected_parameters = {
        "read": ("self", "tenant"),
        "write": ("self", "tenant", "graph", "principal"),
        "tenants": ("self",),
        "transaction": ("self", "tenant", "principal"),
    }
    for method_name, expected in expected_parameters.items():
        method = getattr(type(store), method_name)
        signature = inspect.signature(method)
        assert tuple(signature.parameters) == expected

    write_signature = inspect.signature(type(store).write)
    assert write_signature.parameters["principal"].kind is inspect.Parameter.KEYWORD_ONLY


def test_read_write_receipt_first_write_and_no_op(graph_store: _Harness) -> None:
    store = graph_store.store
    graph = _graph("a", "b")

    assert store.read(TENANT_A) == EMPTY_GRAPH

    first_receipt = store.write(TENANT_A, graph, principal=PRINCIPAL)
    assert first_receipt.tenant == TENANT_A
    assert first_receipt.principal == PRINCIPAL
    assert first_receipt.content_hash == graph.content_hash()
    assert first_receipt.node_count == 2
    assert first_receipt.edge_count == 0
    assert first_receipt.revision_number == 1
    assert first_receipt.revision_created is True
    assert store.read(TENANT_A).content_hash() == graph.content_hash()

    no_op_receipt = store.write(TENANT_A, graph, principal=PRINCIPAL)
    # Identity/content match the first write, but a no-op (ADR-023 §11) must
    # report revision_created=False and identify the *existing* head — it must
    # not be indistinguishable from a fresh append.
    assert no_op_receipt.tenant == first_receipt.tenant
    assert no_op_receipt.principal == first_receipt.principal
    assert no_op_receipt.content_hash == first_receipt.content_hash
    assert no_op_receipt.node_count == first_receipt.node_count
    assert no_op_receipt.edge_count == first_receipt.edge_count
    assert no_op_receipt.revision_number == first_receipt.revision_number
    assert no_op_receipt.committed_at == first_receipt.committed_at
    assert no_op_receipt.revision_created is False
    if graph_store.revisions is not None:
        assert graph_store.revisions.revision_count(TENANT_A) == 1


def test_tenant_isolation_and_sorted_enumeration(graph_store: _Harness) -> None:
    store = graph_store.store

    store.write(TENANT_B, _graph("b-1", "b-2"), principal=PRINCIPAL)
    assert store.read(TENANT_A) == EMPTY_GRAPH
    store.write(TENANT_A, _graph("a-1"), principal=PRINCIPAL)

    assert store.read(TENANT_A).node_count == 1
    assert store.read(TENANT_B).node_count == 2
    assert store.tenants() == (TENANT_A, TENANT_B)


def test_transaction_commit_staged_reads_and_receipt_lifecycle(
    graph_store: _Harness,
) -> None:
    store = graph_store.store
    initial = _graph("a")
    staged = _graph("a", "b", "c")
    store.write(TENANT_A, initial, principal=PRINCIPAL)

    with store.transaction(TENANT_A, PRINCIPAL) as transaction:
        assert transaction.read().content_hash() == initial.content_hash()
        with pytest.raises(TransactionStateError):
            _ = transaction.receipt
        transaction.stage(staged)
        assert transaction.read() is staged

    assert transaction.receipt.content_hash == staged.content_hash()
    assert transaction.receipt.node_count == 3
    assert store.read(TENANT_A).content_hash() == staged.content_hash()
    with pytest.raises(TransactionStateError):
        transaction.read()
    with pytest.raises(TransactionStateError):
        transaction.stage(EMPTY_GRAPH)


def test_transaction_caller_exception_rolls_back_and_aborts(
    graph_store: _Harness,
) -> None:
    store = graph_store.store
    initial = _graph("a")
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
    with pytest.raises(TransactionStateError):
        transaction.read()


def test_transaction_for_new_tenant_starts_empty(graph_store: _Harness) -> None:
    store = graph_store.store
    staged = _graph("new")

    with store.transaction(TENANT_B, PRINCIPAL) as transaction:
        assert transaction.read() == EMPTY_GRAPH
        transaction.stage(staged)

    assert store.read(TENANT_B).content_hash() == staged.content_hash()
    assert store.tenants() == (TENANT_B,)
