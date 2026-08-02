# Storage Ports — contract reference

The `emg_platform_core.ports` contracts that decouple EMG services from any
specific database (Freeze §11 "one writer per store … storage-independent",
§32 "Introduce a `GraphStore` port"). This page is the authoritative contract
that Phase 2's Neo4j/Postgres adapters must satisfy.

## `GraphStore`

```python
@runtime_checkable
class GraphStore(Protocol):
    def read(self, tenant: TenantId) -> MemoryGraph: ...
    def write(self, tenant: TenantId, graph: MemoryGraph, *,
              principal: PrincipalRef) -> WriteReceipt: ...
    def tenants(self) -> tuple[TenantId, ...]: ...
    def transaction(self, tenant: TenantId,
                    principal: PrincipalRef) -> AbstractContextManager[GraphTransaction]: ...
```

Contract obligations for any implementation:

| Method | Obligation |
|---|---|
| `read` | Return the current snapshot for `tenant`; the empty graph if the tenant has none. Never raise for an unknown tenant. |
| `write` | Persist `graph` as the new current snapshot for `tenant`, stamped with `principal`. Return a faithful `WriteReceipt` (hash + counts of what was stored). One logical writer per tenant (Freeze §11). |
| `tenants` | Return the tenants with a stored graph, deterministically sorted. |
| `transaction` | Provide an **atomic** read-modify-write unit of work; concurrent transactions must not interleave to lose data. |

Determinism obligation: for a given stored state, `read` and `tenants` must
return equal values across runs and machines (higher layers rely on
reproducibility).

## `GraphTransaction`

```python
@runtime_checkable
class GraphTransaction(Protocol):
    @property
    def tenant(self) -> TenantId: ...
    @property
    def principal(self) -> PrincipalRef: ...
    @property
    def receipt(self) -> WriteReceipt: ...      # after successful commit only
    def read(self) -> MemoryGraph: ...
    def stage(self, graph: MemoryGraph) -> None: ...
```

Lifecycle: obtained via `store.transaction(tenant, principal)` as a context
manager. `read()` returns the current (or staged) snapshot; `stage(graph)` sets
the pending snapshot; the unit of work **commits on clean context exit** and
**rolls back if the block raises**.

- After the context closes (committed *or* aborted), `read()` and `stage()`
  raise `TransactionStateError`.
- `receipt` is available **only after a successful commit**; accessing it before
  commit or after a rollback raises `TransactionStateError`.
- **Atomicity obligation:** an implementation must make the whole unit of work
  serialisable with other transactions and direct writes, so a transaction
  cannot read a stale snapshot and later overwrite a newer committed state (no
  lost updates), and a direct write cannot interleave between a transaction's
  snapshot and its commit. (`InMemoryGraphStore` satisfies this by holding its
  lock across the entire context.)

```python
with store.transaction(tenant, principal) as txn:
    current = txn.read()
    updated = build_next(current)          # pure domain computation
    txn.stage(updated)
# committed here (atomically); on exception nothing is persisted
receipt = txn.receipt                      # available only after the clean exit above
```

## `WriteReceipt`

```python
class WriteReceipt(BaseModel):   # frozen
    tenant: TenantId
    principal: PrincipalRef
    content_hash: str            # 64-char sha256 of the stored graph
    node_count: int              # >= 0
    edge_count: int              # >= 0
```

Storage-agnostic proof of a write and the seed of the audit spine (Freeze §11).
Every adapter returns the same shape, so audit emission (a later phase) is
adapter-independent.

## Adapters

| Adapter | Phase | Purpose |
|---|---|---|
| `InMemoryGraphStore` | 1 (this) | Deterministic, in-process; tests & local dev. |
| Neo4j adapter | 2 | Graph of record (durability). Freeze §12, §30. |
| Postgres adapter | 2 | Metadata, versions, evidence ledger, outbox. Freeze §12, §30, §31. |

Any new adapter must satisfy the obligations above; the in-memory adapter's test
suite (`libs/python/emg-platform-core/tests`) is the executable contract those
adapters should also be tested against in Phase 2.

> **Reconciliation note — 2026-08-03.** The Phase 1 expectation recorded in the
> table above ("Neo4j adapter — Graph of record") is **not** how Phase 2 was
> built, and the original row is preserved only as a record of that expectation.
> Phase 2 deliberately refined it (`PHASE2_ARCHITECTURE.md:26`, ADR-1/ADR-5):
> **PostgreSQL is the authoritative record** for revisions, head pointer,
> outbox, mutation ledger, and evidence ledger; **Neo4j is a rebuildable
> serving projection** and is never on the write path. There is one adapter,
> `PostgresNeo4jGraphStore`, not two. Current reads prefer Neo4j with
> read-repair and fall back to PostgreSQL when it is unavailable (P-01).
> See `docs/engineering/persistence-architecture.md` for the implemented design.
