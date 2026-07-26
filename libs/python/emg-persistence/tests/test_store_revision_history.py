"""PostgresNeo4jGraphStore: GraphRevisionReader + WriteReceipt revision
identity (ADR-023). Exercised against controlled repository/outbox doubles —
mirrors the existing test_store_write.py pattern (no live database required).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from _outbox_helpers import RecordingOutboxRepository
from _rev_helpers import PRINCIPAL, TENANT
from emg_memory_graph import EvidenceRef, EvidenceSource, MemoryGraph, MemoryNode
from emg_persistence import PersistenceConflictError
from emg_persistence.revisions import Revision, RevisionHead, RevisionRepository
from emg_persistence.revisions.model import RevisionRecord
from emg_persistence.store import PostgresNeo4jGraphStore
from emg_platform_core import HistoricalGraphRevision, RevisionNotFoundError, SnapshotIntegrityError
from psycopg import Connection

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


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


class _Repository:
    """A controllable RevisionRepository double covering both write and
    GraphRevisionReader-backing methods."""

    def __init__(self) -> None:
        self._revisions: dict[int, Revision] = {}
        self._head: RevisionHead | None = None
        self.list_revisions_calls: list[tuple[Any, ...]] = []

    def get_head(self, tenant: Any) -> RevisionHead | None:
        return self._head

    def get_revision(self, tenant: Any, revision_number: int) -> Revision | None:
        return self._revisions.get(revision_number)

    def revision_exists(self, tenant: Any, revision_number: int) -> bool:
        return revision_number in self._revisions

    def revision_count(self, tenant: Any) -> int:
        return len(self._revisions)

    def tenants(self) -> tuple[Any, ...]:
        return (TENANT,) if self._revisions else ()

    def revalidate_head(self, tenant: Any, expected: RevisionHead) -> bool:
        return self._head == expected

    def compare_and_set_head(self, tenant: Any, expected: Any, desired: Any) -> bool:
        raise NotImplementedError

    def create_first_revision(self, revision: Revision) -> RevisionHead:
        self._revisions[revision.revision_number] = revision
        self._head = revision.head()
        return self._head

    def append_revision(self, revision: Revision) -> RevisionHead:
        self._revisions[revision.revision_number] = revision
        self._head = revision.head()
        return self._head

    def list_revisions(
        self, tenant: Any, *, limit: int = 50, before_revision_number: int | None = None
    ) -> tuple[RevisionRecord, ...]:
        self.list_revisions_calls.append((tenant, limit, before_revision_number))
        numbers = sorted(self._revisions, reverse=True)
        if before_revision_number is not None:
            numbers = [n for n in numbers if n < before_revision_number]
        selected = numbers[:limit]
        return tuple(
            RevisionRecord(
                tenant=self._revisions[n].tenant,
                revision_number=self._revisions[n].revision_number,
                content_hash=self._revisions[n].content_hash,
                parent_hash=self._revisions[n].parent_hash,
                principal=self._revisions[n].principal,
                node_count=self._revisions[n].node_count,
                edge_count=self._revisions[n].edge_count,
                created_at=self._revisions[n].created_at,
            )
            for n in selected
        )


class _Transactions:
    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        yield cast(Connection[Any], object())


def _store(repository: _Repository, outbox: RecordingOutboxRepository) -> PostgresNeo4jGraphStore:
    def repository_factory(_connection: Connection[Any]) -> RevisionRepository:
        return cast(RevisionRepository, repository)

    return PostgresNeo4jGraphStore(
        _Transactions(),
        repository_factory=repository_factory,
        outbox_repository_factory=lambda _connection: outbox,
        clock=lambda: NOW,
    )


def test_list_revisions_maps_records_to_platform_core_metadata() -> None:
    repository = _Repository()
    graph = _graph("a")
    repository.create_first_revision(
        Revision(
            tenant=TENANT,
            revision_number=1,
            content_hash=graph.content_hash(),
            parent_hash=None,
            principal=PRINCIPAL,
            node_count=1,
            edge_count=0,
            graph_json=graph.model_dump(mode="json"),
            created_at=NOW,
        )
    )
    store = _store(repository, RecordingOutboxRepository())

    results = store.list_revisions(TENANT, limit=10, before_revision_number=5)

    assert repository.list_revisions_calls == [(TENANT, 10, 5)]
    assert len(results) == 1
    assert results[0].revision_number == 1
    assert results[0].principal == PRINCIPAL
    assert results[0].parent_hash is None
    # never carries a graph — metadata-only.
    assert not hasattr(results[0], "graph")


def test_read_revision_returns_full_historical_graph() -> None:
    repository = _Repository()
    graph = _graph("a", "b")
    revision = Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash=graph.content_hash(),
        parent_hash=None,
        principal=PRINCIPAL,
        node_count=2,
        edge_count=0,
        graph_json=graph.model_dump(mode="json"),
        created_at=NOW,
    )
    repository.create_first_revision(revision)
    store = _store(repository, RecordingOutboxRepository())

    historical = store.read_revision(TENANT, 1)

    assert isinstance(historical, HistoricalGraphRevision)
    assert historical.graph.content_hash() == graph.content_hash()
    assert historical.metadata.revision_number == 1
    assert historical.metadata.principal == PRINCIPAL


def test_read_revision_not_found_raises_typed_error() -> None:
    repository = _Repository()
    store = _store(repository, RecordingOutboxRepository())

    with pytest.raises(RevisionNotFoundError):
        store.read_revision(TENANT, 1)


def test_read_revision_hash_mismatch_raises_snapshot_integrity_error() -> None:
    repository = _Repository()
    graph = _graph("a")
    corrupted = Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash="f" * 64,  # deliberately wrong vs. the actual graph_json
        parent_hash=None,
        principal=PRINCIPAL,
        node_count=1,
        edge_count=0,
        graph_json=graph.model_dump(mode="json"),
        created_at=NOW,
    )
    repository.create_first_revision(corrupted)
    store = _store(repository, RecordingOutboxRepository())

    with pytest.raises(SnapshotIntegrityError):
        store.read_revision(TENANT, 1)


def test_first_write_creates_one_outbox_event_and_matching_receipt() -> None:
    repository = _Repository()
    outbox = RecordingOutboxRepository()
    store = _store(repository, outbox)
    graph = _graph("a")

    receipt = store.write(TENANT, graph, principal=PRINCIPAL)

    assert len(outbox.events) == 1
    assert outbox.events[0].revision_number == 1
    assert receipt.revision_number == 1
    assert receipt.revision_created is True
    assert receipt.committed_at == NOW


def test_no_op_write_creates_no_outbox_event_and_identifies_existing_head() -> None:
    repository = _Repository()
    outbox = RecordingOutboxRepository()
    store = _store(repository, outbox)
    graph = _graph("a")

    first = store.write(TENANT, graph, principal=PRINCIPAL)
    second = store.write(TENANT, graph, principal=PRINCIPAL)

    assert len(outbox.events) == 1  # no new event for the no-op
    assert second.revision_number == first.revision_number == 1
    assert second.revision_created is False
    assert second.committed_at == first.committed_at


def test_append_creates_exactly_one_new_outbox_event() -> None:
    repository = _Repository()
    outbox = RecordingOutboxRepository()
    store = _store(repository, outbox)
    first_graph = _graph("a")
    store.write(TENANT, first_graph, principal=PRINCIPAL)

    second_graph = _graph("a", "b")
    receipt = store.write(TENANT, second_graph, principal=PRINCIPAL)

    assert len(outbox.events) == 2
    assert outbox.events[1].revision_number == 2
    assert receipt.revision_number == 2
    assert receipt.revision_created is True


def test_receipt_revision_identity_matches_stored_head() -> None:
    repository = _Repository()
    store = _store(repository, RecordingOutboxRepository())
    graph = _graph("a")

    receipt = store.write(TENANT, graph, principal=PRINCIPAL)
    stored_head = repository.get_head(TENANT)

    assert stored_head is not None
    assert receipt.revision_number == stored_head.revision_number
    assert receipt.content_hash == stored_head.content_hash


def test_optimistic_conflict_on_append_is_unchanged() -> None:
    repository = _Repository()
    store = _store(repository, RecordingOutboxRepository())
    store.write(TENANT, _graph("a"), principal=PRINCIPAL)

    def _raise_conflict(revision: Revision) -> RevisionHead:
        raise PersistenceConflictError("head advanced")

    repository.append_revision = _raise_conflict  # type: ignore[assignment]

    with pytest.raises(PersistenceConflictError):
        store.write(TENANT, _graph("a", "b"), principal=PRINCIPAL)
