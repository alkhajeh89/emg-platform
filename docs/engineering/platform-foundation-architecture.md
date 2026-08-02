# Platform Foundation Architecture (Phase 1)

**Package:** `libs/python/emg-platform-core`
**Frozen basis:** `EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9, §11, §12, §32.
**Status:** implemented in Phase 1 (Platform Foundation).

## Purpose

`emg-platform-core` is the **storage-independence seam** on which every future
EMG service is built. It contains no I/O and no ML (Freeze §9); it defines the
*contracts* through which services reach durable storage, a deterministic
in-memory implementation for tests and local development, and the cross-cutting
identity value types the frozen architecture requires on every datum.

It is intentionally small. Phase 1 delivers the *shape* of persistence, not
persistence itself — the Neo4j and Postgres adapters arrive in Phase 2 behind the
same ports (Freeze §32).

## Hexagonal design (ports & adapters)

```
        services (Phase 2+: knowledge-graph, retrieval, …)
                     depend on the PORT, never a database
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │   GraphStore (Protocol)   │   ports/graph_store.py
                    │   GraphTransaction        │   (Freeze §11, §32)
                    └─────────────┬─────────────┘
                    implemented by │
             ┌──────────────────────────────────────┐
             ▼                                        ▼
   InMemoryGraphStore  (Phase 1)          Neo4j / Postgres adapters (Phase 2)
   adapters/in_memory.py                  adapters/… (durability)
             │                                        │
             ▼                                        ▼
        emg-memory-graph  (the deterministic, immutable domain core)
```

Services depend on the `GraphStore` **interface**; the concrete store is injected
(dependency injection). This keeps the deterministic memory-graph core free of
storage concerns and makes in-memory / Neo4j / Postgres fully swappable without
touching domain logic — the "one writer per store … storage-independent"
boundary of Freeze §11.

## Components

### Ports (`emg_platform_core.ports`) — Freeze §11, §32

- **`GraphStore`** — `read(tenant)`, `write(tenant, graph, *, principal)`,
  `tenants()`, `transaction(tenant, principal)`. Expressed purely in domain
  terms (a tenant, a principal, an immutable `MemoryGraph`) — no database
  concepts leak through. `runtime_checkable`, so conformance is testable.
- **`GraphTransaction`** — an atomic read-modify-write unit of work:
  `read()` the current snapshot, `stage(graph)` a replacement, commit on clean
  context exit (rollback on exception). Staged snapshots (not in-place mutation)
  preserve `MemoryGraph` immutability (Freeze §9/§32). After a successful commit,
  `txn.receipt` exposes the `WriteReceipt`; accessing it before commit or after a
  rollback raises `TransactionStateError`. Once the context has closed
  (committed *or* aborted), `read()`/`stage()` also raise `TransactionStateError`.
- **`WriteReceipt`** — an immutable record of a persisted write (deterministic
  64-char `content_hash`, node/edge counts, tenant, principal). The seed of the
  audit spine (Freeze §11); later phases emit an audit record from it. Identical
  across adapters, since it contains no storage-specific detail.

### Identity (`emg_platform_core.identity`) — Freeze §9, §12

- **`TenantId`** — the multi-tenancy spine. The frozen model requires *"every
  datum carries `tenant_id`"* (§12). Wrapping the raw string in a validated value
  type makes tenant scoping explicit and type-checkable at every boundary — a
  read or write can never silently omit its tenant.
- **`PrincipalRef`** + `PrincipalKind` — *"principal provenance on every
  mutation — who/what asserted it"* (§9). A stable, auditable *reference* (not an
  identity record — that belongs to the identity service, §10/§11), carried on
  every write.
- `SYSTEM_TENANT` / `SYSTEM_PRINCIPAL` — explicit well-known values so "no
  tenant" / "system action" is never an empty or implicit value.

### Adapters (`emg_platform_core.adapters`) — Freeze §32

- **`InMemoryGraphStore`** — deterministic, tenant-scoped, in-process. A
  transaction holds the store's reentrant lock for its **entire** unit of work
  (snapshot → body → commit/abort), making transactions strictly serialisable
  with each other and with every direct `read`/`write`/`tenants` call. This
  eliminates lost updates (a transaction can never read a stale snapshot then
  overwrite a newer committed one) and prevents a direct write landing between a
  transaction's snapshot and its commit. Test/dev only; durability is Phase 2.
  Finer-grained concurrency (e.g. optimistic version checks) is a
  persistence-adapter concern, not a foundation concern.

## Deferred to Phase 2 (Persistence Binding)

- Neo4j adapter (graph of record) and Postgres adapter (metadata, versions,
  evidence ledger, transactional outbox) — Freeze §12, §30, §31.
- Threading `tenant_id` / `principal` through the persisted domain models
  (the additive retrofit named in Freeze §9), shipped with a real migration.
- Schema migrations.

> **Reconciliation note — 2026-08-03.** This document is a Phase 1 record and
> its deferral list above is preserved as written. Phase 2 has since been
> delivered, and it resolved the first bullet differently: **PostgreSQL is the
> authoritative record and Neo4j is a rebuildable serving projection** (ADR-1 /
> ADR-5, `PHASE2_ARCHITECTURE.md:26`) — not "Neo4j as graph of record" — and it
> shipped one adapter, `PostgresNeo4jGraphStore`, rather than two. Schema
> migrations V001–V006 exist. Nothing in `emg-platform-core` changed as a
> result; the port seam described here held. For the implemented persistence
> design see `docs/engineering/persistence-architecture.md`.

## Guarantees

- **Determinism:** the in-memory adapter returns identical `content_hash` for
  identical stored state across runs and machines (asserted by tests).
- **No I/O / no ML in the core** (Freeze §9): the package depends only on
  `emg-memory-graph`, `emg-common-types`, `emg-errors`, and pydantic.
- **No dependency cycle:** `emg-platform-core` depends on `emg-memory-graph`,
  never the reverse.
- **100% test coverage** on the package (unit, port-contract, determinism,
  tenant-isolation, transaction lifecycle, adversarial).
