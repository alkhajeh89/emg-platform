# Phase 2 — Persistence Binding — Implementation Plan

**Status:** **COMPLETE.** All 8 sprints below were implemented, tested against real PostgreSQL 16 + Neo4j 5 Community, and merged to `develop` via the `persistence` CI job. See `PHASE2_COMPLETION.md` for full validation evidence, final test counts, and known non-blocking technical debt. The §7 checklist below has been updated from its original "Not started" planning state to reflect what the repository actually contains, per-sprint, with commit evidence.
**Aligns to:** `PHASE2_ARCHITECTURE.md` **Revision 3 (APPROVED)** — ADR-1…ADR-6, D1–D3, plus the ADR-6 refinement (explicit `ProjectionWorker`, approved 2026-07-24).
**Base:** `develop` (Phase 1 merged: `38ffcf7`, `5373009`).
**Package:** `libs/python/emg-persistence` (D3) — implemented.

## Non-negotiable architectural invariants (every sprint must uphold)

1. **PostgreSQL is authoritative** (ADR-1). Neo4j is a **serving projection only**, rebuildable from PostgreSQL.
2. **Neo4j is NOT on the write open/commit path** (ADR-5). Transaction open loads the snapshot from `graph_revisions.graph_json` at `graph_head`; `diff_graphs` compares against that PostgreSQL snapshot. Writes remain available when Neo4j is down.
3. **`write()` performs no work after returning** (ADR-6). No hidden post-return worker. Catch-up is read-repair + explicit `catch_up_projection(tenant)`.
4. **`read()` supports a PostgreSQL fallback** (§5.1) — authoritative data readable whenever PostgreSQL is up.
5. **`graph_json` is the authoritative snapshot** used for open + read-fallback.
6. **No-op head revalidation is mandatory** (§7 step 3): return a no-op receipt only if the head is still `(R0,H0)`, else `PersistenceConflictError` — never a stale-head receipt.
7. **`content_hash` is non-unique** (ADR-3); `(tenant_id, revision_number)` is revision identity.
8. **Outbox contract unchanged** (§9): exactly one `graph.revision.committed` per committed revision; node/edge events are Phase 4.
9. **`GraphStore`/`GraphTransaction`/`WriteReceipt` public API is unchanged** (Phase 1 port). Phase 2 is purely additive; the in-memory adapter remains the default for unit tests.
10. **`emg-memory-graph` is single-tenant** (D1); tenant scoping lives at the storage boundary. No change to `emg-memory-graph` or `emg-platform-core`.

Cross-cutting rule: the **Phase 1 behavioural contract suite is the executable specification** — the persistent adapter must pass the identical contract the in-memory adapter passes.

---

## Sprint 1 — Package scaffolding, settings, DI, factory, errors

**Objective.** Stand up `emg-persistence` as an installable, type-clean package with configuration, the DI factory, and the error hierarchy — no DB access yet. The factory returns the Phase 1 `InMemoryGraphStore` when no DSNs are configured, so the package is usable and testable before any driver work.

**Files to create.**
- `libs/python/emg-persistence/pyproject.toml` — deps: `emg-platform-core`, `emg-memory-graph`, `emg-errors`, `neo4j`, `psycopg[binary]`, `pydantic>=2.8`, `pydantic-settings`; `[dev]`: pytest, mypy, ruff; `hatchling>=1.14,<2`, `dev-mode-dirs=["src"]` (repo convention).
- `src/emg_persistence/__init__.py` — curated `__all__`, `__version__="0.1.0"`.
- `src/emg_persistence/config.py` — `PersistenceSettings` (pydantic-settings): `postgres_dsn: str | None`, `neo4j_uri/user/password: str | None`, pool sizes, timeouts; env-prefixed (`EMG_PERSISTENCE_*`).
- `src/emg_persistence/errors.py` — `PersistenceError(EMGError)`, `PersistenceConflictError(PersistenceError)`, `ProjectionLagError(PersistenceError)` (internal only).
- `src/emg_persistence/factory.py` — `build_graph_store(settings: PersistenceSettings) -> GraphStore` (returns `InMemoryGraphStore` when DSNs absent; the persistent store is wired in later sprints).
- `src/emg_persistence/py.typed`.
- `tests/test_import.py`, `tests/test_config.py`, `tests/test_factory.py`, `tests/test_errors.py`.

**Files to modify.** None outside the new package. (Package is auto-discovered by `install-libs.sh` + pytest — no tooling change.)

**Dependencies.** Phase 1 `emg-platform-core` (ports, `InMemoryGraphStore`). No DB.

**Implementation steps.**
1. Scaffold package + `pyproject.toml` (mirror an existing lib's shape).
2. `PersistenceSettings` with typed optional DSNs + validation (URI shape checks only, no connection).
3. Error hierarchy under `emg_errors.EMGError`.
4. `build_graph_store` selecting in-memory vs (future) persistent by DSN presence; document the seam.
5. Curated `__init__` exports; `py.typed`.

**Acceptance criteria.** Package imports; `build_graph_store(PersistenceSettings())` returns an object satisfying `isinstance(x, GraphStore)`; `mypy --strict` clean; ruff/black clean.

**Risks.** Over-scoping settings. → Keep settings minimal; add fields when a sprint needs them.

**Rollback strategy.** Additive package — delete the directory / revert the sprint commit; zero impact on existing code (in-memory remains default).

**Definition of Done.** New package builds + installs editable; factory returns a working in-memory `GraphStore`; unit tests + `make typecheck` green; no existing test affected.

**Testing.** *New:* import/config/factory/errors unit tests. *Existing affected:* none. *Expected coverage:* 100% of the (small) new surface.

**CI impact.** The `quality` + `typecheck` jobs pick up the new package automatically (glob). **No DB job yet.**

---

## Sprint 2 — PostgreSQL schema, migration runner, migrations, migration tests

**Objective.** Deliver the hardened migration runner (§10) and the baseline PostgreSQL schema (§11), applied to a real ephemeral PostgreSQL in tests. No `GraphStore` behaviour yet.

**Files to create.**
- `src/emg_persistence/postgres/pool.py` — psycopg connection pool (lazy, from settings).
- `src/emg_persistence/migrate.py` — runner with **all §10 guarantees**: `schema_migrations` history table; immutable SHA-256 checksums; checksum verification on start; failed (`success=false`) + dirty detection & halt; transactional PostgreSQL migrations; idempotent Neo4j migrations (marker `:SchemaMigration`).
- `src/emg_persistence/migrations/postgres/V001__baseline.sql` — `tenants`, `graph_revisions` (PK `(tenant_id,revision_number)`, **non-unique** index `(tenant_id,content_hash)` — ADR-3), `graph_head` (PK `tenant_id`), `outbox` (PK `event_id`, UNIQUE `idempotency_key`), `schema_migrations`. **`evidence_ledger` table too** (schema only; ADR-4 — not used by `GraphStore`).
- `src/emg_persistence/migrations/neo4j/M001__constraints.cypher` — `:MemoryNode`/`:MEMORY_EDGE`/`:GraphHead` constraints + indexes via `CREATE ... IF NOT EXISTS`.
- `tests/integration/test_migrations.py`.

**Files to modify.** `PersistenceSettings` (add pool params if needed); `__init__` exports (`migrate` entrypoint).

**Dependencies.** Sprint 1. Requires PostgreSQL + Neo4j test containers (compose/testcontainers).

**Implementation steps.**
1. Connection pool + a `neo4j` driver holder (`neo4j/driver.py` may land here or Sprint 5; keep minimal).
2. Migration runner: discovery, ordering, checksum recording/verification, dirty/failed detection, transactional apply (PG), idempotent apply (Neo4j).
3. Author `V001` (exact §11 schema; **assert non-unique** on `content_hash`) and `M001`.
4. Migration tests: clean apply; idempotent re-apply; checksum-change detection → fail; dirty-state halt.

**Acceptance criteria.** Baseline applies cleanly on empty DBs; re-apply is a no-op; a tampered migration checksum is rejected; a simulated mid-migration death leaves a detectable dirty state that halts the next run; **`content_hash` index is non-unique** (a duplicate hash inserts successfully in a probe).

**Risks.** *Migration:* partial apply. → transactional PG + dirty detection. *Testing:* container flakiness. → health-gated waits.

**Rollback strategy.** Forward-only; emergency `*_down.sql` retained but discouraged. Reverting the sprint removes the runner + migrations; no production data exists yet.

**Definition of Done.** `migrate.py` meets every §10 guarantee with tests; baseline schema matches §11 exactly; migration tests green against real containers.

**Testing.** *New:* migration integration tests (DB-backed). *Existing affected:* none. *Expected coverage:* >95% of `migrate.py`; schema exercised by later sprints.

**CI impact.** **Introduce the new `persistence` CI job** (PostgreSQL 16 + Neo4j 5 **Community**, §15): apply migrations + run migration tests. Existing `quality`/`typecheck` unchanged.

---

## Sprint 3 — RevisionRepository, graph_head, compare-and-set, first-revision handling

**Objective.** Implement the authoritative revision log and head mechanics (§7, §11) as a repository — the core durability primitive — independent of the full `GraphStore`.

**Files to create.**
- `src/emg_persistence/postgres/revisions.py` — `RevisionRepository`: `get_head(tenant) -> (R0,H0)|None`; `load_revision(tenant, R) -> graph_json`; `append_revision(...)` with **compare-and-set head** (`UPDATE graph_head ... WHERE head_revision_number = R0`) and **first-revision** `INSERT ... ON CONFLICT (tenant_id) DO NOTHING`; `revalidate_head(tenant, R0, H0) -> bool` (`SELECT ... FOR SHARE`).
- `tests/integration/test_revisions.py`, `tests/integration/test_concurrency_head.py`.

**Files to modify.** `__init__` (internal exports if needed).

**Dependencies.** Sprints 1–2 (schema + pool).

**Implementation steps.**
1. Head read + revision load (returns authoritative `graph_json`).
2. `append_revision` in one transaction: insert revision `R0+1`; CAS head; **exactly one** outbox insert is deferred to Sprint 6 (here a placeholder or injected callback — keep the atomic-with-revision requirement documented so Sprint 6 slots in without changing the transaction boundary).
3. First-revision path via `INSERT ... ON CONFLICT DO NOTHING`; 0-rows → conflict.
4. `revalidate_head` for the no-op path (Sprint 4 consumer).
5. Concurrency tests at the repository level.

**Acceptance criteria.** Sequential appends produce gap-free `revision_number`; CAS rejects a stale parent (0 rows → conflict signal); first-revision race → exactly one INSERT wins; rollback revision reproducing a prior `content_hash` inserts successfully (non-unique).

**Risks.** *Technical:* CAS correctness. → dedicated concurrency tests (two connections). *Architectural:* leaking outbox coupling early. → keep the transaction boundary explicit for Sprint 6.

**Rollback strategy.** Additive module; revert removes it; schema untouched.

**Definition of Done.** RevisionRepository passes sequential + concurrent tests; compare-and-set + first-revision semantics match §7; `content_hash` non-uniqueness demonstrated.

**Testing.** *New:* revision + head + concurrency integration tests. *Existing affected:* none. *Expected coverage:* >95% of `revisions.py`.

**CI impact.** Runs in the `persistence` job. No new job.

---

## Sprint 4 — GraphStore write path: PostgreSQL transaction, no-op, optimistic concurrency, WriteReceipt

**Objective.** Implement `PostgresNeo4jGraphStore`'s **authoritative write/open path using PostgreSQL only** (ADR-5), including no-op head revalidation (§7 step 3) and the `WriteReceipt` — **without any Neo4j dependency**. `write()` returns at the PostgreSQL commit and does no post-return work (ADR-6).

**Files to create.**
- `src/emg_persistence/store.py` — `PostgresNeo4jGraphStore` (write/open/tenants/receipt paths) + `_PersistentTransaction` (mirrors the Phase 1 lifecycle: OPEN/COMMITTED/ABORTED, `receipt` after commit).
- `tests/integration/test_write_path.py`, `tests/integration/test_noop_revalidation.py`, `tests/contract/` bootstrap (parameterize Phase 1 contract over this store — write/tenants portions runnable without Neo4j via PG-fallback read from Sprint 5; where read is required, mark xfail until Sprint 5 or use the PG snapshot loader directly).

**Files to modify.** `factory.py` (return `PostgresNeo4jGraphStore` when DSNs present); `__init__` exports.

**Dependencies.** Sprints 1–3.

**Implementation steps.**
1. **Open (ADR-5):** `get_head` + `load_revision(graph_json)` → `MemoryGraph G0` (or `EMPTY_GRAPH`); carry `(G0,R0,H0)`. **No Neo4j.**
2. **Body/commit:** compute `H1`; `diff_graphs(new, G0)`.
3. **No-op (§7 step 3):** if `H1==H0`, `revalidate_head`; equal → no-op receipt; changed → `PersistenceConflictError`.
4. **Change path:** `append_revision` (revision + CAS head; outbox insert injected in Sprint 6) → on 0 rows conflict; on commit build `WriteReceipt(H1,…)`.
5. **Return:** receipt; **no post-return work** (ADR-6).
6. Wire `factory` to select the persistent store.

**Acceptance criteria.** Write open/commit succeed **with Neo4j absent**; no-op with unchanged head returns a receipt; no-op with concurrently-advanced head raises `PersistenceConflictError` (no stale receipt); `WriteReceipt` fields correct; `write()` provably performs no work after returning (no projection call on the write path).

**Risks.** *Architectural:* accidentally reading from Neo4j on open. → explicit test: write with Neo4j driver unconfigured/stopped. *Technical:* transaction-boundary leaks. → single-transaction append.

**Rollback strategy.** Additive; factory falls back to in-memory if the persistent store is reverted.

**Definition of Done.** Full write path is PostgreSQL-only, passes write/no-op/concurrency tests **without Neo4j**, and honors ADR-2/ADR-5/ADR-6.

**Testing.** *New:* write-path, no-op-revalidation, first cut of contract (write side). *Existing affected:* Phase 1 contract suite is *reused* (parameterized), not modified. *Expected coverage:* >95% of the write path.

**CI impact.** `persistence` job now runs write-path + no-op tests. Neo4j container present but the write tests also run with it stopped (availability assertion).

---

## Sprint 5 — Neo4j projection: apply, reconstruction, GraphHead, read-repair, catch_up_projection, PostgreSQL fallback

**Objective.** Implement the serving projection and the full `read()` path (§5, §5.1, §8, ADR-6) — the only place Neo4j is used.

**Files to create.**
- `src/emg_persistence/neo4j/driver.py` (if not in Sprint 2), `src/emg_persistence/neo4j/projection.py` — `Neo4jGraphProjection`: idempotent diff `apply`; `reconstruct(tenant) -> MemoryGraph`; `get_projection_head`; **monotonic compare-and-set `:GraphHead`** (§8); `read_repair(tenant)`; `catch_up_projection(tenant) -> applied_through_revision`; `rebuild_projection(tenant)`.
- store `read()` implementation with **PostgreSQL fallback** (§5.1).
- `tests/integration/test_projection.py`, `tests/integration/test_read_repair.py`, `tests/integration/test_read_fallback.py`, `tests/integration/test_catch_up.py`, `tests/integration/test_reconstruction.py`.

**Files to modify.** `store.py` (wire `read()`), `factory.py` (inject projection).

**Dependencies.** Sprints 1–4.

**Implementation steps.**
1. Parameterized `UNWIND MERGE/DELETE` idempotent apply keyed by node/edge id; `content_json` per node/edge.
2. `reconstruct` → deserialize `content_json` → `MemoryGraph`; assert **canonical `content_hash` equality** (§6), not byte equality.
3. Monotonic `:GraphHead` CAS (`expected → expected+1`); never regresses.
4. `read()`: prefer Neo4j (read-repair on lag); **fallback to PostgreSQL `graph_json`** when Neo4j unavailable.
5. Explicit `catch_up_projection` (replays pending revisions idempotently); `rebuild_projection` from the log.

**Acceptance criteria.** Reconstructed graph hash == authoritative head hash; read-repair advances a lagging projection monotonically; concurrent repairs never regress/double-apply; **read returns the correct graph with Neo4j stopped** (PG fallback); `catch_up_projection` reaches head and is idempotent.

**Risks.** *Technical:* non-monotonic head under concurrency. → CAS + idempotent apply tests. *Architectural:* projection creeping onto the write path. → assert write tests still pass with Neo4j down.

**Rollback strategy.** Additive; without the projection, `read()` uses PG fallback only (still correct, slower for topology — acceptable interim).

**Definition of Done.** Full `read()` path (Neo4j-preferred + PG fallback) + read-repair + `catch_up_projection` implemented and tested; reconstruction is canonical-hash-correct; the **whole Phase 1 contract suite now passes against the persistent store**.

**Testing.** *New:* projection/read-repair/fallback/catch-up/reconstruction. *Existing affected:* Phase 1 contract suite reused end-to-end. *Expected coverage:* >95% of projection + read path.

**CI impact.** `persistence` job runs the full read/projection suite (needs Neo4j up) plus the Neo4j-down fallback tests.

---

## Sprint 6 — Transactional outbox: event payload, ordering, idempotency, replay model

**Objective.** Implement the outbox (§9) as part of the write transaction — exactly one `graph.revision.committed` per committed revision; no node/edge events (Phase 4).

**Files to create.**
- `src/emg_persistence/postgres/outbox.py` — `OutboxRepository.enqueue(tenant, revision_number, content_hash, ...)` writing an `outbox` row **inside the revision transaction** (via the Sprint 3 injection point).
- `tests/integration/test_outbox.py`.

**Files to modify.** `revisions.py`/`store.py` — insert the outbox row atomically with the revision + head CAS (single transaction); no-op writes emit **no** row.

**Dependencies.** Sprints 3–4.

**Implementation steps.**
1. Outbox row with all §9 fields (`event_id`, `tenant_id`, `revision_number`, `content_hash`, `event_type='graph.revision.committed'`, `schema_version=1`, `idempotency_key=f"{tenant}:{rev}"`, `payload`, timestamps).
2. Insert within the revision transaction; UNIQUE `idempotency_key`.
3. Ordering + replay semantics documented; no publisher (Phase 4).

**Acceptance criteria.** Every committed revision has exactly one outbox row; no-op writes produce none; `idempotency_key` unique; per-tenant `revision_number` ordering is gap-free; an event exists iff its revision committed (atomicity).

**Risks.** *Architectural:* emitting node/edge events (out of scope). → assert exactly one event type. *Technical:* outbox outside the revision transaction. → single-transaction test (rollback leaves no row).

**Rollback strategy.** Additive; revert removes outbox writes (revisions still commit). Forward-safe.

**Definition of Done.** Outbox atomic with revisions; §9 fields/ordering/idempotency verified; no-op emits nothing.

**Testing.** *New:* outbox atomicity/ordering/idempotency/no-op-no-event. *Existing affected:* write-path tests extended to assert the outbox row. *Expected coverage:* >95% of `outbox.py`.

**CI impact.** Within the `persistence` job. No new job.

---

## Sprint 7 — Contract, concurrency, recovery, migration, performance validation

**Objective.** Complete the §14 test matrix and prove parity + resilience; no new production behaviour (test-only sprint, plus any fixes surfaced).

**Files to create.**
- `tests/contract/test_contract_parity.py` — the Phase 1 behavioural suite parameterized over `InMemoryGraphStore` **and** `PostgresNeo4jGraphStore`.
- `tests/integration/test_recovery.py` — crash-after-commit / projection-failure → read-repair or PG-fallback.
- `tests/integration/test_concurrency_full.py` — first-revision race, subsequent-head race, concurrent read-repair/catch-up.
- `tests/integration/test_performance.py` — budget-based (diff-write, read/reconstruct, catch-up) on a moderate graph.

**Files to modify.** Minor test-support helpers; production code only if a real defect is found (stop-and-report if it implies an architecture change).

**Dependencies.** Sprints 1–6.

**Implementation steps.**
1. Wire contract parity (single source of truth for behaviour).
2. Recovery: simulate Neo4j apply failure post-commit; assert receipt already returned + eventual correctness.
3. Concurrency: the three races (no lost update; no stale-head receipt; monotonic head).
4. Performance budgets (documented, not micro-benchmarks).

**Acceptance criteria.** Persistent store passes the **entire** Phase 1 contract; all §14 concurrency/recovery/migration cases green; performance within documented budgets; cross-tenant isolation proven (P0).

**Risks.** *Testing:* flaky concurrency/timing. → deterministic barriers/handshakes; retries only where semantically valid. *Architectural:* a test reveals a spec gap. → stop-and-report, do not silently deviate.

**Rollback strategy.** Test-only; revertable with zero production impact.

**Definition of Done.** Full §14 matrix green against real containers; contract parity established; isolation + recovery proven.

**Testing.** *New:* contract/concurrency/recovery/perf. *Existing affected:* consolidates prior sprint tests. *Expected coverage:* package >95%, all categories represented.

**CI impact.** `persistence` job runs the complete matrix (longest-running job).

---

## Sprint 8 — Integration, CI finalization, documentation, PHASE2_COMPLETION.md

**Objective.** Finalize CI, documentation, and the completion report; confirm zero regression to Phases 0/1 and no breaking API change.

**Files to create.**
- `docs/engineering/persistence-architecture.md`, `docs/engineering/persistence-operations.md` (migrations, catch-up/rebuild runbook), update `storage-ports.md` "Adapters" row (Neo4j/Postgres now implemented behind the same port).
- `PHASE2_COMPLETION.md` (completed/remaining work, technical debt, validation summary, baseline comparison vs Phase 1, risks).

**Files to modify.** `.github/workflows/ci.yml` — finalize the `persistence` job (service health-checks, driver caching); `docs/engineering/technical-debt.md` (any Phase 2 deferrals, e.g. continuous projection worker); `EMG_ARCHITECTURE_ROADMAP`/review (mark Phase 2 done). Optionally note `docker-compose.yml` Neo4j Community alignment (flagged in §15) — change only with approval.

**Dependencies.** Sprints 1–7.

**Implementation steps.**
1. Finalize CI job; confirm `quality`/`typecheck` still green with the new package.
2. Documentation + operations runbook (catch-up/rebuild/migrations).
3. `PHASE2_COMPLETION.md` with validation evidence and baseline comparison.
4. Full-repo regression: ruff/black/pytest/`make typecheck`/pre-commit + the DB job.

**Acceptance criteria.** All CI jobs green; docs complete; `PHASE2_COMPLETION.md` produced; **no Phase 0/1 regression**; `GraphStore` public API unchanged (in-memory contract still passes).

**Risks.** *Technical:* CI time growth. → caching + health gates. *Architectural:* doc/impl drift. → docs generated from the approved rev 3.

**Rollback strategy.** Whole Phase 2 is additive behind the factory; the default remains in-memory until a service opts in. A single revert of the Phase 2 commits restores Phase 1 exactly.

**Definition of Done.** Phase 2 complete; every invariant (top of this plan) verified by tests; completion report + docs delivered; awaiting review before Phase 3.

**Testing.** *New:* none (finalization). *Existing affected:* full suite runs in CI. *Expected coverage:* package >95% maintained; whole-repo suite green.

**CI impact.** `persistence` job finalized and required; `quality` + `typecheck` unchanged in scope (auto-cover the new package).

---

## 6. Risk management (consolidated)

**Technical risks.**
- Cross-store consistency (PG committed, Neo4j lagging) → authoritative log + idempotent projection + read-repair + PG read-fallback (ADR-1/5/6); recovery tests (S5, S7).
- Compare-and-set / monotonic-head correctness under concurrency → dedicated two-connection concurrency tests (S3, S5, S7).
- Reconstruction correctness vs JSON drift → canonical `content_hash` equality, never byte equality (S5).
- CI time growth from DB containers → health-gated waits + driver caching (S2, S8).

**Architectural risks.**
- Neo4j creeping onto the write path (violates ADR-5) → explicit "write with Neo4j down" tests (S4); component boundaries enforced in review.
- Hidden post-return work (violates ADR-6) → `write()` returns at commit; projection only via read-repair/`catch_up_projection`; asserted in S4/S5.
- Emitting node/edge events early (violates §9) → exactly-one-event assertion (S6).
- Mutating the frozen model or the Phase 1 port (violates D1 / API-unchanged) → additive-only; contract suite reused unmodified.

**Migration risks.**
- Partial/dirty apply → transactional PG migrations + dirty/failed detection + checksum immutability (S2).
- Accidental `UNIQUE(content_hash)` (blocks rollback) → schema review + non-uniqueness probe test (S2, S3).
- Environment drift → checksum-verified history table; CI-gated migrations (S2, S8).

**Testing risks.**
- Flaky concurrency/timing tests → deterministic barriers/handshakes; bounded retries only where valid (S3–S7).
- Container flakiness in CI → service health checks; retries on startup only (S2, S8).
- Coverage gaps on error/fallback branches → explicit fallback/recovery/no-op-stale tests (S4–S7).

---

## 7. Final checklist

| Sprint | Status | Dependencies | Evidence (commits) | Complexity |
|---|---|---|---|---|
| S1 — Scaffold, settings, DI, factory, errors | **Complete** | Phase 1 | `705d4de`, `d4c0ed8` | Low |
| S2 — Schema, migration runner, migrations, tests | **Complete** | S1 | `f0ff6b2` | Medium |
| S3 — RevisionRepository, head, CAS, first-revision | **Complete** | S1–S2 | `af2985b` | Medium |
| S4 — GraphStore write path, no-op, optimistic concurrency, receipt | **Complete** | S1–S3 | `e4dcad0` | High |
| S5 — Neo4j projection, reconstruction, read-repair, catch-up, PG fallback | **Complete** | S1–S4 | `73d4942` (projection); `cb3087f` (PostgreSQL-fallback defect found and fixed — see `PHASE2_COMPLETION.md`); `237944e`, `23303c2` (unit + real-DB tests) | High |
| S6 — Transactional outbox, ordering, idempotency, replay | **Complete** | S3–S4 | `2371b75`; checkpoint foundation `306d3a9` (ADR-6 refinement, explicit `ProjectionWorker`) | Medium |
| S7 — Contract, concurrency, recovery, migration, performance | **Complete** | S1–S6 | `tests/contract/test_graph_store_contract.py` (in `e4dcad0`); concurrency/recovery covered across the integration suite (33 DB-gated tests) | Medium |
| S8 — Integration, CI, docs, PHASE2_COMPLETION.md | **Complete** | S1–S7 | `4a7fe1e` (persistence CI job: PostgreSQL 16 + Neo4j 5 Community), `bdf7450` (migration-test schema isolation — independent hardening, not a root-cause fix), `3e80953` (Cypher-comment splitter fix — the actual CI root cause), `PHASE2_COMPLETION.md` (this closure) | Low |

**Sequencing note.** S2 introduced the DB-backed CI job; S3→S6 built the durability core in dependency order (repository → write path → projection/read → outbox); S7 proved the contract/resilience; S8 finalized CI and documentation. Every sprint stayed additive and revertable, and no sprint violated the invariants at the top of this plan.

---

**Phase 2 is complete.** All 8 sprints above are implemented, tested against real PostgreSQL 16 + Neo4j 5 Community service containers in the `persistence` CI job, and merged to `develop`. See `PHASE2_COMPLETION.md` for the full validation record.
