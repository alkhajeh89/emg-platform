"""In-memory ``GraphStore``/``GraphRevisionReader`` adapter.

(Freeze §32: "an in-memory adapter for tests"; ADR-023: history retention +
``GraphRevisionReader``.)

A deterministic, tenant-scoped, in-process implementation of the storage seam.
It performs no I/O and depends only on the immutable ``emg-memory-graph`` model,
so it is safe to use in unit tests and local development. The Neo4j and Postgres
adapters (durability) arrive in Phase 2 behind the *same* ``GraphStore`` port —
this adapter is what proves the port is implementable end-to-end today.

Since ADR-023, this adapter also retains a full, immutable, append-only revision
history per tenant (mirroring the shape ``PostgresNeo4jGraphStore`` already
persists in PostgreSQL) and implements ``GraphRevisionReader`` over it, so
service-layer history/restore code can be exercised in unit tests without a
database.

Concurrency & atomicity: a transaction holds the store's reentrant lock for the
**entire** unit of work — from opening (which snapshots the current graph)
through commit or rollback. This makes a transaction strictly serialisable with
every other transaction and with every direct ``read``/``write``/``tenants``/
history call, so a transaction can never read a stale snapshot and later
overwrite a newer committed state (no lost updates), and a direct write cannot
land between a transaction's snapshot and its commit. This is the simplest
correct design for a single-process store; horizontal scale and finer-grained
concurrency (e.g. optimistic version checks) are persistence-adapter concerns,
not a foundation concern.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum

from emg_memory_graph import EMPTY_GRAPH, MemoryGraph

from ..errors import RevisionNotFoundError, SnapshotIntegrityError, TransactionStateError
from ..identity import PrincipalRef, TenantId
from ..ports.graph_revision_reader import DEFAULT_REVISION_LIST_LIMIT, MAX_REVISION_LIST_LIMIT
from ..ports.graph_store import GraphTransaction, WriteReceipt
from ..ports.revision_metadata import HistoricalGraphRevision, RevisionMetadata

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    """A deterministic, tenant-scoped in-process ``GraphStore`` +
    ``GraphRevisionReader``. Test/dev only.

    Retains a full, immutable, append-only revision history per tenant
    (mirroring the shape ``graph_revisions`` persists durably in PostgreSQL),
    so history/restore workflows are testable without a database.
    """

    def __init__(self, *, clock: Clock = _utcnow) -> None:
        self._history: dict[str, list[HistoricalGraphRevision]] = {}
        self._tenants: dict[str, TenantId] = {}
        self._lock = threading.RLock()
        self._clock = clock

    # --- GraphStore ------------------------------------------------------
    def read(self, tenant: TenantId) -> MemoryGraph:
        with self._lock:
            revisions = self._history.get(tenant.value)
            return revisions[-1].graph if revisions else EMPTY_GRAPH

    def write(
        self, tenant: TenantId, graph: MemoryGraph, *, principal: PrincipalRef
    ) -> WriteReceipt:
        with self._lock:
            self._tenants[tenant.value] = tenant
            return self._commit(tenant, principal, graph)

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
            revisions = self._history.get(tenant.value)
            current = revisions[-1].graph if revisions else EMPTY_GRAPH
            txn = _InMemoryTransaction(tenant, principal, current)
            try:
                yield txn
            except BaseException:
                txn._abort()
                raise
            else:
                self._tenants[tenant.value] = tenant
                receipt = self._commit(tenant, principal, txn._staged)
                txn._commit(receipt)

    # --- GraphRevisionReader ----------------------------------------------
    def list_revisions(
        self,
        tenant: TenantId,
        *,
        limit: int = DEFAULT_REVISION_LIST_LIMIT,
        before_revision_number: int | None = None,
    ) -> tuple[RevisionMetadata, ...]:
        if not 1 <= limit <= MAX_REVISION_LIST_LIMIT:
            raise ValueError(f"limit must be in [1, {MAX_REVISION_LIST_LIMIT}]: {limit!r}")
        with self._lock:
            revisions = self._history.get(tenant.value, [])
            # Stored ascending by revision_number (append order); newest first.
            ordered = list(reversed(revisions))
            if before_revision_number is not None:
                ordered = [
                    rev for rev in ordered if rev.metadata.revision_number < before_revision_number
                ]
            return tuple(rev.metadata for rev in ordered[:limit])

    def read_revision(self, tenant: TenantId, revision_number: int) -> HistoricalGraphRevision:
        with self._lock:
            revisions = self._history.get(tenant.value, [])
            for rev in revisions:
                if rev.metadata.revision_number == revision_number:
                    actual_hash = rev.graph.content_hash()
                    if actual_hash != rev.metadata.content_hash:
                        raise SnapshotIntegrityError(
                            f"stored snapshot hash mismatch at revision {revision_number} "
                            f"for tenant {tenant.value!r}"
                        )
                    return rev
            raise RevisionNotFoundError(
                f"no revision {revision_number} for tenant {tenant.value!r}"
            )

    # --- internal ----------------------------------------------------------
    def _commit(
        self, tenant: TenantId, principal: PrincipalRef, graph: MemoryGraph
    ) -> WriteReceipt:
        """Append ``graph`` as the next revision, or no-op if unchanged (caller
        holds the lock)."""
        revisions = self._history.setdefault(tenant.value, [])
        staged_hash = graph.content_hash()
        current_head = revisions[-1] if revisions else None

        if current_head is not None and staged_hash == current_head.metadata.content_hash:
            head_meta = current_head.metadata
            return WriteReceipt(
                tenant=tenant,
                principal=principal,
                content_hash=head_meta.content_hash,
                node_count=head_meta.node_count,
                edge_count=head_meta.edge_count,
                revision_number=head_meta.revision_number,
                committed_at=head_meta.created_at,
                revision_created=False,
            )

        revision_number = 1 if current_head is None else current_head.metadata.revision_number + 1
        parent_hash = None if current_head is None else current_head.metadata.content_hash
        created_at = self._clock()
        metadata = RevisionMetadata(
            tenant=tenant,
            revision_number=revision_number,
            content_hash=staged_hash,
            parent_hash=parent_hash,
            principal=principal,
            node_count=graph.node_count,
            edge_count=graph.edge_count,
            created_at=created_at,
        )
        revisions.append(HistoricalGraphRevision(metadata=metadata, graph=graph))
        return WriteReceipt(
            tenant=tenant,
            principal=principal,
            content_hash=staged_hash,
            node_count=graph.node_count,
            edge_count=graph.edge_count,
            revision_number=revision_number,
            committed_at=created_at,
            revision_created=True,
        )
