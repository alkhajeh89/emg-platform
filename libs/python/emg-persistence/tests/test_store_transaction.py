"""Persistent GraphStore transaction lifecycle tests (Task 4A)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
from emg_persistence.revisions import Revision, RevisionHead, RevisionRepository
from emg_persistence.store import PostgresNeo4jGraphStore, _PersistentGraphTransaction
from emg_platform_core import PrincipalRef, TenantId, TransactionStateError, WriteReceipt
from psycopg import Connection

TENANT = TenantId.of("acme")
PRINCIPAL = PrincipalRef.service("ingest")
NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def _graph() -> MemoryGraph:
    evidence = EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator="document-1",
        source_principal="svc-ingest",
        captured_at=NOW,
    )
    node = MemoryNode(
        node_id="node-1",
        node_type="person",
        label="Example",
        created_at=NOW,
        updated_at=NOW,
        source="svc-ingest",
        confidence=0.9,
        evidence=(evidence,),
    )
    return MemoryGraph(nodes=(node,))


def _revision(graph: MemoryGraph) -> Revision:
    return Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash=graph.content_hash(),
        parent_hash=None,
        principal=PRINCIPAL,
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        graph_json=graph.model_dump(mode="json"),
        created_at=NOW,
    )


class _Transactions:
    def __init__(self, events: list[str], *, commit_failure: BaseException | None = None) -> None:
        self.events = events
        self.commit_failure = commit_failure
        self.calls = 0

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        self.calls += 1
        self.events.append("begin")
        try:
            yield cast(Connection[Any], object())
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
            if self.commit_failure is not None:
                raise self.commit_failure
        finally:
            self.events.append("close")


class _Repository:
    def __init__(self, events: list[str], current: Revision | None = None) -> None:
        self.events = events
        self.current = current
        self.created: list[Revision] = []
        self.appended: list[Revision] = []

    def get_head(self, tenant: TenantId) -> RevisionHead | None:
        assert tenant == TENANT
        self.events.append("get_head")
        return None if self.current is None else self.current.head()

    def get_revision(self, tenant: TenantId, revision_number: int) -> Revision | None:
        assert tenant == TENANT
        self.events.append("get_revision")
        if self.current is None or self.current.revision_number != revision_number:
            return None
        return self.current

    def revalidate_head(self, tenant: TenantId, expected: RevisionHead) -> bool:
        assert tenant == TENANT
        self.events.append("revalidate_head")
        return self.current is not None and self.current.head() == expected

    def create_first_revision(self, revision: Revision) -> RevisionHead:
        self.events.append("create_first")
        self.created.append(revision)
        self.current = revision
        return revision.head()

    def append_revision(self, revision: Revision) -> RevisionHead:
        self.events.append("append")
        self.appended.append(revision)
        self.current = revision
        return revision.head()


def _store(
    repository: _Repository,
    events: list[str],
    *,
    commit_failure: BaseException | None = None,
) -> tuple[PostgresNeo4jGraphStore, _Transactions]:
    transactions = _Transactions(events, commit_failure=commit_failure)
    outbox = RecordingOutboxRepository(events)

    def repository_factory(_connection: Connection[Any]) -> RevisionRepository:
        return cast(RevisionRepository, repository)

    return (
        PostgresNeo4jGraphStore(
            transactions,
            repository_factory=repository_factory,
            outbox_repository_factory=lambda _connection: outbox,
            clock=lambda: NOW,
        ),
        transactions,
    )


def test_transaction_is_open_and_staged_reads_are_consistent() -> None:
    events: list[str] = []
    repository = _Repository(events, _revision(EMPTY_GRAPH))
    store, transactions = _store(repository, events)
    staged = _graph()

    with store.transaction(TENANT, PRINCIPAL) as transaction:
        assert transaction.tenant == TENANT
        assert transaction.principal == PRINCIPAL
        assert transaction.read() == EMPTY_GRAPH
        transaction.stage(staged)
        assert transaction.read() is staged
        assert transactions.calls == 1

    assert repository.appended[0].graph_json == staged.model_dump(mode="json")
    assert events == [
        "begin",
        "get_head",
        "get_revision",
        "get_head",
        "get_revision",
        "append",
        "outbox",
        "commit",
        "close",
    ]


def test_clean_exit_commits_and_receipt_is_available_only_after_commit() -> None:
    events: list[str] = []
    repository = _Repository(events)
    store, _ = _store(repository, events)
    staged = _graph()

    with store.transaction(TENANT, PRINCIPAL) as transaction:
        transaction.stage(staged)
        with pytest.raises(TransactionStateError, match="only available"):
            _ = transaction.receipt

    receipt = transaction.receipt
    assert receipt.tenant == TENANT
    assert receipt.principal == PRINCIPAL
    assert receipt.content_hash == staged.content_hash()
    assert receipt.node_count == 1
    assert receipt.edge_count == 0
    assert events[-2:] == ["commit", "close"]


def test_exception_aborts_and_rolls_back_without_persisting() -> None:
    events: list[str] = []
    repository = _Repository(events, _revision(EMPTY_GRAPH))
    store, _ = _store(repository, events)

    with (
        pytest.raises(RuntimeError, match="boom"),
        store.transaction(TENANT, PRINCIPAL) as transaction,
    ):
        transaction.stage(_graph())
        raise RuntimeError("boom")

    assert repository.appended == []
    assert events[-2:] == ["rollback", "close"]
    with pytest.raises(TransactionStateError, match="aborted"):
        _ = transaction.receipt
    with pytest.raises(TransactionStateError, match="aborted"):
        transaction.read()


def test_commit_failure_aborts_and_exposes_no_receipt() -> None:
    events: list[str] = []
    repository = _Repository(events)
    store, _ = _store(repository, events, commit_failure=RuntimeError("commit failed"))

    with (
        pytest.raises(RuntimeError, match="commit failed"),
        store.transaction(TENANT, PRINCIPAL) as transaction,
    ):
        transaction.stage(_graph())

    with pytest.raises(TransactionStateError, match="aborted"):
        _ = transaction.receipt
    with pytest.raises(TransactionStateError, match="aborted"):
        transaction.stage(EMPTY_GRAPH)


def test_committed_transaction_rejects_post_close_operations() -> None:
    events: list[str] = []
    store, _ = _store(_Repository(events), events)

    with store.transaction(TENANT, PRINCIPAL) as transaction:
        transaction.stage(_graph())

    with pytest.raises(TransactionStateError, match="committed"):
        transaction.read()
    with pytest.raises(TransactionStateError, match="committed"):
        transaction.stage(EMPTY_GRAPH)


def test_internal_transaction_rejects_double_commit_and_abort_after_commit() -> None:
    graph = _graph()
    transaction = _PersistentGraphTransaction(TENANT, PRINCIPAL, EMPTY_GRAPH)
    committed_receipt = WriteReceipt(
        tenant=TENANT,
        principal=PRINCIPAL,
        content_hash=graph.content_hash(),
        node_count=graph.node_count,
        edge_count=graph.edge_count,
    )
    transaction.commit(committed_receipt)

    with pytest.raises(TransactionStateError, match="committed"):
        transaction.commit(committed_receipt)
    with pytest.raises(TransactionStateError, match="committed"):
        transaction.abort()
