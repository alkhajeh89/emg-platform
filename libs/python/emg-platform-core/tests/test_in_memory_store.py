"""InMemoryGraphStore behaviour: read/write, tenant isolation, determinism,
transactions (commit, rollback, lifecycle)."""

from __future__ import annotations

import pytest
from _pc_helpers import sample_graph
from emg_platform_core import (
    PrincipalRef,
    TenantId,
    TransactionStateError,
)
from emg_platform_core.adapters.in_memory import InMemoryGraphStore

T_A = TenantId.of("tenant-a")
T_B = TenantId.of("tenant-b")
P = PrincipalRef.service("ingest-svc")


def test_read_missing_tenant_returns_empty() -> None:
    store = InMemoryGraphStore()
    g = store.read(T_A)
    assert g.node_count == 0 and g.edge_count == 0


def test_write_returns_faithful_receipt() -> None:
    store = InMemoryGraphStore()
    g = sample_graph("a", "b")
    receipt = store.write(T_A, g, principal=P)
    assert receipt.tenant == T_A
    assert receipt.principal == P
    assert receipt.content_hash == g.content_hash()
    assert receipt.node_count == g.node_count == 2
    assert receipt.edge_count == g.edge_count == 0


def test_read_after_write_roundtrips() -> None:
    store = InMemoryGraphStore()
    g = sample_graph("a", "b", "c")
    store.write(T_A, g, principal=P)
    assert store.read(T_A).content_hash() == g.content_hash()


def test_tenant_isolation() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)
    assert store.read(T_B).node_count == 0  # B is untouched by A's write
    store.write(T_B, sample_graph("x", "y"), principal=P)
    assert store.read(T_A).node_count == 1
    assert store.read(T_B).node_count == 2


def test_tenants_sorted() -> None:
    store = InMemoryGraphStore()
    store.write(TenantId.of("zeta"), sample_graph("a"), principal=P)
    store.write(TenantId.of("alpha"), sample_graph("b"), principal=P)
    assert store.tenants() == (TenantId.of("alpha"), TenantId.of("zeta"))


def test_determinism_across_stores() -> None:
    g = sample_graph("a", "b")
    r1 = InMemoryGraphStore().write(T_A, g, principal=P)
    r2 = InMemoryGraphStore().write(T_A, g, principal=P)
    assert r1.content_hash == r2.content_hash


def test_transaction_commits_staged_graph() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)
    with store.transaction(T_A, P) as txn:
        assert txn.read().node_count == 1  # sees current committed state
        txn.stage(sample_graph("a", "b", "c"))
        assert txn.read().node_count == 3  # sees staged state within txn
    assert store.read(T_A).node_count == 3  # committed on clean exit


def test_transaction_rolls_back_on_exception() -> None:
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("a"), principal=P)

    class Boom(Exception):
        pass

    with pytest.raises(Boom), store.transaction(T_A, P) as txn:
        txn.stage(sample_graph("a", "b", "c", "d"))
        raise Boom
    assert store.read(T_A).node_count == 1  # unchanged — staged work discarded


def test_committed_transaction_is_closed() -> None:
    store = InMemoryGraphStore()
    captured = {}
    with store.transaction(T_A, P) as txn:
        captured["txn"] = txn
        txn.stage(sample_graph("a"))
    dead = captured["txn"]
    with pytest.raises(TransactionStateError):
        dead.read()
    with pytest.raises(TransactionStateError):
        dead.stage(sample_graph("z"))


def test_rolled_back_transaction_is_closed() -> None:
    store = InMemoryGraphStore()
    captured = {}

    class Boom(Exception):
        pass

    with pytest.raises(Boom), store.transaction(T_A, P) as txn:
        captured["txn"] = txn
        txn.stage(sample_graph("a"))
        raise Boom
    dead = captured["txn"]
    with pytest.raises(TransactionStateError):
        dead.read()
    with pytest.raises(TransactionStateError):
        dead.stage(sample_graph("z"))


def test_receipt_available_after_commit_with_correct_fields() -> None:
    store = InMemoryGraphStore()
    captured = {}
    with store.transaction(T_A, P) as txn:
        captured["txn"] = txn
        txn.stage(sample_graph("a", "b"))
    receipt = captured["txn"].receipt
    assert receipt.tenant == T_A
    assert receipt.principal == P
    assert receipt.content_hash == store.read(T_A).content_hash()
    assert receipt.node_count == 2
    assert receipt.edge_count == 0


def test_receipt_unavailable_before_commit() -> None:
    store = InMemoryGraphStore()
    with store.transaction(T_A, P) as txn:
        txn.stage(sample_graph("a"))
        with pytest.raises(TransactionStateError):
            _ = txn.receipt  # not yet committed


def test_receipt_unavailable_after_rollback() -> None:
    store = InMemoryGraphStore()
    captured = {}

    class Boom(Exception):
        pass

    with pytest.raises(Boom), store.transaction(T_A, P) as txn:
        captured["txn"] = txn
        txn.stage(sample_graph("a"))
        raise Boom
    with pytest.raises(TransactionStateError):
        _ = captured["txn"].receipt


def test_transaction_on_new_tenant_starts_empty() -> None:
    store = InMemoryGraphStore()
    with store.transaction(T_B, P) as txn:
        assert txn.read().node_count == 0
        txn.stage(sample_graph("x"))
    assert store.read(T_B).node_count == 1
