"""Adversarial concurrency + lifecycle tests for the transaction atomicity
guarantee (no lost updates, no stale overwrite of a direct write).

These exercise the guarantee that a transaction holds the store lock across its
entire unit of work, so transactions are strictly serialisable with each other
and with direct writes.
"""

from __future__ import annotations

import threading

from _pc_helpers import extend_graph, sample_graph
from emg_platform_core import PrincipalRef, TenantId
from emg_platform_core.adapters.in_memory import InMemoryGraphStore

T_A = TenantId.of("tenant-a")
P = PrincipalRef.service("ingest-svc")


def test_concurrent_transactions_do_not_lose_updates() -> None:
    """N threads each read-modify-write (add one distinct node) concurrently.
    With correct serialisation, every update survives -> exactly N nodes. Under a
    lost-update bug (lock released during the body), some updates overwrite
    others and the count would be < N."""
    store = InMemoryGraphStore()
    n = 12
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait()  # maximise contention: all start together
            with store.transaction(T_A, P) as txn:
                current = txn.read()
                txn.stage(extend_graph(current, f"n{i}"))
        except BaseException as exc:  # pragma: no cover - only on unexpected failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    final = store.read(T_A)
    assert final.node_count == n
    assert {node.node_id for node in final.nodes} == {f"n{i}" for i in range(n)}


def test_direct_write_not_overwritten_by_stale_transaction() -> None:
    """A direct write that is attempted while a transaction is in flight must not
    be silently lost. Because the transaction holds the lock for its whole body,
    the direct write serialises after the commit and survives."""
    store = InMemoryGraphStore()
    store.write(T_A, sample_graph("base"), principal=P)

    in_txn = threading.Event()
    release = threading.Event()

    def txn_worker() -> None:
        with store.transaction(T_A, P) as txn:
            current = txn.read()
            in_txn.set()  # signal: we are inside the txn (holding the lock)
            release.wait(timeout=5)
            txn.stage(extend_graph(current, "from_txn"))

    t = threading.Thread(target=txn_worker)
    t.start()
    assert in_txn.wait(timeout=5)

    # Release the txn to commit, then perform a direct write. Under the lock-held
    # design this write blocks until the txn commits, then applies on top of it.
    release.set()
    store.write(T_A, sample_graph("direct"), principal=P)
    t.join(timeout=5)

    ids = {node.node_id for node in store.read(T_A).nodes}
    assert "direct" in ids  # the direct write was not silently overwritten
