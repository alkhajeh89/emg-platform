# Persistence Architecture — `emg-persistence`

**Type:** Living engineering reference (L4). Kept current with `develop`.
**Governing authority:** `docs/phases/phase-2/PHASE2_ARCHITECTURE.md` Revision 3
(ADR-1 … ADR-6); Product Architecture Freeze §12; accepted addendum
`docs/architecture/EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md` (P-02).
**Status baseline:** `develop` at `69e2267` (2026-08-09), after RC-1C … RC-1H.
**Scope:** describes what `libs/python/emg-persistence` implements today. It
creates no architecture decision and amends none (GR-001 Rule 8).

> **How to read the status labels.** Every capability below is tagged
> **[Implemented]**, **[Operational prerequisite]**, **[Post-v1]**, or
> **[Non-goal]**. Repository implementation does not imply that a production
> environment has executed or configured it.

---

## 1. Authority model

**[Implemented]** PostgreSQL is the authoritative record. Neo4j is a
rebuildable serving projection and is never on the write open or commit path
(ADR-1, ADR-5). This is a deliberate refinement of Freeze §12's wording, stated
explicitly at `PHASE2_ARCHITECTURE.md:26`: the *authoritative* record is the
PostgreSQL revision log; Neo4j holds the materialized topology for serving.

`PersistenceSettings.is_persistence_configured` keys entirely off
`postgres_dsn` (`config.py:98-106`) — the authoritative datastore decides
whether persistence is configured. Neo4j settings are optional throughout.

Consequence: writes remain available whenever PostgreSQL is available,
regardless of Neo4j's health. Reads remain available on the same condition.

## 2. Neo4j serving projection and fallback

**[Implemented — P-01, `cdbf0ca`, PR #52]** `PostgresNeo4jGraphStore.read`
prefers the Neo4j serving projection with read-repair and falls back to
PostgreSQL:

1. Read the authoritative head from PostgreSQL. No head → `EMPTY_GRAPH`.
2. Resolve the projection. Any failure resolving it → projection treated as
   absent.
3. No projection → return the authoritative PostgreSQL snapshot.
4. Projection present → serve through it, with read-repair against the
   authoritative head.

The authoritative head is consulted **first, always**, so a stale or
unavailable projection can never serve content newer or older than
PostgreSQL's committed head without detection. `ProjectionLagError` is an
internal signal only and is never surfaced from `read()` or `write()`
(`errors.py:34-40`).

**[Implemented]** `LazyNeo4jProjection` constructs no driver until first use,
so a configured-but-unreachable Neo4j costs nothing at composition time.

## 3. Revision history and optimistic concurrency

**[Implemented]** `graph_revisions` is keyed `(tenant_id, revision_number)`
with a deliberately **non-unique** `(tenant_id, content_hash)` index
(`V001__baseline.sql:30-34`) — a rollback legitimately reproduces a prior
content hash (ADR-3). That index must never become `UNIQUE`.

**[Implemented]** Head advancement is compare-and-set: a conditional
`UPDATE graph_head … WHERE head_revision_number = R0`, with a first-revision
`INSERT … ON CONFLICT (tenant_id) DO NOTHING`. A losing writer receives
`PersistenceConflictError` **before any durable change** and is expected to
re-open the transaction and retry (`errors.py:24-31`). No-op writes revalidate
the authoritative head before returning a receipt, so a stale-head receipt is
never issued.

**[Implemented]** Historical reads (`read_revision`) deserialize and
hash-verify the requested revision, raising `SnapshotIntegrityError` on
mismatch rather than returning unverified content.

## 4. Transactional outbox

**[Implemented]** Exactly one `graph.revision.committed` row per committed
revision, written atomically with the revision in the same transaction
(`postgres/outbox_repository.py`; `outbox.idempotency_key` is `UNIQUE`,
`V001__baseline.sql:49`). A no-op write emits no row.

**[Implemented]** `ProjectionWorker` (`projection/worker.py`) consumes outbox
rows and applies the Neo4j projection, checkpointing through
`postgres/checkpoint_repository.py`. It is a **library class**. It is never
started by `GraphStore.write()` (ADR-6) and is invoked explicitly only.

**[Production-readiness dependency]** No continuous worker daemon, scheduler,
or lifecycle exists. Tracked as **TD-002**. Projection freshness today depends
on read-repair and explicit `catch_up_projection(tenant)`.

## 5. Mutation ledger and dispatch

**[Implemented]** `mutation_ledger` (V004) is append-only and enforced as such
at the database by a `BEFORE UPDATE OR DELETE` trigger
(`V004__mutation_ledger.sql:168-181`). Scalar columns are authoritative; stored
JSON is an immutable replay representation validated by trigger against those
scalars.

**[Implemented]** `mutation_dispatch` carries PK `(channel, mutation_id)` and
`channel IN ('audit','event')`. Both channel rows are inserted in the same
transaction as the ledger append (`postgres/mutation_repository.py:305-312`).

**[Implemented — P-05, `8972aa7`, PR #48]** Dispatch claims are bounded.
`claim_dispatch` requires an explicit `max_attempts` (rejected below 1) and the
claim predicate carries `attempt_count < %(max_attempts)s`, so a permanently
failing row cannot be reclaimed without limit. Claiming uses
`FOR UPDATE SKIP LOCKED` with an explicit `limit`.

**[Implemented — ADR-028 / RC-1C]** `services/audit-projector` is the dedicated
consumer of the `audit` channel. It claims tenant-partitioned work through
`PostgresMutationRepository.claim_dispatch()`, projects immutable
`audit_intents` to deterministic SubmittedAuditEvents, and delivers them at
least once to authenticated `POST /audit/events`. Completion occurs only after
all intents succeed; partial delivery replays the mutation and Audit Service
idempotency suppresses duplicates. Retry, attempt exhaustion, lease recovery,
D-51 graceful shutdown, and backlog visibility use existing
`mutation_dispatch` state. V007 grants `emg_audit_projector` schema `USAGE`,
table `SELECT`, and only the five required mutable dispatch columns.

## 6. Evidence ledger

**[Implemented — P-02, `9d464ed` + `c9ce138`, PR #55]** `EvidenceLedgerRepository`
is an **internal** `emg-persistence` capability: a `Protocol` in `evidence.py`
with a PostgreSQL implementation in `postgres/evidence_repository.py`. It is
deliberately **not** exported from `emg_persistence.__all__`, matching
`OutboxRepository` and `RevisionRepository`.

Governing contract: `EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md`, Accepted
2026-08-02, decisions EL-1 … EL-11.

- **Append-only.** Four operations only — `append`, `get`, `list_range`,
  `verify_range`. No update, delete, truncate, repair, replay, or rebuild path
  exists.
- **Per-tenant hash chain.** `seq` starts at 1; the first entry's `prev_hash`
  is the 64-zero genesis sentinel; each later entry links to its predecessor's
  `entry_hash`.
- **Canonical hashing.** SHA-256 over sorted-key compact JSON
  (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`), UTF-8
  encoded, stored as 64 lowercase hex characters. Nine hashed keys, floats
  forbidden at any depth.
- **Verification.** Per-entry hash recomputation is mandatory on every read;
  chain-link verification is an explicit range-scoped operation, never implicit.
- **Fail closed.** `EvidenceLedgerIntegrityError` (a `PersistenceError`
  subclass) is never retryable and is never conflated with
  `PersistenceConflictError`.
- **Independent.** No coupling to `GraphStore`, the outbox, ADR-027, ADR-028,
  or ADR-030 (ADR-4).

**[Non-goal]** P-02 introduced **no ingestion wiring, API route, worker, UI, or
product capability**, and the repository has no production caller today.

**[Implemented — EL-10 / V008]** PostgreSQL now enforces `prev_hash NOT NULL`,
positive sequence values, lowercase SHA-256 field shape, the genesis sentinel,
and an owner-binding `BEFORE UPDATE OR DELETE` append-only trigger. Migration
preflight rejects incompatible existing rows without rewriting them. These are
structural database controls; `verify_range()` remains responsible for
cryptographic entry recomputation and chain-link verification.

## 7. PostgreSQL pooling and connection ownership

**[Implemented — P-04, `8afadb9` + `78a3919`, PR #51]** `ConnectionProvider`
separates connection lifetime from repository behaviour
(`postgres/pool.py`). Two implementations:

- `DirectConnectionProvider` — one connection per acquisition, closed
  deterministically. No pooling.
- `PooledConnectionProvider` — a **lazy, bounded** `psycopg_pool.ConnectionPool`.
  Construction performs no I/O; the first acquisition creates and opens the
  pool. Bounds come from `postgres_pool_min_size` / `postgres_pool_max_size`;
  acquisition and connect both honour `connect_timeout_seconds`.

A returned connection is reset before reuse: any non-`IDLE` transaction status
is rolled back, and a connection that cannot be reset is closed rather than
returned to the pool. `close()` is idempotent and refuses further acquisition.

`build_graph_store` assembles the pooled provider without opening a connection
or constructing a Neo4j driver (`factory.py:29-38`).

## 8. Migrations and least privilege

**[Implemented]** Forward-only, checksum-immutable migrations
(`migrations/runner.py:42, 119-137`). Applied migrations are immutable; a
checksum change halts the runner. Dirty and failed states halt rather than
continue. PostgreSQL migrations are transactional; Neo4j migrations are
idempotent.

Current PostgreSQL migration set:

| Migration | Purpose |
| :--- | :--- |
| V001 | Baseline: `tenants`, `graph_revisions`, `graph_head`, `outbox`, `evidence_ledger` |
| V002 | `projection_checkpoints` |
| V003 | `mutation_idempotency` |
| V004 | `mutation_ledger`, `mutation_ledger_resource`, `mutation_dispatch` + append-only triggers |
| V005 | Runtime least privilege — migrator owns objects; app role gets narrow DML |
| V006 | **P-03** — runtime column-level `UPDATE` privileges |
| V007 | Audit Projector role grants: schema/table reads plus five dispatch update columns |
| V008 | **EL-10** — evidence-ledger preflight, structural constraints, and append-only trigger |

**[Implemented — P-03, `b99b9af`, PR #50]** V006 revokes table-wide `UPDATE`
from `emg_knowledge_graph_app` on `graph_head`, `outbox`,
`projection_checkpoints`, `mutation_idempotency`, and `mutation_dispatch`, and
re-grants `UPDATE` only on the specific columns each repository writes. Role
changes remain conditional so deployments managing roles externally still apply
the schema.

**[Implemented]** `evidence_ledger` is granted `SELECT, INSERT` only
(`V005`) and V008's trigger binds the owner as well as runtime roles. No role
may update or delete ledger rows through ordinary SQL.

**[Implemented — ADR-041]** Audit Service schema evolution is a distinct
packaged stream inside this same migration framework. It uses
`audit_schema_migrations`, is owned by `emg_audit_migrator`, safely adopts the
existing schema shape, and grants `emg_audit_app` append/read privileges only.
Local seed SQL remains a development fixture, not production migration
authority.

## 9. Tenant isolation

**[Implemented]** Every persistence operation is tenant-scoped. `TenantId` is
an explicit parameter on every repository entry point; no statement reaches a
tenant-partitioned table without a `tenant_id` predicate, and all values are
parameterized.

For the evidence ledger this is strengthened twice over: the query predicate
scopes the row, and `tenant_id` is bound into the hashed payload, so a row
relocated between tenants fails hash verification. Verification uses the
**requested** tenant, never the stored column.

**[Non-goal]** No persistence component performs authorization or
classification decisions. No repository takes a principal, clearance, or policy
parameter. Tenant isolation is a structural invariant, not an authorization
decision, and cannot be disabled by configuration (P-02 EL-11; ADR-025/ADR-026
place enforcement in the service layer).

## 10. Dependency direction

```
services/*  ──▶  emg-platform-core (ports)  ◀──  emg-persistence (adapters)
                                                        │
                                                        ▼
                                   PostgreSQL (authoritative) + Neo4j (projection)
```

**[Implemented]** `emg-persistence` implements the unchanged Phase 1
`GraphStore` port and depends on `emg-platform-core`, `emg-errors`,
`emg-memory-graph`, `pydantic`, `psycopg`, `psycopg-pool`, and `neo4j`.
Nothing in `emg-platform-core` depends on `emg-persistence`. Services obtain a
store only through `build_graph_store`.

Repositories (`RevisionRepository`, `OutboxRepository`,
`EvidenceLedgerRepository`, `PostgresMutationRepository`) are internal
contracts — documented, not public (`PHASE2_ARCHITECTURE.md:440`). The package
exports only `PersistenceSettings`, the typed errors, `build_graph_store`, and
`PostgresNeo4jGraphStore`.

The ADR-030 composition adapter deliberately lives in
`services/knowledge-graph/src/emg_knowledge_graph_infrastructure`, not here, to
avoid a reverse dependency from this reusable library into a service.

## 11. Explicit non-goals and deferred work

**[Non-goal — this package will not acquire these]**

- No HTTP surface, API route, or transport of any kind.
- No authorization, classification, or policy evaluation.
- No ingestion pipeline or evidence-capture wiring.
- No product capability.
- No event-sourcing capability beyond the outbox and the evidence chain.

**[Post-v1]**

- Continuous Neo4j `ProjectionWorker` daemon and lifecycle — TD-002. This is
  distinct from the implemented Audit Projector.

**[Operational prerequisite]**

- Metrics collection, dashboards, tracing, and alerting — owned by ADR-015 /
  FEAT-12-3, not by this package.
- Target-environment backup scheduling, KMS/cross-region configuration, and a
  witnessed recovery rehearsal. Provider-neutral backup/PITR/restore tooling
  is implemented; see `persistence-operations.md` §8.

---

## Related documents

- Operations: `docs/engineering/persistence-operations.md`
- Ports contract: `docs/engineering/storage-ports.md`
- Phase 2 architecture (historical, governing): `docs/phases/phase-2/PHASE2_ARCHITECTURE.md`
- Phase 2 completion record (historical): `docs/phases/phase-2/PHASE2_COMPLETION.md`
- Evidence ledger contract: `docs/architecture/EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md`
- Technical debt: `docs/engineering/technical-debt.md`
