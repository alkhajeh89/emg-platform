# Phase 2 — Persistence Binding — Architecture Design (for review, rev 3)

**Phase:** 2 — Persistence Binding
**Status:** DESIGN — for architectural review only. **No code in this document; no implementation until approved.**
**Revision:** 3 (rev 2 comments 1–11 resolved; **rev 3** resolves three blocking issues: (1) PostgreSQL-only write open/commit path — Neo4j off the write path; (2) no-op head revalidation; (3) concrete projection execution model + read fallback — ADR-5, ADR-6).
**Date:** 2026-07-19
**Base:** `develop` (Phase 1 merged: `38ffcf7`, `5373009`).
**Governing baseline:** `EMG_PRODUCT_ARCHITECTURE_FREEZE.md` (v1.0-FROZEN) and the Phase 1 `GraphStore` port (`libs/python/emg-platform-core`).

> **Approved decisions carried into rev 2:**
> - **D1 — Tenant scoping stays at the `GraphStore`/storage boundary.** `MemoryGraph` is explicitly **single-tenant**; every *persisted* datum is tenant-scoped. The frozen `emg-memory-graph` models are not modified.
> - **D2 — PostgreSQL authoritative log + Neo4j projection** (no distributed/2PC transaction).
> - **D3 — New package `libs/python/emg-persistence`.**
> - **DB-backed CI approved.** Neo4j **Community Edition** is the default (see §15 for the justification that Enterprise is *not* required for Phase 2).

---

## 0. Architecture Decision Records (ADRs)

### ADR-1 — Single source of truth: PostgreSQL is authoritative; Neo4j is a projection

**Decision.** **PostgreSQL is the single authoritative source of truth** for the memory graph — specifically the append-only, hash-linked **revision log** plus the per-tenant **head** pointer. **Neo4j is a queryable topology projection (the serving graph)**, derived from and rebuildable from the PostgreSQL revision log. Neo4j is **never** described or treated as the graph of record or the source of truth.

**Status.** Accepted (supersedes rev 1, which inconsistently called Neo4j the "graph of record" while also making PostgreSQL authoritative).

**Is this an interpretation of Freeze §12, or a deliberate refinement?** **It is a deliberate architectural refinement, stated explicitly.** Freeze §12 literally says *"Graph of record: knowledge-graph service → Neo4j (topology) + Postgres (metadata, versions, evidence ledger)."* Read strictly, §12 implies Neo4j co-owns the record. Rev 2 **refines** this: the *authoritative* record (the thing recovery and correctness depend on) is the PostgreSQL revision log; Neo4j holds the *materialized topology for serving/queries* and is a rebuildable derivative. This refinement removes the dual-source-of-truth ambiguity, makes recovery unambiguous (replay from PostgreSQL), and still satisfies §12's data-ownership split (Neo4j = topology serving, Postgres = versions/metadata/authority). It does **not** change any frozen product/domain boundary; it sharpens the internal ownership within the knowledge-graph persistence layer. Freeze §12 wording will be proposed for a clarifying note under Freeze Control if the reviewer wishes (a documentation change, not a boundary change).

**Consequences.** Recovery, concurrency correctness, and the revision chain all key off PostgreSQL. Neo4j may lag transiently and is repaired/rebuilt from PostgreSQL. No client ever depends on Neo4j for durability.

### ADR-2 — Commit boundary = the PostgreSQL transaction; projection is asynchronous

**Decision.** A `GraphStore.write()` / transaction commit **succeeds the instant the PostgreSQL transaction commits.** At that point the write is durable and the `WriteReceipt` is returned. Updating the Neo4j projection is a **separate, asynchronous, best-effort** step whose failure **must not** change the write outcome. Projection lag is resolved later by read-repair/replay. There is **no** post-durability failure mode that makes a client believe a durable write failed.

**Status.** Accepted (supersedes rev 1's `ProjectionLagError` on the write path). Refined in rev 3: "after commit" work is not performed inside `write()` at all — see ADR-6.

**Consequences.** `write()` never raises after the PostgreSQL commit. The only write-time failure modes are *before* durability: validation errors, or a concurrency conflict (`PersistenceConflictError`) when the head moved (or a no-op whose head was revalidated and found stale — §7 step 3). `ProjectionLagError` is demoted to an *internal, catch-up/read-repair-time* signal, never surfaced from `write()`.

### ADR-5 — The authoritative read/write path uses PostgreSQL only; Neo4j is not required to open or commit a write

**Decision (rev 3, blocking issue 1).** Opening a write transaction and committing it depend on **PostgreSQL only**. The transaction snapshot is loaded from the authoritative `graph_revisions.graph_json` at the current `graph_head`, and `diff_graphs` compares against that PostgreSQL snapshot. **Neo4j is never on the write open/commit path.** Consequently, **writes remain fully available when Neo4j is unavailable** — projection availability cannot block durability. This makes the code consistent with ADR-1 (PostgreSQL authoritative, Neo4j a rebuildable projection); rev 2 incorrectly opened the transaction by reconstructing from Neo4j.

**Status.** Accepted. Reads also gain a PostgreSQL fallback so authoritative data is never unreadable when Neo4j is down (ADR-6 + §5.1).

### ADR-6 — Projection execution model: read-repair + explicit `catch_up_projection`; no hidden post-return worker

**Decision (rev 3, blocking issue 3).** Phase 2 defines a concrete, bounded projection execution model rather than implying unexplained asynchronous work:

- The PostgreSQL commit returns the `WriteReceipt`. **`GraphStore.write()` performs no work after it returns** and makes no such claim.
- The `graph_revisions` log is the **durable projection backlog** — every revision needed to bring Neo4j to any head is already durably recorded.
- Neo4j catches up through **(a) read-repair** triggered on the next `read` (§8) and **(b)** an explicit, callable internal operation **`catch_up_projection(tenant) -> applied_through_revision`** that replays pending revisions idempotently and monotonically. Both use the same idempotent apply + compare-and-set `:GraphHead` mechanism (§8), so they are safe to run concurrently.
- A **continuously running projection worker is explicitly deferred**. It is *not* part of Phase 2 unless separately added with a full lifecycle/retry/back-pressure design; the read-repair + explicit catch-up model is preferred to keep Phase 2 scope controlled.
- **Permitted variant — synchronous best-effort projection:** an implementation *may* attempt a projection apply **synchronously, inside `write()`, before returning**, provided (i) it is described as *synchronous best-effort* (never "asynchronous"), (ii) a projection failure never changes the durable write result, and (iii) the `WriteReceipt` is still returned after a failed projection attempt (the failure is swallowed/logged, and read-repair/catch-up resolves it later). No detached/background task is started.

**Status.** Accepted; the read-repair + explicit `catch_up_projection` model is the design baseline. Diagrams show projection only as read-repair/catch-up or as an explicit synchronous best-effort step — never as unexplained work occurring after the response returned.

### ADR-3 — `revision_number` is revision identity; `content_hash` is graph identity

**Decision.** The identity of a revision is `(tenant_id, revision_number)` — a strictly increasing per-tenant counter. `content_hash` identifies a **graph state** and is **not unique**: a legitimate rollback creates a *new* revision whose `content_hash` equals an earlier revision's. Therefore `content_hash` is a **non-unique index**, never a UNIQUE constraint.

**Status.** Accepted (supersedes rev 1's `UNIQUE(tenant_id, content_hash)`).

### ADR-4 — `GraphStore` persists graph state only; evidence persistence is a separate capability

**Decision.** `GraphStore.write(tenant, graph, *, principal)` receives no evidence objects, so it persists **only**: revisions, the head pointer, and the outbox. **It does not write an evidence ledger.** The `EvidenceLedgerRepository` is an **independent persistence capability** (used by ingestion/evidence workflows in later phases), not part of the `GraphStore` write path. This removes the rev-1 contract gap (the store had no evidence input yet claimed to persist an evidence ledger).

**Status.** Accepted (matches the reviewer's preferred option). Evidence *carried inside* `MemoryNode`/`MemoryEdge` (their `evidence` refs) is serialized as part of the graph snapshot in the revision row — it is preserved, but it is not separately shredded into an evidence-ledger table by `GraphStore`.

### ADR-7 — Bilingual content is preserved opaquely (Arabic + English readiness)

**Decision.** Phase 2 persistence conforms to platform **ADR-018 (Bilingual Enterprise Architecture)**. Authoritative `graph_json` and Neo4j `content_json` store UTF-8 domain payloads without language stripping. Arabic and English labels, aliases, and metadata that the domain model carries must round-trip with canonical `content_hash` equality. Phase 2 does **not** add dedicated multilingual schema columns; domain enrichment (`source_language`, translations, multilingual links) is mandatory in later knowledge/ingestion phases per ADR-018.

**Status.** Accepted (additive; aligns Phase 2 with ADR-018).

### ADR-6 refinement — Explicit ProjectionWorker (outbox + checkpoints)

**Decision (implementation approval 2026-07-24).** Phase 2 **includes** an explicit `ProjectionWorker` that consumes `graph.revision.committed` outbox rows, applies Neo4j projection via the same idempotent apply + `:GraphHead` CAS path as read-repair/`catch_up_projection`, and records `projection_checkpoints` for idempotency. The worker is **never** started by `GraphStore.write()` (ADR-6 / no hidden post-return work). It is invoked explicitly (`process_once` / operator or CI). Continuous daemon lifecycle remains optional and out of band.

**Status.** Accepted refinement of ADR-6 for Phase 2 completion scope.

---

## 1. Objectives

1. Make the memory graph **durable** by implementing the Phase 1 `GraphStore` port with **PostgreSQL as the authoritative revision log** and **Neo4j as the serving projection** (ADR-1; Freeze §12, §30). **The authoritative open/commit/read path uses PostgreSQL only; Neo4j is never required for a write, and reads fall back to PostgreSQL when Neo4j is down (ADR-5).**
2. Preserve every Phase 1 guarantee at scale: determinism (content-hash chain), one-writer-per-tenant, atomic read-modify-write, and the `WriteReceipt` contract — while upgrading concurrency from single-process to **cross-process** (compare-and-set head, incl. no-op head revalidation).
2b. Define a **concrete, bounded projection execution model** — read-repair + an explicit `catch_up_projection(tenant)` operation, with **no hidden post-return worker** (ADR-6).
3. Introduce the **transactional outbox** (Freeze §31) with a fully specified contract (§9): exactly one `graph.revision.committed` event per committed revision.
4. Establish the **shared-schema multi-tenancy** baseline (Freeze §17): every persisted datum tenant-scoped (D1).
5. Ship a **store-contract test suite** proving the persistent adapter satisfies the identical Phase 1 behavioural contract.
6. **Zero breaking API changes:** the `GraphStore` port is unchanged; the in-memory adapter stays the default for unit tests.

## 2. Scope

- `PostgresNeo4jGraphStore` implementing `GraphStore`/`GraphTransaction` (read, write, tenants, transaction, receipts). **Write open/commit and the read fallback use PostgreSQL only (ADR-5).**
- PostgreSQL schema + migrations: `tenants`, `graph_revisions` (incl. `graph_json` snapshot used to open transactions and to serve the read fallback), `graph_head`, `outbox`, `schema_migrations`. (`evidence_ledger` schema is defined but **owned by the evidence capability**, not the `GraphStore` write path — ADR-4.)
- Neo4j **serving** projection: labels/constraints/indexes, `:GraphHead` marker, idempotent diff apply, reconstruction — used for serving reads, never for write open/commit.
- Compare-and-set head for cross-process concurrency, including **first-revision** creation and **no-op head revalidation** (§7).
- **Projection execution model (ADR-6):** read-repair + explicit `catch_up_projection(tenant)`; **no** continuously running worker in Phase 2. Optional synchronous best-effort in-`write()` apply is permitted but not required.
- **Read availability:** Neo4j-preferred with **PostgreSQL fallback** (§5.1).
- Settings-driven `GraphStore` **factory** (DI seam).
- Custom migration runner meeting the strengthened requirements (§10).
- Contract, integration, concurrency, recovery, no-op, and migration tests; DB-backed CI job.
- Documentation + `PHASE2_COMPLETION.md`.

## 3. Non-scope

- Query/traversal service & HTTP APIs — Phase 3.
- Authorization / classification-clearance enforcement — Phase 3 (Phase 2 *stores* classification inside serialized nodes; it does not enforce).
- **Evidence ingestion workflow** that populates `evidence_ledger` — later phase; Phase 2 only defines the ledger schema + repository capability (ADR-4), it is not wired into `GraphStore.write`.
- Broker/event-bus wiring — Phase 4 (Phase 2 writes outbox rows only).
- Retrieval / Qdrant — Phase 5.
- Tenant isolation tiers (schema/db-per-tenant) — designed-for, deferred (Freeze §17).
- `tenant_id` on the frozen domain models (D1: single-tenant `MemoryGraph`).
- Any change to `emg-memory-graph`, `emg-platform-core` ports, or existing services.

## 4. Package layout

```
libs/python/emg-persistence/                 # new (deps: emg-platform-core, emg-memory-graph, neo4j, psycopg[binary], pydantic-settings)
  pyproject.toml
  src/emg_persistence/
    __init__.py
    config.py            # PersistenceSettings (pydantic-settings): DSNs, pool sizes
    factory.py           # build_graph_store(settings) -> GraphStore  (DI seam)
    errors.py            # PersistenceError, PersistenceConflictError; ProjectionLagError (internal only)
    postgres/
      pool.py            # psycopg connection pool
      revisions.py       # RevisionRepository (append-only log + compare-and-set head)
      outbox.py          # OutboxRepository (transactional outbox rows)
      evidence.py        # EvidenceLedgerRepository (INDEPENDENT capability; NOT used by GraphStore.write — ADR-4)
    neo4j/
      driver.py          # neo4j driver/session management
      projection.py      # Neo4jGraphProjection (apply diff idempotently, reconstruct, head marker)
      schema.py          # constraint/index definitions (applied via migrations)
    store.py             # PostgresNeo4jGraphStore + _PersistentTransaction
    migrations/
      postgres/          # V001__baseline.sql, ...           (transactional, checksummed)
      neo4j/             # M001__constraints.cypher, ...      (idempotent, checksummed)
    migrate.py           # migration runner (checksums, dirty/failed detection, history)
  tests/
    contract/            # runs the Phase-1 behavioural contract against this adapter
    integration/         # DB-backed (compose services / testcontainers)
    test_migrations.py  test_concurrency.py  test_recovery.py  test_noop_write.py
```

Auto-discovered by `install-libs.sh` and pytest (no tooling change), consistent with Phase 1.

## 5. Neo4j projection architecture (serving graph — NOT source of truth)

Neo4j is the **queryable topology projection** (ADR-1). It is derived from PostgreSQL and fully rebuildable.

- **Node:** `:MemoryNode {tenant_id, node_id, node_type, label, created_at, updated_at, source, confidence, content_json}`. `content_json` is the serialized `MemoryNode`, used for **canonical semantic reconstruction** (§6).
- **Edge:** `:MEMORY_EDGE {tenant_id, edge_id, edge_type, direction, confidence, valid_from, valid_until, content_json}`.
- **Head marker:** `:GraphHead {tenant_id, revision_number, content_hash}` — records which revision the projection currently reflects; drives monotonic read-repair (§8).
- **Constraints/indexes:** unique `(tenant_id, node_id)`; unique `(tenant_id, edge_id)`; index `(tenant_id, node_type)`; unique `(tenant_id)` on `:GraphHead`. (Neo4j **5 Community**, see §15.)
- **Apply** is diff-based and **idempotent**: `diff_graphs(new, current)` → batched, parameterized `UNWIND … MERGE/DELETE`, then compare-and-set `:GraphHead` from the expected prior revision to the new one (never regresses — §8).
- **Reconstruct** a tenant's `MemoryGraph`: fetch nodes+edges for `tenant_id`, deserialize `content_json`, build a `MemoryGraph` (which canonicalizes/sorts) → **same deterministic `content_hash`** as the authoritative revision (§6).

### 5.1 Read path and PostgreSQL fallback (rev 3, blocking issue 3)

`GraphStore.read(tenant)` **prefers the Neo4j serving projection** (fast topology reads, read-repair on lag — §8), but **never depends on Neo4j for availability**:

- **Projection current** (`:GraphHead == graph_head`) → reconstruct from Neo4j.
- **Projection lags** → read-repair (§8), then reconstruct from Neo4j.
- **Neo4j unavailable** → **authoritative PostgreSQL fallback:** load `graph_json` at the current `graph_head` from `graph_revisions` and deserialize to `MemoryGraph`. This is the exact snapshot writes use to open (§7 step 1), so the fallback returns the correct current graph.

Rationale (explicitly justifying the requirement): the authoritative data lives in PostgreSQL, so it must remain readable whenever PostgreSQL is up, regardless of the serving projection's health. The projection is an optimization for query/traversal (Phase 3), not a availability dependency for the authoritative graph. Reads are unavailable only if **PostgreSQL** is down (the true source of truth), never merely because Neo4j is down.

## 6. Reconstruction semantics (comment 6)

Persistence and reconstruction guarantee **canonical semantic reconstruction producing the same deterministic `content_hash`** — *not* byte-identical serialization. JSON encoding is not guaranteed byte-stable across libraries/versions, so correctness is defined by the domain's own canonical hash: a reconstructed `MemoryGraph` is correct iff `reconstructed.content_hash() == authoritative_revision.content_hash`. `emg-memory-graph` already canonicalizes (sorted nodes/edges, canonical `content_hash`), so reconstruction compares hashes, never raw bytes. Every occurrence of "byte-identical" from rev 1 is replaced by this definition.

## 7. Transaction flow (comments 2, 5, 7; rev-3 blocking issues 1, 2, 3)

`GraphStore.transaction()`/`write()` commit is a **single PostgreSQL transaction** (the durability boundary, ADR-2). **The open/snapshot and the commit depend on PostgreSQL only — never on Neo4j (ADR-5).** Neo4j is a serving projection that catches up out of band (ADR-6); a write is fully available when Neo4j is down.

1. **Open — from PostgreSQL, authoritative (blocking issue 1, ADR-5):**
   - `SELECT head_revision_number, head_content_hash FROM graph_head WHERE tenant_id = ?` → `(R0, H0)`, or *no row* → `R0 = 0`, `H0 = ∅` (tenant has no revision yet).
   - Load the authoritative head graph: `SELECT graph_json FROM graph_revisions WHERE tenant_id = ? AND revision_number = R0` → deserialize to `MemoryGraph G0` (or `EMPTY_GRAPH` when `R0 = 0`). **The snapshot comes from PostgreSQL `graph_json`, not from Neo4j.**
   - Yield the transaction carrying `(G0, R0, H0)`. **No Neo4j access occurs to open a transaction.**
2. **Body** — caller `stage(new_graph)` (pure; `MemoryGraph` immutable). `diff_graphs` (at commit) compares against the **PostgreSQL** snapshot `G0`.
3. **No-op short-circuit with head revalidation (comment 5 + blocking issue 2):** on commit, compute `H1 = new_graph.content_hash()`. If `H1 == H0` (staged graph equals the head captured at open), the write intends no change — but a concurrent writer may have advanced the head since open, so we **must revalidate the authoritative head before returning a receipt**. In one short PostgreSQL transaction:
   - `SELECT head_revision_number, head_content_hash FROM graph_head WHERE tenant_id = ? FOR SHARE` (or an equivalent `SELECT ... FOR UPDATE`) → `(R_now, H_now)`.
   - **If `(R_now, H_now) == (R0, H0)`** → the head is unchanged → return a no-op `WriteReceipt` for the current head (`content_hash = H0`, current counts). **No** revision, **no** `revision_number` bump, **no** outbox row, **no** event.
   - **If `(R_now, H_now) ≠ (R0, H0)`** → the head advanced under us → **`PersistenceConflictError`** (never return a receipt for a stale head). Caller retries (re-open sees the new head).
   This guarantees a no-op receipt is only ever returned for the *still-current* authoritative head.
4. **Commit (PostgreSQL, atomic) when `H1 ≠ H0`:** in one transaction —
   - Insert `graph_revisions (tenant_id, revision_number = R0+1, content_hash = H1, parent_hash = H0, principal_*, node_count, edge_count, graph_json, created_at)`.
   - **Compare-and-set head:** `UPDATE graph_head SET head_revision_number = R0+1, head_content_hash = H1 WHERE tenant_id = ? AND head_revision_number = R0`. For the **first revision** (no head row yet), use `INSERT INTO graph_head (...) VALUES (...) ON CONFLICT (tenant_id) DO NOTHING` (§ first-revision below).
   - Insert **exactly one** `outbox` row (`graph.revision.committed`, §9).
   - Commit.
   - **If the compare-and-set/first-insert affected 0 rows** → another writer advanced (or created) the head → `PersistenceConflictError` (before any durable change; caller retries).
5. **Durability = success (ADR-2):** once the PostgreSQL COMMIT returns, the write **has succeeded**; build and return the `WriteReceipt(content_hash = H1, counts, tenant, principal)`.
6. **Projection is NOT performed inside `write()` (blocking issue 3, ADR-6):** `write()` returns immediately after the PostgreSQL commit and **claims no further work**. The `graph_revisions` log *is* the durable projection backlog; Neo4j catches up later through (a) read-repair on the next `read` (§8) and/or (b) an explicit internal `catch_up_projection(tenant)` operation. There is **no** hidden post-return worker in Phase 2. (An optional *synchronous best-effort* apply is described in ADR-6 as the only permitted in-`write()` projection variant; it never changes the durable result and still returns the receipt on projection failure. The read-repair/explicit-catch-up model is preferred to keep scope controlled.)

**First-revision concurrency (comment 7).** Two writers may both see "no head" and try to create revision 1. Both attempt `INSERT INTO graph_head ... ON CONFLICT (tenant_id) DO NOTHING` inside their transaction; the unique PK on `tenant_id` means **exactly one INSERT succeeds** (affects 1 row) and commits revision 1; the other affects **0 rows** → `PersistenceConflictError` → retry (its retry now sees head = 1 and proceeds as an ordinary compare-and-set). The same compare-and-set predicate thus covers both the first revision (INSERT … ON CONFLICT) and all subsequent revisions (conditional UPDATE).

## 8. Concurrent read-repair safety (comment 8)

Multiple readers can simultaneously detect that `:GraphHead` (Neo4j) lags the PostgreSQL head. Coordination requirements:

- **Monotonic replay marker + compare-and-set on `:GraphHead`.** Each replay step advances the projection from an *expected* `revision_number` to `expected+1` using a Cypher compare-and-set: `MATCH (h:GraphHead {tenant_id:$t}) WHERE h.revision_number = $expected SET h.revision_number = $expected+1, h.content_hash = $next`. A step whose expected value no longer matches (another reader already advanced it) is a **no-op** — so concurrent repairers converge and never double-apply.
- **Idempotent apply.** Each revision's diff apply is idempotent (MERGE/DELETE keyed by node/edge id), so re-applying a revision is harmless.
- **`GraphHead` never regresses.** Advances are strictly `expected → expected+1` guarded by the compare-and-set; a lower revision can never overwrite a higher one.
- **Optional advisory lock.** For efficiency (avoid redundant work under high read concurrency), a PostgreSQL transaction-scoped **advisory lock keyed by `tenant_id`** may serialize repair for one tenant; correctness does not depend on it (the compare-and-set is the correctness mechanism), it only reduces wasted replays.

Guarantee: regardless of how many readers repair concurrently, the projection converges monotonically to the PostgreSQL head and `:GraphHead` never moves backwards.

## 9. Outbox contract (comment 9)

**Baseline: exactly ONE `graph.revision.committed` event per committed revision.** Node/edge-level events (`graph.node.*`, `graph.edge.*`) remain **Phase 4**.

Outbox row / event fields:

| Field | Meaning |
|---|---|
| `event_id` | UUID, unique per event (primary key). |
| `tenant_id` | Owning tenant. |
| `revision_number` | The committed revision's number. |
| `content_hash` | The committed graph's hash (`H1`). |
| `event_type` | `graph.revision.committed` (Freeze §13 namespace). |
| `schema_version` | Event-schema version integer (starts at `1`) for forward evolution. |
| `idempotency_key` | `f"{tenant_id}:{revision_number}"` — unique; the natural dedupe key for consumers. |
| `payload` | JSON: `{tenant_id, revision_number, content_hash, parent_hash, principal_id, principal_kind, node_count, edge_count, created_at}`. |
| `created_at`, `published_at` | Written-at; `published_at` NULL until a Phase 4 relay publishes. |

- **Ordering guarantee:** per tenant, events are totally ordered by `revision_number` (monotonic, gap-free — one event per revision). No global cross-tenant order is promised.
- **Written atomically** with the revision in the same PostgreSQL transaction (transactional outbox) — an event exists **iff** its revision committed.
- **Replay behaviour:** a relay (Phase 4) publishes unpublished rows in `revision_number` order and marks `published_at`; consumers dedupe on `idempotency_key`. Re-publishing is safe (at-least-once + idempotent consumers). No-op writes (§7 step 3) produce **no** event.

## 10. Migration runner requirements (comment 10)

The custom runner (`migrate.py`) **must** provide, and the design commits to, all of:

- **Migration history table** — `schema_migrations (version, name, checksum, applied_at, success)` in PostgreSQL; a `:SchemaMigration {version, checksum, applied_at}` marker set in Neo4j.
- **Immutable migration checksums** — each migration file's SHA-256 is recorded on first apply; on every run the runner re-hashes files and **fails if a previously-applied migration's checksum changed** (immutability enforcement).
- **Checksum verification** — startup verifies all applied migrations still match their recorded checksums before applying anything new.
- **Failed-migration detection** — a migration that errors is recorded with `success = false`; the runner refuses to proceed until resolved.
- **Dirty-migration detection** — if the process dies mid-migration, the in-progress version is marked dirty; the next run detects the dirty state and **halts** (no silent partial schema).
- **Transactional PostgreSQL migrations** — each PostgreSQL migration runs inside a single transaction (all-or-nothing); the history update is part of that transaction.
- **Idempotent Neo4j migrations** — Cypher migrations use `CREATE CONSTRAINT/INDEX IF NOT EXISTS` (Neo4j lacks transactional DDL), so re-running is safe; the `:SchemaMigration` marker records completion.

Migrations are **forward-only**; the baseline is `V001` (PostgreSQL tables) + `M001` (Neo4j constraints/indexes). CI runs the runner against ephemeral service containers before tests.

## 11. Schema design (comments 3, 4)

**PostgreSQL (shared-schema; `tenant_id` on every table):**

| Table | Identity / keys | Notes |
|---|---|---|
| `tenants` | PK `tenant_id` | registry; backs `tenants()` |
| `graph_revisions` | PK `(tenant_id, revision_number)`; **non-unique index** `(tenant_id, content_hash)` (ADR-3, comment 3) | append-only; `parent_hash`, `principal_id`, `principal_kind`, `node_count`, `edge_count`, `graph_json`, `created_at` |
| `graph_head` | PK `tenant_id` | `head_revision_number`, `head_content_hash`; compare-and-set anchor (§7) |
| `outbox` | PK `event_id`; UNIQUE `idempotency_key` | §9 fields |
| `schema_migrations` | PK `version` | §10 (checksum, applied_at, success) |
| `evidence_ledger` | PK `(tenant_id, seq)`; index `(tenant_id, evidence_id)` | **independent capability (ADR-4)** — append-only, hash-chained; **not written by `GraphStore.write`** |

`revision_number` is revision identity; `content_hash` is graph identity and **non-unique** (a rollback may re-create a prior `content_hash`).

**Neo4j:** labels/constraints/indexes per §5, created by migrations (§10).

*(Column lists are design specification, not DDL; runnable migrations are authored during implementation, after approval.)*

## 12. Migration strategy

- Forward-only, versioned, checksummed migrations run by the §10 runner. Baseline `V001` + `M001`.
- `graph_revisions` uses a **non-unique** `(tenant_id, content_hash)` index (comment 3) — never UNIQUE — so rollback revisions that reproduce a prior hash are legal.
- CI applies migrations to ephemeral PostgreSQL + Neo4j before the DB-backed tests; environment promotion is gated on a clean, checksum-verified migration state.

## 13. Rollback strategy

- **Code:** Phase 2 is additive (new package + factory). The in-memory adapter stays the default until a service opts in, so reverting the Phase 2 commits restores exact Phase 1 state.
- **State rollback = a new forward revision (comment 3).** Because `graph_revisions` is append-only and `content_hash` is non-unique, "rolling back" to an earlier graph is expressed as **appending a new revision** (`revision_number = head+1`) whose `content_hash` equals the target earlier revision's hash. Nothing is deleted; the never-overwrite invariant (Freeze §9) holds; the outbox emits one `graph.revision.committed` for the rollback revision like any other.
- **Schema:** prefer roll-forward; emergency `*_down.sql` kept but discouraged.
- **Projection:** Neo4j is rebuildable from the PostgreSQL revision log (`rebuild_projection(tenant)`), so a corrupt projection is recoverable with zero data loss (authority is PostgreSQL, ADR-1).

## 14. Testing strategy

- **Contract parity (headline):** the Phase 1 behavioural suite (read/write, tenant isolation, determinism, transaction commit/rollback/lifecycle, receipts) parameterized over `InMemoryGraphStore` **and** `PostgresNeo4jGraphStore`.
- **No-op write tests (comment 5):** writing a graph equal to the current head creates **no** revision, does **not** bump `revision_number`, writes **no** outbox row, and returns a `WriteReceipt` for the current head.
- **No-op stale-head race (blocking issue 2, adversarial):** open a transaction at head `(R0,H0)`; from another connection commit a *different* graph (advancing the head); then commit the first transaction with a graph whose hash equals `H0` → it **must** raise `PersistenceConflictError` and **must not** return a receipt for the now-stale head. A companion test asserts that when the head is unchanged, the no-op returns the current-head receipt.
- **Write availability without Neo4j (blocking issue 1):** with Neo4j stopped/unreachable, `write()` still opens (PostgreSQL snapshot), commits, and returns a valid `WriteReceipt`.
- **Read fallback without Neo4j (blocking issue 3):** with Neo4j stopped, `read()` returns the correct current graph from the PostgreSQL fallback (`content_hash == head`).
- **Explicit catch-up (ADR-6):** after writes with Neo4j down, bring Neo4j up and call `catch_up_projection(tenant)` → projection reaches the PostgreSQL head; idempotent on re-invocation; `:GraphHead` monotonic.
- **Concurrency (comments 7, 8):**
  - *First-revision race:* two writers create revision 1 concurrently → exactly one succeeds, the other gets `PersistenceConflictError` (INSERT … ON CONFLICT).
  - *Subsequent race:* concurrent compare-and-set on the same head → one wins, one conflicts; no lost update.
  - *Concurrent read-repair/catch-up:* many readers/catch-ups on a lagging projection simultaneously → `:GraphHead` advances monotonically, never regresses, no double-apply.
- **`content_hash` identity, not uniqueness (comment 3):** a rollback revision reproducing a prior `content_hash` is accepted and stored (would violate a UNIQUE constraint — proves it is only an index).
- **Post-commit projection failure (comment 2, ADR-6):** simulate Neo4j apply failure during catch-up *after* PostgreSQL commit → the earlier `write()` still returned a successful `WriteReceipt`; a later `read` read-repairs (or PG-falls-back) to the correct graph.
- **Reconstruction (comment 6):** persisted-then-reconstructed graph has an equal `content_hash` to the authoritative revision (semantic, not byte, equality).
- **Migration tests (comment 10):** baseline apply; idempotent re-apply; checksum-change detection; dirty-state halt.
- **Determinism / recovery / evidence-repository (ADR-4)** unit tests.
- Coverage target **> 95%** on the new package; DB-backed tests gated to the integration CI job.

## 15. CI impact

- **New `persistence` CI job** using GitHub Actions `services:` — **PostgreSQL 16** and **Neo4j 5 Community**. Runs the migration runner, then contract/integration/concurrency/recovery/migration tests.
- **Neo4j Community is the default and is sufficient for Phase 2.** Phase 2 uses only core graph features: labels, relationships, properties, and `CREATE CONSTRAINT/INDEX IF NOT EXISTS` — all present in Community Edition. Phase 2 does **not** require any Enterprise-only capability (multi-database / `CREATE DATABASE` per tenant, RBAC, property-existence/ key constraints, fine-grained security, hot backups, clustering). Those become relevant only for the **tenant isolation tiers** (database-per-tenant) deferred to v1.x/2.0 (Freeze §17); Enterprise will be justified there, not here. **Decision: use Community Edition for Phase 2** (updates rev 1, which pinned `neo4j:5-enterprise`; `docker-compose.yml` should be revisited during implementation to align local dev with Community for parity — flagged, not changed here).
- The existing **`quality`** job runs the new package's non-DB unit tests; **`typecheck`** runs `mypy --strict` on `emg-persistence` — both automatic (glob-based). `make lint` unchanged.
- Added runtime (~30–60s container startup) mitigated by health-gated waits + driver-wheel caching.

## 16. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Projection lag after commit misread as write failure | Med→**Low** | ADR-2: commit = success; projection async; `write()` never raises post-commit. |
| Cross-process lost update (incl. first revision) | Med | Compare-and-set head + INSERT…ON CONFLICT (§7); concurrency tests (§14). |
| `GraphHead` regression under concurrent repair | Med | Monotonic compare-and-set advance; idempotent apply (§8). |
| Rollback blocked by hash uniqueness | Med→**resolved** | Non-unique `content_hash` index (ADR-3). |
| Evidence contract ambiguity | Med→**resolved** | ADR-4: `GraphStore` persists no evidence ledger; evidence is a separate capability. |
| Migration drift / partial apply | Low | Checksums + dirty/failed detection + transactional PG migrations (§10). |
| Reconstruction correctness vs serialization drift | Low | Canonical `content_hash` equality, not byte equality (§6). |
| Neo4j licensing in CI | Low | Community Edition suffices for Phase 2 (§15). |
| Scope creep into query/authz | Low | Hard non-scope (§3); stop-and-report. |

## 17. Sequence diagrams

**Write / commit — PostgreSQL-only open + commit; no post-return work (blocking issues 1, 2, 3):**

```mermaid
sequenceDiagram
    participant Svc as Caller (service)
    participant Store as PostgresNeo4jGraphStore
    participant PG as PostgreSQL (authoritative)
    Note over Store,PG: Neo4j is NOT on the write open/commit path (ADR-5)
    Svc->>Store: transaction(tenant, principal)
    Store->>PG: SELECT graph_head → (R0,H0);\nSELECT graph_revisions.graph_json @ R0 → G0
    PG-->>Store: snapshot G0, head (R0,H0)
    Store-->>Svc: txn (PostgreSQL snapshot G0)
    Svc->>Store: stage(G1)
    Note over Store: clean exit → commit; H1 = G1.content_hash()
    alt H1 == H0 (no-op, revalidate head — issue 2)
        Store->>PG: BEGIN; SELECT graph_head FOR SHARE → (R_now,H_now); COMMIT
        alt (R_now,H_now) == (R0,H0)
            Store-->>Svc: WriteReceipt(H0)  %% no revision/outbox/event
        else head advanced under us
            Store-->>Svc: PersistenceConflictError (never a stale-head receipt)
        end
    else H1 != H0
        Store->>PG: BEGIN; INSERT revision(R0+1,H1,parent=H0);\ncompare-and-set head (R0->R0+1)\n[first: INSERT head ON CONFLICT DO NOTHING];\nINSERT outbox(graph.revision.committed); COMMIT
        alt head matched / first insert won
            PG-->>Store: COMMIT ok  %% DURABLE = SUCCESS (ADR-2)
            Store-->>Svc: WriteReceipt(H1)
            Note over Store: write() returns and does NO further work (ADR-6).\nNeo4j catches up via read-repair / catch_up_projection(tenant).
        else head moved / conflict (incl. first-rev race)
            PG-->>Store: 0 rows → ROLLBACK (no durable change)
            Store-->>Svc: PersistenceConflictError (retry)
        end
    end
```

**Read — prefer projection, read-repair on lag, PostgreSQL fallback if Neo4j down (comment 8 + blocking issue 3):**

```mermaid
sequenceDiagram
    participant Svc as Caller
    participant Store as GraphStore
    participant NEO as Neo4j (projection)
    participant PG as PostgreSQL (authoritative)
    Svc->>Store: read(tenant)
    Store->>PG: get graph_head (R_pg, H_pg)
    alt Neo4j available
        Store->>NEO: get :GraphHead (R_neo)
        alt R_neo == R_pg
            Store->>NEO: fetch nodes+edges; reconstruct
        else R_neo < R_pg (lag → read-repair)
            loop replay R_neo+1 .. R_pg
                Store->>PG: fetch revision k
                Store->>NEO: apply diff (idempotent);\ncompare-and-set GraphHead (k-1 -> k)
                note over NEO: CAS no-op if another reader already advanced
            end
            Store->>NEO: fetch + reconstruct
        end
    else Neo4j unavailable (fallback — ADR-5/§5.1)
        Store->>PG: SELECT graph_revisions.graph_json @ R_pg; deserialize
    end
    Store-->>Svc: MemoryGraph (content_hash == H_pg)  %% available whenever PostgreSQL is up
```

## 18. Component diagram

```mermaid
flowchart TB
    subgraph Services["Services (Phase 3+)"]
      KG[knowledge-graph service]
    end
    KG -->|GraphStore port| FAC[GraphStore factory]
    FAC -->|dev/tests| MEM[InMemoryGraphStore (Phase 1)]
    FAC -->|prod| STORE[PostgresNeo4jGraphStore]
    subgraph emg-persistence
      STORE --> REV[RevisionRepository]
      STORE --> OBX[OutboxRepository]
      STORE --> PRJ[Neo4jGraphProjection\napply + read-repair + catch_up_projection]
      EVL[EvidenceLedgerRepository\n(independent capability - ADR-4)]
    end
    REV --> PG[(PostgreSQL - AUTHORITATIVE\nopen+commit+read-fallback)]
    OBX --> PG
    EVL -. used by ingestion/evidence (later) .-> PG
    STORE ==>|write open/commit + read fallback\nNeo4j NOT required (ADR-5)| REV
    PRJ -->|serving reads (preferred) + read-repair| NEO[(Neo4j - projection/serving)]
    PG -->|revisions = durable backlog\nread-repair / catch_up_projection| PRJ
    OBX -. Phase 4 relay .-> BRK[[Broker]]
    STORE -. depends on .-> CORE[emg-platform-core ports]
    STORE -. serializes .-> MG[emg-memory-graph models]
```

## 19. Data flow diagram

```mermaid
flowchart LR
    IN[Knowledge objects] --> BLD[MemoryGraphBuilder]
    BLD --> G[Immutable single-tenant MemoryGraph]
    OPEN[transaction open:\nload snapshot G0 from PostgreSQL graph_json @ head] --> G
    G --> W[GraphStore.write tenant,graph,principal]
    W --> H1{H1 == head H0?}
    H1 -- yes --> REVAL{head still R0,H0?}
    REVAL -- yes --> RC0[WriteReceipt H0\nno revision / no outbox / no event]
    REVAL -- no --> CONF[PersistenceConflictError]
    H1 -- no --> DIFF[diff_graphs vs PostgreSQL snapshot G0]
    DIFF --> REVROW[graph_revisions row R0+1\n+ compare-and-set head]
    DIFF --> OBXROW[outbox: 1x graph.revision.committed]
    REVROW --> PGDB[(PostgreSQL AUTHORITATIVE)]
    OBXROW --> PGDB
    PGDB --> OK[COMMIT = success -> WriteReceipt H1\nwrite() returns, no further work - ADR-6]
    PGDB -->|revisions = durable backlog| CATCH[read-repair / catch_up_projection]
    CATCH --> NEODB[(Neo4j projection\nserving reads; PostgreSQL fallback if down)]
    OBXROW -. Phase 4 .-> EVENTS[[graph.revision.committed events]]
```

## 20. API contracts (comment 2)

- **Public port API unchanged.** No new methods on `GraphStore`/`GraphTransaction`; `WriteReceipt` unchanged.
- **Open/snapshot source (ADR-5):** transaction open reads `graph_head` + `graph_revisions.graph_json` from **PostgreSQL only**; `diff_graphs` compares the staged graph against that PostgreSQL snapshot. Neo4j is not touched to open or commit a write.
- **`write()` outcome semantics (ADR-2):** returns a `WriteReceipt` on success; success is defined by the PostgreSQL commit (or a **head-revalidated** no-op — §7 step 3). The **only** write-time exceptions are *pre-durability*: `pydantic.ValidationError` (bad input) and `PersistenceConflictError` (head moved / first-revision race / **no-op whose head was revalidated stale**). **`write()` never raises after durability** and, per ADR-6, **performs no work after returning**; projection problems are never surfaced to the caller.
- **`read()` semantics (ADR-5, §5.1):** Neo4j-preferred with read-repair; **PostgreSQL fallback** when Neo4j is unavailable. Reads are available whenever PostgreSQL is up.
- **Projection operations (ADR-6, internal):** `catch_up_projection(tenant) -> applied_through_revision` (explicit, idempotent, monotonic) and `rebuild_projection(tenant)`. No public port change; these are adapter-internal maintenance operations. `ProjectionLagError` is **internal only** (catch-up/read-repair), never surfaced from `write()`/`read()`.
- **New additive surface:** `build_graph_store(settings)`, `PersistenceSettings`, and typed errors `PersistenceError` / `PersistenceConflictError` (both from `emg_errors.EMGError`).
- **Outbox event contract** as fully specified in §9.
- **Internal contracts:** `RevisionRepository`, `OutboxRepository`, `Neo4jGraphProjection`, and the independent `EvidenceLedgerRepository` (ADR-4) — documented, not public.

## 21. Performance considerations

- **Write path is PostgreSQL-only (ADR-5)** — open loads `graph_json` at the head (O(N+E) deserialize) + `graph_head` (O(1)); commit is one PostgreSQL transaction. **Neo4j is not on the write path**, so commit latency and write availability never depend on the projection.
- **Diff-based projection** — O(changed), one batched `UNWIND` round trip during read-repair/catch-up (off the write path).
- **Indexing** — composite `(tenant_id, node_id)`/`(tenant_id, node_type)`; non-unique `(tenant_id, content_hash)`; `graph_head` PK for O(1) head + compare-and-set.
- **No hidden post-return work (ADR-6)** — `write()` cost ends at the PostgreSQL commit; projection cost is incurred by the next `read`'s read-repair or an explicit `catch_up_projection`.
- **Read cost** — Neo4j-served O(N+E) reconstruction on the hot path; PostgreSQL fallback is a single `graph_json` fetch + deserialize (O(N+E)). Phase 3 query service reads targeted subgraphs.
- **Snapshot storage trade-off** — `graph_json` at each revision makes both write-open and read-fallback a single PostgreSQL fetch (correctness/availability over space). (A future optimization may store diffs + periodic snapshots; out of Phase 2 scope.)
- **Connection pooling** — psycopg + neo4j driver pools; per-op sessions.

## 22. Failure scenarios (comment 2)

| Scenario | Behaviour |
|---|---|
| **Neo4j unavailable during a write** | Write is unaffected — open/commit use PostgreSQL only (ADR-5). Write succeeds; projection catches up later. |
| **Neo4j unavailable during a read** | Read falls back to the PostgreSQL `graph_json` at the current head (§5.1) — authoritative data stays readable. |
| Neo4j apply/catch-up fails after a commit | Write already **succeeded** (receipt returned; `write()` did no post-return work — ADR-6). `graph_revisions` is the durable backlog; read-repair / `catch_up_projection` resolves it. Client never sees a failure. |
| Crash immediately after PostgreSQL commit | Revision durable; nothing else was pending inside `write()` (ADR-6). Next read read-repairs (or PG-fallback). |
| No-op write, head unchanged (`H1 == H0`, revalidated) | No revision, no outbox, no event; success receipt for the current head (§7 step 3). |
| **No-op write, head advanced concurrently** | Revalidation detects `(R_now,H_now) ≠ (R0,H0)` → `PersistenceConflictError`; **no stale-head receipt** (blocking issue 2). |
| Concurrent writers, same tenant (incl. first revision) | Compare-and-set / INSERT…ON CONFLICT → exactly one commits; others `PersistenceConflictError` (pre-durability) → retry. |
| Concurrent read-repair / catch-up | Monotonic CAS on `:GraphHead`; idempotent apply; never regresses (§8). |
| PostgreSQL unavailable | Write fails atomically **before** durability; read is unavailable (true source of truth is down). Caller retries. No partial state. |
| Rollback to a prior graph | New forward revision with a repeated `content_hash` (legal — non-unique); one outbox event. |
| Migration failure / dirty state | Runner halts; `success=false`/dirty recorded; no partial schema (§10). |
| Projection corruption | `rebuild_projection(tenant)` from PostgreSQL (authority). |

## 23. Security considerations

- **Secrets** via env/vault only; `.env` for local dev (gitignored). **Least-privilege** DB roles.
- **Injection-safe** — all SQL and Cypher parameterized; graph content flows through parameters, never string interpolation.
- **Tenant isolation** enforced by a mandatory `tenant_id` predicate on every query (defense-in-depth ahead of the Phase 3 PDP).
- **Evidence tamper-evidence** — the independent `evidence_ledger` (ADR-4) is hash-chained when populated by the evidence capability; `GraphStore` itself writes no evidence.
- **TLS** to both datastores; **no PII in logs**; classification stored now, enforced in Phase 3.
- **Supply chain** — new drivers (`neo4j`, `psycopg`) pinned + `pip-audit`-scanned.

## 24. Multi-tenancy implementation (D1)

- **`MemoryGraph` is single-tenant** (D1); tenant scoping lives entirely at the `GraphStore`/storage boundary. Every persisted row (PostgreSQL) and node/edge (Neo4j) carries `tenant_id`; every store call and repository method takes a `TenantId`; every query filters by it; composite indexes make tenant-scoped access efficient.
- **Cross-tenant isolation is a P0 test category** — no read/write may cross tenants.
- **Isolation tiers** (schema-per-tenant PostgreSQL, database-per-tenant Neo4j) are enabled by the repository seam but **deferred** (Freeze §17; would be where Enterprise Neo4j is justified, §15).

## 25. How Phase 2 preserves the Product Architecture Freeze

| Freeze section | Phase 2 conformance |
|---|---|
| §9 Domain model (immutable, no I/O, never-overwrite) | `emg-memory-graph` untouched; persistence isolated in `emg-persistence`; single-tenant model (D1); rollback = new append-only revision (never destructive). |
| §11 One writer per store; audit/event on mutation | Compare-and-set head = single logical writer per tenant; every committed revision emits exactly one outbox event (§9). |
| §12 Data ownership | **Refined (ADR-1):** PostgreSQL authoritative (versions/metadata/authority); Neo4j = topology serving projection, rebuildable. Explicit refinement, not silent reinterpretation. |
| §13 Event taxonomy | Outbox uses `graph.revision.committed`; node/edge events deferred to Phase 4. |
| §17 Multi-tenancy | Shared-schema baseline (D1); isolation tiers deferred. |
| §30 Database strategy | PostgreSQL + Neo4j exactly (Qdrant/Redis later). |
| §31 Event architecture | Transactional outbox now; broker Phase 4. |
| §32 Memory-graph architecture | `GraphStore` port + Neo4j serving adapter + in-memory adapter — the frozen §32 progression, with PostgreSQL as the durability authority. |

**No frozen product/domain boundary is altered.** The one **explicit refinement** (ADR-1: PostgreSQL authoritative, Neo4j projection) sharpens §12's internal ownership and is documented as a refinement, not an interpretation.

---

## Architecture Decision Log

| Review Item | Resolution | Document Section(s) Updated |
|---|---|---|
| 1 — Source-of-truth contradiction | **ADR-1**: PostgreSQL authoritative revision/recovery store; Neo4j = queryable projection. Declared a **deliberate refinement** of Freeze §12 (not an interpretation). Neo4j never called source of truth. | §0 ADR-1, §1, §5, §11, §17–19, §25 |
| 2 — Post-commit failure semantics | **ADR-2**: PostgreSQL commit == successful write; `WriteReceipt` returned; projection is async/best-effort; `ProjectionLagError` demoted to internal read-repair only; `write()` never raises post-durability. | §0 ADR-2, §7, §17 (seq), §20 (API), §22 (failures) |
| 3 — Remove `UNIQUE(tenant_id, content_hash)` | **ADR-3**: `revision_number` = revision identity; `content_hash` = graph identity → **non-unique index**. Rollback may repeat a hash. | §0 ADR-3, §11 (schema), §12 (migration), §13 (rollback), §14 (testing) |
| 4 — Evidence-ledger contract gap | **ADR-4**: `GraphStore` persists revisions + head + outbox only; `EvidenceLedgerRepository` is an independent capability, **not** on the `write()` path (which receives no evidence). | §0 ADR-4, §2–4, §11, §18, §20, §23 |
| 5 — No-op write semantics | Defined: if `H1 == H0` → no revision, no `revision_number` bump, no outbox, no event; `WriteReceipt` for current head **is** returned; success. | §7 (step 3), §14, §17 (seq), §19, §22 |
| 6 — "byte-identical reconstruction" | Replaced everywhere with **"canonical semantic reconstruction producing the same deterministic `content_hash`."** | §5, §6 (new), §14, §21 |
| 7 — First-revision concurrency | `INSERT INTO graph_head … ON CONFLICT (tenant_id) DO NOTHING`; exactly one writer wins, other gets `PersistenceConflictError`; added to test plan. | §7 (first-revision), §14 (concurrency), §22 |
| 8 — Concurrent read-repair safety | Monotonic compare-and-set on `:GraphHead` + idempotent apply (+ optional advisory lock); `GraphHead` never regresses. | §8 (new), §17 (seq), §22 |
| 9 — Outbox contract | Fully specified: `event_id`, `tenant_id`, `revision_number`, `content_hash`, `event_type`, `schema_version`, `idempotency_key`, ordering, payload, replay. Baseline = 1 `graph.revision.committed`/revision; node/edge events Phase 4. | §9 (new), §11 (schema), §20 |
| 10 — Migration runner requirements | Documented guarantees: history table, immutable checksums, checksum verification, failed + dirty detection, transactional PG, idempotent Neo4j. | §10 (new), §11, §12 |
| 11 — Synchronize all sections | All diagrams, schema, transaction flow, API, testing, rollback, failures, CI, Freeze mapping updated for the above; no remaining contradictions. | entire document |
| DB CI / Neo4j edition | DB-backed CI accepted; **Neo4j Community** chosen for Phase 2 with an explicit justification that no Enterprise-only feature is used (Enterprise deferred to isolation tiers). | §15 |
| D1 / D2 / D3 (approved) | Tenant scoping at storage boundary + single-tenant `MemoryGraph`; PostgreSQL log + Neo4j projection; new `libs/python/emg-persistence`. | header, §4, §24 |

### Decision-log addendum — rev 3 blocking issues

| Blocking issue | Resolution | Document Section(s) Updated |
|---|---|---|
| 1 — Neo4j on the authoritative write/open path | **ADR-5**: transaction open reads `graph_head` + `graph_revisions.graph_json` from **PostgreSQL**; `diff_graphs` compares against the PostgreSQL snapshot; **Neo4j is not required to open or commit**; writes remain available when Neo4j is down. | §0 ADR-5, §1, §2, §7 (step 1–2), §17 (write seq), §18–19 (diagrams), §20 (API), §21 (perf), §22 (failures), §14 (tests) |
| 2 — No-op concurrency race | No-op path **revalidates the authoritative head** (`SELECT graph_head FOR SHARE`): returns the no-op receipt only if `(R_now,H_now) == (R0,H0)`, else raises `PersistenceConflictError`. Never returns a stale-head receipt. Adversarial test added. | §7 (step 3), §17 (write seq), §19, §20, §22, §14 (adversarial no-op race) |
| 3 — Undefined projection execution model | **ADR-6**: PostgreSQL commit returns the receipt; `write()` does **no** post-return work; `graph_revisions` is the durable backlog; Neo4j catches up via **read-repair** + explicit **`catch_up_projection(tenant)`**; continuous worker deferred; synchronous best-effort variant permitted with guarantees. **Read gains a PostgreSQL fallback** (§5.1) so authoritative data is readable when Neo4j is down. Diagrams no longer show unexplained post-return work. | §0 ADR-2 (refined) + ADR-6, §1 (obj 2b), §2, §5.1 (new), §7 (step 6), §17 (both seq), §18–19, §20, §21, §22, §14 |

## Summary of architecture changes (rev 1 → rev 2, then rev 2 → rev 3)

1. **Single source of truth fixed (ADR-1):** PostgreSQL is authoritative; Neo4j is a rebuildable serving projection. "Graph of record" wording removed from Neo4j; declared an explicit refinement of Freeze §12.
2. **Commit semantics fixed (ADR-2):** durability (PostgreSQL commit) *is* success; `WriteReceipt` returned; projection is asynchronous/best-effort; `write()` cannot fail after durability; `ProjectionLagError` is internal-only.
3. **Revision vs graph identity fixed (ADR-3):** `content_hash` is a non-unique index; `revision_number` is identity; rollback can repeat a hash.
4. **Evidence contract fixed (ADR-4):** `GraphStore` writes revisions/head/outbox only; the evidence ledger is a separate capability not on the write path.
5. **No-op writes defined (§7):** equal-hash writes create nothing and return a success receipt for the current head.
6. **Reconstruction redefined (§6):** canonical `content_hash` equality, not byte-identical serialization.
7. **First-revision concurrency defined (§7):** `INSERT … ON CONFLICT` compare-and-set; one winner, others conflict.
8. **Read-repair coordination defined (§8):** monotonic compare-and-set on `:GraphHead`; never regresses; idempotent; optional advisory lock.
9. **Outbox contract fully specified (§9):** all fields, ordering, idempotency, replay; one `graph.revision.committed` per revision.
10. **Migration runner hardened (§10):** checksums, dirty/failed detection, transactional PG, idempotent Neo4j, history table.
11. **All sections synchronized (§11 comment):** diagrams, schema, flow, API, testing, rollback, failures, CI, Freeze mapping — internally consistent.
12. **Neo4j Community Edition selected for Phase 2 (§15)** with explicit justification; Enterprise deferred to isolation tiers.

**Rev 2 → rev 3 (three blocking issues):**

13. **PostgreSQL-only write path (ADR-5):** transaction open loads the snapshot from `graph_revisions.graph_json` at `graph_head`; `diff_graphs` compares against it; Neo4j removed from write open/commit. Writes are available when Neo4j is down. (rev 2 wrongly opened by reconstructing from Neo4j.)
14. **No-op head revalidation (blocking issue 2):** the no-op path re-checks the authoritative head under lock and raises `PersistenceConflictError` if it advanced; never returns a stale-head receipt. Adversarial test added.
15. **Concrete projection execution model (ADR-6):** `write()` performs no post-return work; `graph_revisions` is the durable backlog; catch-up via read-repair + explicit `catch_up_projection(tenant)`; continuous worker deferred; synchronous best-effort variant permitted with strict guarantees. Diagrams updated to remove unexplained post-return work.
16. **PostgreSQL read fallback (§5.1):** `read()` prefers Neo4j but falls back to the authoritative `graph_json` when Neo4j is down, with explicit justification that authoritative data must not become unreadable because the serving projection is unavailable.
17. **All dependent sections synchronized (blocking issue "update"):** objectives, scope, transaction flow, both sequence diagrams, component + data-flow diagrams, API contracts, failure scenarios, testing, performance, decision log, and revision summary — no internal contradictions remain.

**No implementation code was written; no repository source files were modified; no commits were created. Awaiting architecture approval before producing `PHASE2_PLAN.md` or beginning implementation.**
