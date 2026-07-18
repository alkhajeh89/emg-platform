"""In-memory ``GraphStore`` adapter (Freeze §32: "an in-memory adapter for tests").

A deterministic, tenant-scoped, in-process implementation of the storage seam.
It performs no I/O and depends only on the immutable ``emg-memory-graph`` model,
so it is safe to use in unit tests and local development. The Neo4j and Postgres
adapters (durability) arrive in Phase 2 behind the *same* ``GraphStore`` port —
this adapter is what proves the port is implementable end-to-end today.

Concurrency & atomicity: a transaction holds the store's reentrant lock for the
**entire** unit of work — from opening (which snapshots the current graph)
through commit or rollback. This makes a transaction strictly serialisable with
every other transaction and with every direct ``read``/``write``/``tenants``
call, so a transaction can never read a stale snapshot and later overwrite a
newer committed state (no lost updates), and a direct write cannot land between a
transaction's snapshot and its commit. This is the simplest correct design for a
single-process store; horizontal scale and finer-grained concurrency (e.g.
optimistic version checks) are persistence-adapter concerns, not a foundation
concern.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum

from emg_memory_graph import EMPTY_GRAPH, MemoryGraph

from ..errors import TransactionStateError
from ..identity import PrincipalRef, TenantId
from ..ports import GraphTransaction, WriteReceipt


class _TxnState(Enum):
    OPEN = "open"
    COMMITTED = "committed"
    ABORTED = "aborted"


class _InMemoryTransaction:
    """A single-tenant read-modify-write unit of work (structurally a
    :class:`~emg_platform_core.ports.GraphTransaction`).

    Lifecycle: created OPEN; ``read``/``stage`` are valid only while OPEN. The
    owning store transitions it to COMMITTED (persisting the staged graph and
    attaching a :class:`WriteReceipt`) on clean context exit, or ABORTED on
    exception. Once closed, ``read``/``stage`` raise ``TransactionStateError``;
    ``receipt`` is available only in the COMMITTED state.
    """

    def __init__(self, tenant: TenantId, principal: PrincipalRef, current: MemoryGraph) -> None:
        self._tenant = tenant
        self._principal = principal
        self._staged = current
        self._state = _TxnState.OPEN
        self._receipt: WriteReceipt | None = None

    @property
    def tenant(self) -> TenantId:
        return self._tenant

    @property
    def principal(self) -> PrincipalRef:
        return self._principal

    @property
    def receipt(self) -> WriteReceipt:
        if self._state is not _TxnState.COMMITTED or self._receipt is None:
            raise TransactionStateError(
                f"receipt is only available after a successful commit "
                f"(transaction is {self._state.value})"
            )
        return self._receipt

    def read(self) -> MemoryGraph:
        self._require_open()
        return self._staged

    def stage(self, graph: MemoryGraph) -> None:
        self._require_open()
        self._staged = graph

    def _require_open(self) -> None:
        if self._state is not _TxnState.OPEN:
            raise TransactionStateError(
                f"transaction is {self._state.value}; read/stage are no longer permitted"
            )

    def _commit(self, receipt: WriteReceipt) -> None:
        self._state = _TxnState.COMMITTED
        self._receipt = receipt

    def _abort(self) -> None:
        self._state = _TxnState.ABORTED


class InMemoryGraphStore:
    """A deterministic, tenant-scoped in-process ``GraphStore``. Test/dev only."""

    def __init__(self) -> None:
        self._graphs: dict[str, MemoryGraph] = {}
        self._tenants: dict[str, TenantId] = {}
        self._lock = threading.RLock()

    def read(self, tenant: TenantId) -> MemoryGraph:
        with self._lock:
            return self._graphs.get(tenant.value, EMPTY_GRAPH)

    def write(
        self, tenant: TenantId, graph: MemoryGraph, *, principal: PrincipalRef
    ) -> WriteReceipt:
        with self._lock:
            self._graphs[tenant.value] = graph
            self._tenants[tenant.value] = tenant
            return self._receipt_for(tenant, principal, graph)

    def tenants(self) -> tuple[TenantId, ...]:
        with self._lock:
            return tuple(self._tenants[key] for key in sorted(self._tenants))

    @contextmanager
    def transaction(self, tenant: TenantId, principal: PrincipalRef) -> Iterator[GraphTransaction]:
        # The lock is held for the ENTIRE unit of work (snapshot -> body ->
        # commit/abort), so no other transaction or direct write can interleave.
        # This is what makes the "no lost update / no stale overwrite" guarantee
        # in the module docstring hold.
        with self._lock:
            current = self._graphs.get(tenant.value, EMPTY_GRAPH)
            txn = _InMemoryTransaction(tenant, principal, current)
            try:
                yield txn
            except BaseException:
                txn._abort()
                raise
            else:
                staged = txn._staged
                self._graphs[tenant.value] = staged
                self._tenants[tenant.value] = tenant
                txn._commit(self._receipt_for(tenant, principal, staged))

    @staticmethod
    def _receipt_for(tenant: TenantId, principal: PrincipalRef, graph: MemoryGraph) -> WriteReceipt:
        return WriteReceipt(
            tenant=tenant,
            principal=principal,
            content_hash=graph.content_hash(),
            node_count=graph.node_count,
            edge_count=graph.edge_count,
        )
