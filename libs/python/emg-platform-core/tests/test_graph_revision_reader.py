"""GraphRevisionReader + WriteReceipt revision-identity contract (ADR-023).

Exercised against InMemoryGraphStore, the reference adapter that implements
both GraphStore and GraphRevisionReader.
"""

from __future__ import annotations

import pytest
from _pc_helpers import extend_graph, sample_graph
from emg_platform_core import (
    MAX_REVISION_LIST_LIMIT,
    GraphRevisionReader,
    HistoricalGraphRevision,
    PrincipalRef,
    RevisionMetadata,
    RevisionNotFoundError,
    TenantId,
    TransactionStateError,
)
from emg_platform_core.adapters.in_memory import InMemoryGraphStore
from pydantic import ValidationError

T_A = TenantId.of("tenant-a")
T_B = TenantId.of("tenant-b")
P = PrincipalRef.service("ingest-svc")
P2 = PrincipalRef.service("restorer-svc")


def test_store_satisfies_graph_revision_reader_protocol() -> None:
    store = InMemoryGraphStore()
    assert isinstance(store, GraphRevisionReader)


def test_first_revision_receipt_identity() -> None:
    store = InMemoryGraphStore()
    receipt = store.write(T_A, sample_graph("a"), principal=P)
    assert receipt.revision_number == 1
    assert receipt.revision_created is True


def test_append_receipt_identity() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)
    receipt = store.write(T_A, extend_graph(sample_graph("a"), "b"), principal=P)
    assert receipt.revision_number == 2
    assert receipt.revision_created is True


def test_no_op_receipt_identity_and_committed_at_stability() -> None:
    store = InMemoryGraphStore()
    graph = sample_graph("a", "b")
    first = store.write(T_A, graph, principal=P)

    no_op = store.write(T_A, graph, principal=P)

    assert no_op.revision_number == first.revision_number == 1
    assert no_op.revision_created is False
    # committed_at must identify the EXISTING head's commit time, not the
    # wall-clock time of the no-op call.
    assert no_op.committed_at == first.committed_at
    assert no_op.content_hash == first.content_hash


def test_repeated_no_op_never_advances_revision_number() -> None:
    store = InMemoryGraphStore()
    graph = sample_graph("a")
    store.write(T_A, graph, principal=P)
    for _ in range(3):
        receipt = store.write(T_A, graph, principal=P)
        assert receipt.revision_number == 1
        assert receipt.revision_created is False


def test_transaction_rollback_creates_no_history_entry() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)

    class Boom(Exception):
        pass

    with pytest.raises(Boom), store.transaction(T_A, P) as txn:
        txn.stage(sample_graph("a", "b", "c"))
        raise Boom

    history = store.list_revisions(T_A)
    assert len(history) == 1
    assert history[0].revision_number == 1
    # current-state read is unaffected by the rollback
    assert store.read(T_A).node_count == 1


def test_descending_history_order() -> None:
    store = InMemoryGraphStore()
    graph = sample_graph("a")
    store.write(T_A, graph, principal=P)  # revision 1
    for extra in ("b", "c", "d"):
        graph = extend_graph(graph, extra)
        store.write(T_A, graph, principal=P)  # revisions 2, 3, 4

    history = store.list_revisions(T_A)
    numbers = [rev.revision_number for rev in history]
    assert numbers == sorted(numbers, reverse=True)
    assert numbers == [4, 3, 2, 1]


def test_exclusive_before_revision_number_cursor() -> None:
    store = InMemoryGraphStore()
    graph = sample_graph("a")
    store.write(T_A, graph, principal=P)  # revision 1
    for extra in ("b", "c"):
        graph = extend_graph(graph, extra)
        store.write(T_A, graph, principal=P)  # revisions 2, 3

    page = store.list_revisions(T_A, before_revision_number=3)
    assert [rev.revision_number for rev in page] == [2, 1]

    page2 = store.list_revisions(T_A, before_revision_number=1)
    assert page2 == ()


def test_bounded_limit_enforced() -> None:
    store = InMemoryGraphStore()
    graph = sample_graph("a")
    store.write(T_A, graph, principal=P)  # revision 1
    for extra in ("b", "c", "d"):
        graph = extend_graph(graph, extra)
        store.write(T_A, graph, principal=P)  # revisions 2, 3, 4

    page = store.list_revisions(T_A, limit=2)
    assert [rev.revision_number for rev in page] == [4, 3]

    with pytest.raises(ValueError):
        store.list_revisions(T_A, limit=0)
    with pytest.raises(ValueError):
        store.list_revisions(T_A, limit=MAX_REVISION_LIST_LIMIT + 1)


def test_empty_history_lists_as_empty_tuple() -> None:
    store = InMemoryGraphStore()
    assert store.list_revisions(T_A) == ()


def test_tenant_isolation_in_history() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)
    store.write(T_B, sample_graph("x"), principal=P)
    store.write(T_B, extend_graph(sample_graph("x"), "y"), principal=P)

    assert len(store.list_revisions(T_A)) == 1
    assert len(store.list_revisions(T_B)) == 2

    with pytest.raises(RevisionNotFoundError):
        # revision 2 exists for tenant B, not tenant A — must not leak.
        store.read_revision(T_A, 2)


def test_historical_non_head_read_returns_exact_prior_graph() -> None:
    store = InMemoryGraphStore()
    first_graph = sample_graph("a")
    store.write(T_A, first_graph, principal=P)
    second_graph = extend_graph(first_graph, "b")
    store.write(T_A, second_graph, principal=P)

    historical = store.read_revision(T_A, 1)
    assert isinstance(historical, HistoricalGraphRevision)
    assert historical.graph.content_hash() == first_graph.content_hash()
    assert historical.metadata.revision_number == 1
    assert historical.metadata.parent_hash is None

    current = store.read(T_A)
    assert current.content_hash() == second_graph.content_hash()


def test_read_revision_not_found() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)
    with pytest.raises(RevisionNotFoundError):
        store.read_revision(T_A, 999)


def test_read_revision_on_empty_tenant_not_found() -> None:
    store = InMemoryGraphStore()
    with pytest.raises(RevisionNotFoundError):
        store.read_revision(T_A, 1)


def test_metadata_principal_and_first_revision_parent_hash() -> None:
    store = InMemoryGraphStore()
    receipt = store.write(T_A, sample_graph("a"), principal=P)
    historical = store.read_revision(T_A, 1)
    assert historical.metadata.principal == P
    assert historical.metadata.parent_hash is None
    assert historical.metadata.content_hash == receipt.content_hash


def test_second_revision_parent_hash_matches_first_content_hash() -> None:
    store = InMemoryGraphStore()
    first_graph = sample_graph("a")
    first = store.write(T_A, first_graph, principal=P)
    store.write(T_A, extend_graph(first_graph, "b"), principal=P)

    second_meta = store.read_revision(T_A, 2).metadata
    assert second_meta.parent_hash == first.content_hash


def test_history_is_immutable_after_further_writes() -> None:
    store = InMemoryGraphStore()
    first_graph = sample_graph("a")
    store.write(T_A, first_graph, principal=P)
    for extra in ("b", "c", "d"):
        first_graph_extended = extend_graph(store.read(T_A), extra)
        store.write(T_A, first_graph_extended, principal=P)

    # revision 1's stored graph/metadata never changes underneath later writes.
    historical = store.read_revision(T_A, 1)
    assert historical.graph.node_count == 1
    assert historical.metadata.revision_number == 1


def test_isinstance_check_does_not_mutate_state() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)
    assert isinstance(store, GraphRevisionReader)
    assert store.list_revisions(T_A)[0].revision_number == 1


def test_revision_metadata_is_frozen() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)
    metadata = store.list_revisions(T_A)[0]
    assert isinstance(metadata, RevisionMetadata)
    with pytest.raises(ValidationError):
        metadata.revision_number = 99  # type: ignore[misc]


def test_transaction_state_error_unrelated_to_history() -> None:
    # Sanity check: history additions must not weaken existing transaction
    # lifecycle guards.
    store = InMemoryGraphStore()
    with store.transaction(T_A, P) as txn:
        txn.stage(sample_graph("a"))
    with pytest.raises(TransactionStateError):
        txn.stage(sample_graph("z"))
