# emg-platform-core

**EMG Platform Foundation — Phase 1.** The storage-independence seam that every
future EMG service is built on.

This package is deliberately small and pure. It contains **no I/O and no ML**
(Freeze §9); it defines the *contracts* through which services will later reach
durable storage, plus a deterministic in-memory implementation used for tests
and local development.

## What's here

- **Ports** (`emg_platform_core.ports`) — `GraphStore` and `GraphTransaction`
  `Protocol`s: the abstract, storage-independent contract for reading and
  writing an immutable `MemoryGraph`, expressed purely in domain terms (no
  database concepts). Realises the frozen "one writer per store … storage
  independent" boundary (Freeze §11) and the `GraphStore` port (Freeze §32).
- **Identity** (`emg_platform_core.identity`) — `TenantId` and `PrincipalRef`
  frozen value types: the cross-cutting multi-tenancy and provenance dimensions
  the freeze requires on every datum and every mutation (Freeze §9, §12). Defined
  here now; threaded through persistence in Phase 2.
- **Adapters** (`emg_platform_core.adapters`) — `InMemoryGraphStore`, a
  deterministic, tenant-scoped, in-process implementation of `GraphStore` over
  `emg-memory-graph`. Test/dev only; the Neo4j and Postgres adapters arrive in
  Phase 2 (Freeze §32: "a Neo4j adapter for durability and an in-memory adapter
  for tests").

## What's NOT here (by design)

No database drivers, no networking, no persistence engine, no migrations — those
are Phase 2. The core stays deterministic and unit-testable forever, exactly as
the frozen architecture mandates.

## Design

Hexagonal (ports & adapters): services depend on the `GraphStore` *interface*;
concrete stores are injected. This keeps the deterministic memory-graph core free
of storage concerns and makes Neo4j/Postgres/in-memory fully swappable without
touching domain logic.
