"""PostgreSQL-authoritative direct graph write orchestration (Task 3C)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from emg_memory_graph import (
    EMPTY_GRAPH,
    EvidenceRef,
    EvidenceSource,
    MemoryGraph,
    MemoryNode,
    diff_graphs,
)
from emg_persistence import PersistenceConflictError, PersistenceError
from emg_persistence.revisions import Revision, RevisionHead, RevisionRepository
from emg_persistence.store import PostgresNeo4jGraphStore
from emg_platform_core import PrincipalRef, TenantId, WriteReceipt
from psycopg import Connection, OperationalError

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


def _revision(graph: MemoryGraph, *, number: int = 1, parent_hash: str | None = None) -> Revision:
    return Revision(
        tenant=TENANT,
        revision_number=number,
        content_hash=graph.content_hash(),
        parent_hash=parent_hash,
        principal=PRINCIPAL,
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        graph_json=graph.model_dump(mode="json"),
        created_at=NOW,
    )


class _Transactions:
    def __init__(self, events: list[str], *, commit_failure: BaseException | None = None) -> None:
        self._events = events
        self._commit_failure = commit_failure
        self.calls = 0

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        self.calls += 1
        self._events.append("begin")
        try:
            yield cast(Connection[Any], object())
        except BaseException:
            self._events.append("rollback")
            raise
        else:
            self._events.append("commit")
            if self._commit_failure is not None:
                raise self._commit_failure
        finally:
            self._events.append("close")


class _Repository:
    def __init__(
        self,
        events: list[str],
        *,
        current: Revision | None = None,
        revalidated: bool = True,
        head_failure: BaseException | None = None,
        write_failure: BaseException | None = None,
    ) -> None:
        self._events = events
        self._current = current
        self._revalidated = revalidated
        self._head_failure = head_failure
        self._write_failure = write_failure
        self.created: list[Revision] = []
        self.appended: list[Revision] = []

    def get_head(self, tenant: TenantId) -> RevisionHead | None:
        assert tenant == TENANT
        self._events.append("get_head")
        if self._head_failure is not None:
            raise self._head_failure
        return None if self._current is None else self._current.head()

    def get_revision(self, tenant: TenantId, revision_number: int) -> Revision | None:
        assert tenant == TENANT
        self._events.append("get_revision")
        if self._current is None or self._current.revision_number != revision_number:
            return None
        return self._current

    def revalidate_head(self, tenant: TenantId, expected: RevisionHead) -> bool:
        assert tenant == TENANT
        assert self._current is not None
        assert expected == self._current.head()
        self._events.append("revalidate_head")
        return self._revalidated

    def create_first_revision(self, revision: Revision) -> RevisionHead:
        self._events.append("create_first")
        if self._write_failure is not None:
            raise self._write_failure
        self.created.append(revision)
        self._current = revision
        return revision.head()

    def append_revision(self, revision: Revision) -> RevisionHead:
        self._events.append("append")
        if self._write_failure is not None:
            raise self._write_failure
        self.appended.append(revision)
        self._current = revision
        return revision.head()


def _store(
    repository: _Repository,
    events: list[str],
    *,
    commit_failure: BaseException | None = None,
) -> tuple[PostgresNeo4jGraphStore, _Transactions]:
    transactions = _Transactions(events, commit_failure=commit_failure)

    def repository_factory(_connection: Connection[Any]) -> RevisionRepository:
        return cast(RevisionRepository, repository)

    return (
        PostgresNeo4jGraphStore(
            transactions,
            repository_factory=repository_factory,
            clock=lambda: NOW,
        ),
        transactions,
    )


def _assert_receipt(receipt: WriteReceipt, graph: MemoryGraph) -> None:
    assert receipt.tenant == TENANT
    assert receipt.principal == PRINCIPAL
    assert receipt.content_hash == graph.content_hash()
    assert receipt.node_count == graph.node_count
    assert receipt.edge_count == graph.edge_count


def test_first_write_returns_receipt_after_commit_and_persists_revision_one() -> None:
    events: list[str] = []
    repository = _Repository(events)
    store, transactions = _store(repository, events)
    graph = _graph()

    receipt = store.write(TENANT, graph, principal=PRINCIPAL)
    events.append("returned")

    _assert_receipt(receipt, graph)
    assert transactions.calls == 1
    assert events == ["begin", "get_head", "create_first", "commit", "close", "returned"]
    assert len(repository.created) == 1
    revision = repository.created[0]
    assert revision.revision_number == 1
    assert revision.parent_hash is None
    assert revision.graph_json == graph.model_dump(mode="json")


def test_first_empty_graph_creates_revision_one() -> None:
    events: list[str] = []
    repository = _Repository(events)
    store, _ = _store(repository, events)

    receipt = store.write(TENANT, EMPTY_GRAPH, principal=PRINCIPAL)

    _assert_receipt(receipt, EMPTY_GRAPH)
    assert repository.created[0].revision_number == 1
    assert "revalidate_head" not in events


def test_changed_graph_appends_complete_snapshot_with_correct_receipt_and_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import emg_persistence.store as store_module

    events: list[str] = []
    current = _revision(EMPTY_GRAPH, number=7, parent_hash="a" * 64)
    repository = _Repository(events, current=current)
    store, _ = _store(repository, events)
    graph = _graph()
    change_counts: list[tuple[int, int]] = []

    def recording_diff(before: MemoryGraph, after: MemoryGraph):  # type: ignore[no-untyped-def]
        result = diff_graphs(before, after)
        change_counts.append((len(result.added_nodes), len(result.added_edges)))
        return result

    monkeypatch.setattr(store_module, "diff_graphs", recording_diff)

    receipt = store.write(TENANT, graph, principal=PRINCIPAL)

    _assert_receipt(receipt, graph)
    assert change_counts == [(1, 0)]
    assert len(repository.appended) == 1
    revision = repository.appended[0]
    assert revision.revision_number == 8
    assert revision.parent_hash == current.content_hash
    assert revision.principal == PRINCIPAL
    assert revision.node_count == 1
    assert revision.edge_count == 0
    assert revision.graph_json == graph.model_dump(mode="json")
    assert events == ["begin", "get_head", "get_revision", "append", "commit", "close"]


def test_confirmed_no_op_revalidates_head_creates_no_revision_and_returns_receipt() -> None:
    events: list[str] = []
    graph = _graph()
    repository = _Repository(events, current=_revision(graph, number=3))
    store, _ = _store(repository, events)

    receipt = store.write(TENANT, graph, principal=PRINCIPAL)

    _assert_receipt(receipt, graph)
    assert repository.created == []
    assert repository.appended == []
    assert events == [
        "begin",
        "get_head",
        "get_revision",
        "revalidate_head",
        "commit",
        "close",
    ]


def test_stale_no_op_raises_conflict_and_rolls_back() -> None:
    events: list[str] = []
    graph = _graph()
    repository = _Repository(events, current=_revision(graph), revalidated=False)
    store, _ = _store(repository, events)

    with pytest.raises(PersistenceConflictError, match="head changed"):
        store.write(TENANT, graph, principal=PRINCIPAL)

    assert repository.created == []
    assert repository.appended == []
    assert events[-2:] == ["rollback", "close"]


def test_receipt_is_not_constructed_when_commit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import emg_persistence.store as store_module

    events: list[str] = []
    repository = _Repository(events)
    store, _ = _store(repository, events, commit_failure=RuntimeError("commit failed"))
    receipt_calls = 0
    actual_receipt_for = store_module._receipt_for

    def recording_receipt(*args: object, **kwargs: object) -> WriteReceipt:
        nonlocal receipt_calls
        receipt_calls += 1
        return actual_receipt_for(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module, "_receipt_for", recording_receipt)

    with pytest.raises(RuntimeError, match="commit failed"):
        store.write(TENANT, _graph(), principal=PRINCIPAL)

    assert receipt_calls == 0
    assert events[-2:] == ["commit", "close"]


def test_repeated_historical_hash_is_appended_when_not_current_head() -> None:
    events: list[str] = []
    historical_graph = EMPTY_GRAPH
    current_graph = _graph()
    current = _revision(current_graph, number=2, parent_hash=historical_graph.content_hash())
    repository = _Repository(events, current=current)
    store, _ = _store(repository, events)

    receipt = store.write(TENANT, historical_graph, principal=PRINCIPAL)

    _assert_receipt(receipt, historical_graph)
    assert repository.appended[0].revision_number == 3
    assert repository.appended[0].content_hash == historical_graph.content_hash()
    assert "revalidate_head" not in events


def test_cas_conflict_is_preserved_and_rolls_back() -> None:
    events: list[str] = []
    repository = _Repository(
        events,
        current=_revision(EMPTY_GRAPH),
        write_failure=PersistenceConflictError("head advanced"),
    )
    store, _ = _store(repository, events)

    with pytest.raises(PersistenceConflictError, match="head advanced"):
        store.write(TENANT, _graph(), principal=PRINCIPAL)

    assert events[-2:] == ["rollback", "close"]


def test_repository_driver_failure_is_translated_and_rolls_back() -> None:
    events: list[str] = []
    repository = _Repository(events, head_failure=OperationalError("database unavailable"))
    store, _ = _store(repository, events)

    with pytest.raises(PersistenceError, match="failed to write authoritative graph") as caught:
        store.write(TENANT, EMPTY_GRAPH, principal=PRINCIPAL)

    assert isinstance(caught.value.__cause__, OperationalError)
    assert events == ["begin", "get_head", "rollback", "close"]


def test_direct_write_has_no_neo4j_or_outbox_behavior() -> None:
    events: list[str] = []
    repository = _Repository(events, current=_revision(EMPTY_GRAPH))
    store, _ = _store(repository, events)

    store.write(TENANT, _graph(), principal=PRINCIPAL)

    assert events == ["begin", "get_head", "get_revision", "append", "commit", "close"]
