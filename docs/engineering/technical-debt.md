# Engineering Technical-Debt Register

Deliberate, tracked debt for the EMG platform. Each item records root cause, why
it is currently accepted, the recommended resolution, and the phase in which it
is expected to be paid down. Items here are *conscious engineering decisions*,
not unknown defects. (Repository-wide `grep` finds no `TODO`/`FIXME`/`HACK`
markers in `src`; debt is documented, not scattered.)

| ID | Title | Severity | Status | Target phase |
|----|-------|----------|--------|--------------|
| TD-001 | `mypy --strict` not enforced in `make lint` / CI | Low | **RESOLVED in Phase 1** | — |
| TD-002 | Continuous `ProjectionWorker` daemon/lifecycle deferred | Low | Open, accepted (Phase 2) | Future — when continuous projection is needed |
| TD-003 | `neo4j/lazy.py` driver-construction path lacks unit coverage | Low | **RESOLVED 2026-08-02 (P-01, `cdbf0ca`)** | — |
| TD-004 | Parallel project-status tracking systems (`docs/phases/` vs. `ARCHITECTURE_STATUS.md`/`services/README.md`) | Low | Open, accepted — documentation debt only | Unscheduled |

---

## TD-001 — `mypy --strict` is not wired into `make lint` or CI

**Severity:** Low. This is an *automation/enforcement* gap, not a type-safety
gap: the codebase already type-checks clean under `mypy --strict` when run the
way prior sprints ran it (per package). The debt is that nothing currently
enforces that on every change.

**Status:** Open, accepted in Phase 0.

### Root cause

The monorepo contains many packages, and most ship a `tests/` package with its
own `tests/__init__.py`:

```
libs/python/emg-api-contracts/tests/__init__.py
libs/python/emg-audit-client/tests/__init__.py
libs/python/emg-... /tests/__init__.py
services/identity/tests/__init__.py
services/audit/tests/__init__.py
```

A single mypy invocation over the whole tree (`mypy libs services`, which is
what a naïve `make lint` integration would run) makes mypy's module resolver map
every one of those `tests/__init__.py` files to the *same* fully-qualified
module name `tests`. Even with the repo's `namespace_packages = true` and
`explicit_package_bases = true` (root `pyproject.toml` `[tool.mypy]`), mypy
aborts before type-checking with:

```
error: Duplicate module named "tests" (also at ".../tests/__init__.py")
Found 1 error in 1 file (errors prevented further checking)
```

Run **per package**, mypy is clean — verified during Phase 0 validation:

```
mypy libs/python/emg-common-types/src   -> Success: no issues found in 3 source files
mypy libs/python/emg-memory-graph/src   -> Success: no issues found in 20 source files
mypy libs/python/emg-semantic-layer/src -> Success: no issues found in 11 source files
```

So the failure is a **module-path collision in the aggregate invocation**, not a
type error in the code.

### Why it is currently excluded

Phase 0 carried an explicit constraint: *integrate mypy into the existing lint
workflow only if it does not change current behavior.* Today `make lint` runs
`ruff check` + `black --check` and passes. Adding `mypy libs services` would
make `make lint` exit non-zero (the duplicate-module abort above) — a direct
behavior change from pass to fail. Under the constraint, mypy was therefore
**not** wired in. Doing so "quickly" would have introduced a red gate for a
problem that is about module layout, not type safety.

### Recommended future solution

Introduce type-checking as its **own** gate (`make typecheck`, backed by a new
`tools/scripts/run-typecheck.sh`) that avoids the collision, rather than folding
it into `make lint`. Concretely, one of:

1. **Per-package iteration (preferred, lowest risk):** loop over each
   `libs/python/*` and `services/*`, running `mypy <pkg>/src` (and, in a
   separate pass, that package's `tests` with a per-package `MYPYPATH`). This
   mirrors how sprints already validate types and never triggers the collision.
2. **Distinct test package names / module mapping:** give each package's tests a
   unique importable name, or add `[[tool.mypy.overrides]]` / `mypy_path`
   configuration so the aggregate run can disambiguate.

Then wire `make typecheck` into CI (`.github/workflows/ci.yml`) as a **separate
required job**, keeping `make lint` = ruff + black. Use the pinned mypy from
`requirements-dev.txt` (`mypy>=1.10`, 1.x — validated with 1.20.2) so local and
CI agree, and do not upgrade to mypy 2.x without a dedicated evaluation (2.x
changes strictness defaults).

### Expected implementation phase

**Phase 1 (Platform Foundation)** — or an **earlier dedicated developer-experience
task before Phase 2**. This is deliberately *not* deferred to production
hardening: every new package with a `tests/` directory makes the
aggregate-invocation collision worse, so a per-package `make typecheck` gate
should land while the platform is still small, giving type-safety enforcement
from the foundation onward. It was correctly **not** a Phase 0 blocker (wiring it
into `make lint` would have changed current behavior), but it should be paid down
at the start of platform work rather than at the end.

### Resolution (Phase 1)

Resolved as planned. `tools/scripts/run-typecheck.sh` runs `mypy --strict`
(config from the root `pyproject.toml`) **per package** — iterating each
`libs/python/*/src` and `services/*/src` separately — which sidesteps the
duplicate-`tests` collision entirely. It is exposed as `make typecheck` and runs
as a **separate CI job** (`.github/workflows/ci.yml` → `typecheck`), leaving
`make lint` (ruff + black) unchanged. Verified green across all **18 packages**
(16 libraries incl. `emg-platform-core` + 2 services): "Type-check passed
(mypy --strict) for 18 package(s)." No application code required changes — the
tree was already type-clean per package; the debt was purely the missing
enforcement, now closed.

---

## TD-002 — Continuous `ProjectionWorker` daemon/lifecycle deferred

**Severity:** Low. Correctness is unaffected: the durable backlog lives in
`graph_revisions`, and `read()`/`read_repair()`/`catch_up_projection()`
already guarantee the projection converges regardless of whether a
continuous worker is running.

**Status:** Open, accepted (Phase 2, per the ADR-6 refinement approved
2026-07-24).

### Root cause / current behavior

`emg_persistence.projection.worker.ProjectionWorker` consumes outbox rows
and applies the Neo4j projection, recording `projection_checkpoints` for
idempotency, but it is **never started automatically** — `GraphStore.write()`
performs no post-return work (ADR-6), and nothing today schedules the worker
on a loop, retries it with back-pressure, or runs it as a managed daemon.
Explicit invocation (`process_once` / an operator or CI step) is the current,
approved behavior.

### Why it is currently accepted

Phase 2 deliberately scoped a continuous worker as a full lifecycle/retry/
back-pressure design out of the persistence-binding work, preferring the
simpler read-repair + explicit-catch-up model to keep Phase 2 bounded
(`PHASE2_ARCHITECTURE.md` ADR-6). This is a conscious scope decision, not an
oversight.

### Recommended future solution

Design and add a continuous daemon lifecycle (scheduling interval, retry
policy, back-pressure under sustained outbox growth, health/liveness
signal) when a consumer of `services/knowledge-graph` or a later phase
actually needs near-real-time projection freshness rather than
read-triggered repair.

### Expected implementation phase

Future — triggered by demonstrated need, not scheduled against a specific
phase today.

---

## TD-003 — `neo4j/lazy.py` driver-construction path lacks unit coverage

**Severity:** Low. `LazyNeo4jProjection.configured` (the common, no-DSN
path) is covered; the `.get()`/`.close()` driver-construction path (16 of 24
statements) is not exercised by any unit test today.

**Status:** **RESOLVED 2026-08-02** by P-01 (`cdbf0ca`, PR #52).

### Root cause

No test file imported `LazyNeo4jProjection` directly; it was only exercised
indirectly through `store.py`, and no fake/monkeypatched `create_driver` had
been written to cover its lazy-construction branch.

### Resolution

`libs/python/emg-persistence/tests/test_lazy_neo4j_projection.py` now
monkeypatches `emg_persistence.neo4j.driver.create_driver` with a fake and
asserts the lazy-construction and teardown behaviour the recommended solution
below described. No live database is required, and the test runs in the
standard unit job.

### Original recommended solution (for the record)

Add a small unit test that monkeypatches `emg_persistence.neo4j.driver.create_driver`
with a fake, asserting `.get()` constructs exactly once and caches the result,
and that `.close()` tears the fake driver down. No live database required.

---

## TD-004 — Parallel project-status tracking systems

**Severity:** Low (documentation debt only; no code or architectural impact).

**Status:** Open, accepted — recorded, not reconciled.

### Root cause

Two independent status-tracking systems currently coexist in this
repository: the `docs/phases/phase-2/` Phase-N/Sprint-N numbering used for
the persistence work (this document's own track), and an older EPIC/Module
Sprint-numbering track in `docs/architecture/ARCHITECTURE_STATUS.md` and
`services/README.md` (e.g. "Sprint 14 — EPIC-13 Universal Connector
Framework"), which has no awareness that Phase 2 persistence work occurred.

### Why it is currently accepted

Reconciling or renumbering either tracking system is a larger documentation
exercise than any single phase's closure, and doing it hastily risks
silently overwriting history in one track while "fixing" the other. It is
being recorded as debt so it is not lost, not resolved unilaterally here.

### Recommended future solution

A dedicated documentation task should decide which system is authoritative
going forward (or how the two map onto each other) and update both
consistently in one pass, rather than each phase closure patching only its
own track.

### Expected implementation phase

Unscheduled — flagged for a future dedicated documentation-governance pass.
