# emg-persistence

**EMG Persistence Binding.** Durable `GraphStore` adapters for the Enterprise
Memory Graph, behind the unchanged Phase 1 `GraphStore` port.

Architecture (approved `PHASE2_ARCHITECTURE.md` Revision 3, ADR-1 … ADR-6):

- **PostgreSQL is authoritative** for the revision log and head pointer
  (ADR-1). Transaction open, commit, and the read fallback use PostgreSQL only
  (ADR-5).
- **Neo4j is a rebuildable serving projection** — never on the write path.
  Current reads prefer it with read-repair and fall back to PostgreSQL when it
  is unavailable.

**Status: Phase 2 complete and merged, plus the P-01 … P-05 hardening series.**
This package contains the full PostgreSQL and Neo4j implementation, schema
migrations V001–V006, repositories, and the internal evidence ledger. Validated
in the `persistence` CI job against PostgreSQL 16 and Neo4j 5 Community.

> Full engineering detail lives in two living documents:
> [`docs/engineering/persistence-architecture.md`](../../../docs/engineering/persistence-architecture.md)
> and
> [`docs/engineering/persistence-operations.md`](../../../docs/engineering/persistence-operations.md).
> This README is a summary pointer and is not kept in sync line-by-line with
> them.

## What this package provides

| Area | Module | Notes |
| :--- | :--- | :--- |
| Configuration | `config.py` | `PersistenceSettings` — DSNs, pool bounds, timeouts, from `EMG_PERSISTENCE_*`. Secrets are `SecretStr` |
| Composition | `factory.py` | `build_graph_store(settings)` — the only seam services use. In-memory without a PostgreSQL DSN; lazy persistent store with one |
| Store | `store.py` | `PostgresNeo4jGraphStore` — compare-and-set head advancement, historical reads, Neo4j-preferred current reads with PostgreSQL fallback |
| Revisions | `postgres/revision_repository.py` | `graph_revisions` / `graph_head`; non-unique `(tenant_id, content_hash)` index (ADR-3) |
| Outbox | `postgres/outbox_repository.py` | One `graph.revision.committed` row per committed revision, written in the same transaction |
| Projection | `neo4j/`, `projection/` | Lazy driver, diff-based idempotent apply, catch-up / read-repair / rebuild, checkpointing |
| Mutation ledger | `postgres/mutation_repository.py` | ADR-030 ledger, idempotency, and bounded dispatch claims |
| Evidence ledger | `evidence.py`, `postgres/evidence_repository.py` | **Internal** append-only, tenant-scoped hash chain (P-02) |
| Connections | `postgres/pool.py` | `DirectConnectionProvider` and the lazy bounded `PooledConnectionProvider` |
| Migrations | `migrations/`, `migrate.py` | Forward-only, checksum-immutable, dirty/failed halting |

## Public surface

The package deliberately exports very little:

```python
from emg_persistence import (
    PersistenceSettings,
    build_graph_store,
    PostgresNeo4jGraphStore,
    PersistenceError,
    PersistenceConflictError,
    EvidenceLedgerIntegrityError,
    ProjectionLagError,
)
```

Repositories — `RevisionRepository`, `OutboxRepository`,
`EvidenceLedgerRepository`, `PostgresMutationRepository` — are **internal
contracts: documented, not public** (`PHASE2_ARCHITECTURE.md:440`). They are not
exported and must not be imported across the package boundary.

## Error semantics

- `PersistenceConflictError` — optimistic-concurrency conflict, raised before
  any durable change. **Retryable**: re-open the transaction and retry.
- `EvidenceLedgerIntegrityError` — stored evidence failed verification.
  **Never retryable**, and never conflated with a conflict.
- `ProjectionLagError` — internal read-repair signal only; never surfaced from
  `read()` or `write()`.
- `SnapshotIntegrityError` — a stored revision failed hash verification.

## Evidence ledger (P-02)

`EvidenceLedgerRepository` is an internal, append-only, per-tenant hash chain
governed by
[`EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md`](../../../docs/architecture/EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md)
(Accepted 2026-08-02, decisions EL-1 … EL-11). Four operations only: `append`,
`get`, `list_range`, `verify_range`.

Acceptance authorized **only the repository contract**. There is **no ingestion
wiring, API, worker, UI, or product capability**, and no production caller
exists today. It is independent of `GraphStore`, the outbox, ADR-027, ADR-028,
and ADR-030 (ADR-4).

## Not in this package

No HTTP surface, no authorization or classification decisions, no ingestion
pipeline, no product capability, and no continuous projection worker daemon
(TD-002 — `ProjectionWorker` is a library class, invoked explicitly).
