"""Storage ports — the storage-independence seam (Freeze §11, §32).

These ``Protocol``s are the abstract contract through which services read and
write the immutable ``MemoryGraph``. They are expressed **purely in domain
terms** — a tenant, a principal, and a graph snapshot — with no database
concepts, so any backing store (in-memory now; Neo4j/Postgres in Phase 2) is
swappable behind them.

Frozen basis:
  * §11 "one writer per store … all cross-context change flows through APIs or
    events; every mutation emits an audit record" → writes are explicit,
    principal-stamped, and return a receipt.
  * §32 "Introduce a ``GraphStore`` port … with a Neo4j adapter for durability
    and an in-memory adapter for tests."

No I/O is performed *here* — this module only declares the contract and a small
frozen ``WriteReceipt`` value type (Freeze §9: the core performs no I/O).
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from emg_memory_graph import MemoryGraph
from pydantic import BaseModel, ConfigDict, Field

from ..identity import PrincipalRef, TenantId


class WriteReceipt(BaseModel):
    """Immutable proof of a persisted write.

    Records *what* was written (deterministic ``content_hash`` of the stored
    graph, plus counts) and *who/where* (principal + tenant). This is the seed of
    the audit spine (Freeze §11): later phases emit an audit record from it. It
    contains no storage-specific detail, so it is identical across adapters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    principal: PrincipalRef
    # A graph content hash is a SHA-256 hex digest: exactly 64 lowercase hex
    # characters. Validating the shape (not just the length) rejects malformed
    # or upper-cased values that could otherwise slip through.
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)


@runtime_checkable
class GraphTransaction(Protocol):
    """A unit of work over one tenant's graph: read the current snapshot, stage a
    replacement, commit atomically on context exit.

    Read-modify-write must be atomic so concurrent writers cannot interleave and
    lose data; the concrete adapter provides the atomicity guarantee. Using a
    staged snapshot (rather than in-place mutation) preserves the immutability of
    ``MemoryGraph`` (Freeze §9/§32).
    """

    @property
    def tenant(self) -> TenantId: ...

    @property
    def principal(self) -> PrincipalRef: ...

    @property
    def receipt(self) -> WriteReceipt:
        """The :class:`WriteReceipt` for this transaction's committed write.

        Available only *after* the ``with`` block exits successfully (commit).
        Accessing it before commit, or after a rollback/abort, raises
        ``emg_platform_core.errors.TransactionStateError``.
        """
        ...

    def read(self) -> MemoryGraph:
        """Return the current graph snapshot within this transaction. Raises
        ``TransactionStateError`` once the transaction has committed or aborted."""
        ...

    def stage(self, graph: MemoryGraph) -> None:
        """Stage ``graph`` as the new snapshot to be committed on context exit.
        Raises ``TransactionStateError`` once the transaction has committed or
        aborted."""
        ...


@runtime_checkable
class GraphStore(Protocol):
    """The storage-independent contract for persisting tenant-scoped graphs.

    A single logical writer per tenant (Freeze §11). Implementations must be
    deterministic in what they return for a given stored state so higher layers
    remain reproducible.
    """

    def read(self, tenant: TenantId) -> MemoryGraph:
        """Return the current graph snapshot for ``tenant`` (empty if none)."""
        ...

    def write(
        self, tenant: TenantId, graph: MemoryGraph, *, principal: PrincipalRef
    ) -> WriteReceipt:
        """Persist ``graph`` as the new current snapshot for ``tenant``, stamped
        with the asserting ``principal``; return a :class:`WriteReceipt`."""
        ...

    def tenants(self) -> tuple[TenantId, ...]:
        """Return the tenants that currently have a stored graph (sorted)."""
        ...

    def transaction(
        self, tenant: TenantId, principal: PrincipalRef
    ) -> AbstractContextManager[GraphTransaction]:
        """Open an atomic read-modify-write unit of work for ``tenant``."""
        ...
