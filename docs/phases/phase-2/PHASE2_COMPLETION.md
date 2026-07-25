# Phase 2 — Persistence Binding — Completion Report

**Status:** COMPLETE.
**Aligns to:** `PHASE2_ARCHITECTURE.md` Revision 3 (ADR-1…ADR-6) plus the ADR-6 refinement (explicit `ProjectionWorker`, approved 2026-07-24).
**Package:** `libs/python/emg-persistence`.
**CI:** `persistence` job (`.github/workflows/ci.yml`) — PostgreSQL 16 + Neo4j 5 Community — passed on the merged pull request.

---

## 1. Implemented capabilities

- **PostgreSQL authoritative persistence** (ADR-1, ADR-5) — `store.py::PostgresNeo4jGraphStore`; transaction open and commit read/write only `graph_head` and `graph_revisions.graph_json`; Neo4j is never on the write path.
- **Graph revisions + graph-head consistency** (ADR-3) — `postgres/revision_repository.py`; `graph_revisions` keyed `(tenant_id, revision_number)`; **non-unique** `(tenant_id, content_hash)` index, so a rollback revision may legally repeat an earlier hash.
- **Optimistic concurrency / compare-and-set** — conditional `UPDATE graph_head ... WHERE head_revision_number = R0`; first-revision `INSERT ... ON CONFLICT (tenant_id) DO NOTHING`; no-op writes revalidate the authoritative head before ever returning a receipt (§7 step 3 of the architecture doc), never a stale-head receipt.
- **Transactional outbox** (§9) — `postgres/outbox_repository.py`; exactly one `graph.revision.committed` row per committed revision, written atomically with the revision in the same transaction; no-op writes emit no row; `idempotency_key` unique.
- **Projection Worker** (ADR-6 refinement) — `projection/worker.py` with `postgres/checkpoint_repository.py`; consumes outbox rows and applies the Neo4j projection; checkpoints for idempotency; never started by `GraphStore.write()` — invoked explicitly only.
- **Neo4j apply + reconstruction** (§5, §6) — `neo4j/projection.py`; diff-based idempotent `apply` (`UNWIND`/`MERGE`/`DELETE`); reconstruction verified by canonical `content_hash` equality, not byte equality; bilingual (Arabic + English) content round-trips correctly (ADR-7 / ADR-018).
- **Catch-up projection, read repair, rebuild** (§8, ADR-6) — `catch_up_projection()`, `read_repair()`, `rebuild_projection()`; monotonic compare-and-set on `:GraphHead`; idempotent apply guarantees concurrent repairers converge without double-applying or regressing.
- **PostgreSQL fallback when Neo4j is unavailable** (ADR-5 §5.1) — `store._read_via_projection`; reads remain available whenever PostgreSQL is up, regardless of Neo4j's health.
- **Migration safety and dirty-state handling** (§10) — `migrations/runner.py`: immutable SHA-256 checksums, checksum verification on start, failed/dirty detection and halt, transactional PostgreSQL migrations, idempotent Neo4j migrations (`CREATE CONSTRAINT/INDEX IF NOT EXISTS`).

## 2. Validation evidence

Two genuine production defects were found and fixed during Phase 2 hardening, not merely reported — both under the same "stop, report, get approval, fix narrowly, re-validate" discipline used throughout:

1. **PostgreSQL read-fallback defect** (`store.py::_read_via_projection`) — a Neo4j connection failure during `get_projection_head()` sat outside the `try`/`except` that only guarded `read_repair()`, so it was re-raised instead of falling back to PostgreSQL, directly contradicting ADR-5/§5.1's availability guarantee. Reproduced locally with a real `Neo4jGraphProjection` wrapped around a fake exploding driver (no live DB required to prove it), fixed as an isolated 9-line diff (commit `cb3087f`), and covered by a live-DB integration test (`test_store_read_falls_back_to_postgresql_when_neo4j_is_unreachable`) against a genuinely unreachable Neo4j port.
2. **Neo4j migration M1 false dirty-state cascade** — `split_cypher_statements()` called `text.split(";")` on the raw migration file before stripping `//` comments. M001's own header comment contained a semicolon in its prose ("...indexes only; no enterprise-only..."), so the raw split cut that comment in half; the tail fragment no longer started with `//` and leaked into the next statement as `no enterprise-only\n\nCREATE CONSTRAINT ...`, which Neo4j rejected as `CypherSyntaxError`. This marked M1 dirty and cascaded `DirtyMigrationError` across every integration test/file whose fixtures called `run_migrations()` against Neo4j afterward. Verified the migration file itself was valid and its constraint syntax fully `neo4j:5-community` compatible (checked directly against Neo4j's current Cypher Manual: property uniqueness constraints, including composite ones, carry no Enterprise-only tag). Fixed by stripping comments from the full text before splitting on `;` (commit `3e80953`), with regression tests covering full-line comments containing `;`, inline trailing comments containing `;`, multiple `;` inside comment prose, and the real M001 file producing exactly its 4 intended statements.

A third, independent hardening change was also made during this investigation: `test_migration_integration.py`'s Postgres tests were moved into a dedicated `migration_test` schema (commit `bdf7450`), because its deliberately-dirtied synthetic migrations reused the same version numbers as the real baseline migrations in the same shared `public.schema_migrations` table used by every other integration file. **This schema-isolation change is retained as a useful, independent test-isolation improvement — it was investigated first and is a real structural risk worth closing, but it was not the root cause of the CI failure.** The actual root cause was the Cypher-comment-splitter defect above, found afterward by inspecting the second CI run's evidence.

## 3. CI result

The `persistence` job in `.github/workflows/ci.yml` runs against `postgres:16-alpine` and `neo4j:5-community` service containers (Neo4j readiness gated solely by the Python driver's `verify_connectivity()`, per an earlier reliability review — no unverified `cypher-shell` health-check dependency), executing `libs/python/emg-persistence/tests/integration`. This job **passed** on the merged Phase 2 persistence pull request, with no separate migration step required (integration test fixtures apply migrations themselves).

## 4. Final test counts

- `emg-persistence` package: **209 passed, 33 skipped** locally (the 33 are DB-gated integration tests that skip without live PostgreSQL/Neo4j; they ran and passed in CI against the real containers). Package coverage: **94%** (`store.py` 81%, `neo4j/lazy.py` 33%, all other modules 100% — see §5).
- Full monorepo suite: **1258 passed, 49 skipped**, 0 failures.
- Dependency checks: manifest validation, drift detection, and implicit-dependency detection all pass across all 20 manifest components (18 libraries + 2 services).

## 5. Known non-blocking technical debt

Recorded in `docs/engineering/technical-debt.md`:

- The continuous `ProjectionWorker` daemon/lifecycle (retry, back-pressure, scheduling) remains deferred; explicit invocation is the current, approved behavior per the ADR-6 refinement.
- `neo4j/lazy.py`'s driver-construction path (`.get()`/`.close()` when Neo4j is configured) is unit-testable but not yet covered (16/24 lines).
- `store.py`'s remaining uncovered lines are `# pragma: no cover — live DB only` branches exercised by the DB-gated integration suite, not by local no-DB coverage runs.
- The parallel project-status tracking systems (this `docs/phases/` Phase-2/Sprint numbering vs. the older EPIC/Module Sprint-numbering in `ARCHITECTURE_STATUS.md` / `services/README.md`) are recorded as documentation debt, not reconciled here.

## 6. Confirmation

**Phase 2 (Persistence Binding) is complete.** Every architectural invariant in `PHASE2_ARCHITECTURE.md` Revision 3 is implemented, adversarially tested (including two real defects found and fixed, not just planned-for), and proven in CI against real PostgreSQL 16 and Neo4j 5 Community. The `GraphStore` public port is unchanged; the in-memory adapter remains the default for unit tests; no Phase 0/1 regression was introduced (full monorepo suite green).
