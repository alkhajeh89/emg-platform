# Phase 1 — Platform Foundation — Execution Plan

**Phase:** 1 — Platform Foundation (scope limited to foundation only)
**Date:** 2026-07-19
**Base branch:** `develop` (Phase 0 merged: `110fcc8`, `a118e3f`)
**Governing baseline:** `EMG_PRODUCT_ARCHITECTURE_FREEZE.md` (v1.0-FROZEN). Every decision below cites a frozen section.
**Status:** PLAN — presented for the record; internally validated against the freeze (see §Internal Freeze-Conformance Validation). Implementation is purely additive.

---

## Scope decision (and a phase re-sequencing to flag)

The Architecture Review's roadmap labelled Phase 1 "Persistence Binding (Neo4j + Postgres)." Under the explicit Phase 1 constraints now in force — *Platform Foundation only; preserve all tests; preserve current behaviour; no breaking API changes; no shortcut implementations* — binding real databases cannot be done this phase: it requires new infrastructure (running Neo4j/Postgres), schema migrations, and would pressure the frozen domain models toward change. That is genuinely Phase 2 work.

**Decision:** Phase 1 delivers the *foundation those bindings plug into* — the storage **ports** and an **in-memory adapter** — plus the cross-cutting identity **value types** the freeze mandates, and pays down **TD-001**. Actual Neo4j/Postgres adapters, migrations, and the retrofit of `tenant_id`/`principal` onto every domain model move to **Phase 2 — Persistence Binding**. This re-sequencing changes *ordering within the roadmap only*; it does not alter any frozen boundary. Grounded directly in **Freeze §32**: *"Introduce a `GraphStore` port … with a Neo4j adapter for durability and an in-memory adapter for tests."* Phase 1 builds the port + in-memory adapter (the seam); Phase 2 adds the Neo4j adapter (the durability).

This decision is surfaced explicitly so it can be rejected before implementation. If full persistence binding was intended for Phase 1, stop and redirect.

---

## 1. Objectives

1. Establish the **storage-independence seam** the platform is built on: a `GraphStore` port (Protocol) with a transaction boundary, so every future service depends on an interface, never a concrete database. *(Freeze §11 "one writer per store … storage-independent"; §32.)*
2. Provide a **deterministic in-memory adapter** implementing that port over the existing `emg-memory-graph`, proving the seam end-to-end with zero infrastructure. *(Freeze §32.)*
3. Define the **cross-cutting identity value types** — `TenantId` and `PrincipalRef` — as reusable, frozen-pydantic types, ready for Phase 2 to thread through persistence. *(Freeze §9 additive `tenant_id`/`principal`; §12 "every datum carries `tenant_id`".)*
4. Pay down **TD-001**: add a per-package `make typecheck` gate and wire it into CI as a separate job, without changing `make lint` behaviour. *(technical-debt.md; targeted at Phase 1.)*
5. Do all of the above **purely additively** — no edits to any existing library or service source — so all 984 tests and all current behaviour are preserved by construction.

## 2. Deliverables

**D1 — New shared library `libs/python/emg-platform-core`** (pure Python, deterministic, no I/O, no heavy deps beyond pydantic + the existing `emg-*` siblings). Contents:
- `ports/graph_store.py` — `GraphStore` and `GraphTransaction` Protocols (`runtime_checkable`), the storage seam. Read/write/commit contract expressed in domain terms (MemoryGraph in/out), no DB concepts. *(Freeze §11, §32.)*
- `identity/tenant.py` — `TenantId` frozen value type (validated, deterministic). *(Freeze §9, §12.)*
- `identity/principal.py` — `PrincipalRef` frozen value type (who/what asserted a change). *(Freeze §9 "principal provenance on every mutation".)*
- `adapters/in_memory.py` — `InMemoryGraphStore` implementing `GraphStore` over `emg-memory-graph`, deterministic, tenant-scoped, test/dev only. *(Freeze §32.)*
- `errors.py` — typed errors following the repo's existing `SafeLabel`/error conventions.
- `__init__.py` — curated `__all__`, `__version__ = "0.1.0"`.

**D2 — Comprehensive tests** for `emg-platform-core` (unit + adapter-contract + determinism + tenant-scoping + adversarial), matching repo standards, targeting >95% coverage.

**D3 — Documentation:** `docs/engineering/platform-foundation-architecture.md` and `docs/engineering/storage-ports.md`, each citing the freeze sections they implement, with a port/adapter diagram.

**D4 — TD-001 paydown:** `tools/scripts/run-typecheck.sh` (per-package `mypy <pkg>/src` loop, using the pinned mypy), `make typecheck` target, and a **separate** CI job in `.github/workflows/ci.yml`. `make lint` is left unchanged.

**D5 — Phase close-out docs:** `PHASE1_COMPLETION.md`, technical-debt update (close/track TD-001), Architecture Review update (mark Phase 1 done, record the re-sequencing), validation summary, and a baseline comparison vs Phase 0.

## 3. Files expected to change

**New (additive):**
- `libs/python/emg-platform-core/pyproject.toml`, `README.md`, `src/emg_platform_core/{__init__,errors}.py`, `src/emg_platform_core/ports/{__init__,graph_store}.py`, `src/emg_platform_core/identity/{__init__,tenant,principal}.py`, `src/emg_platform_core/adapters/{__init__,in_memory}.py`, `py.typed`
- `libs/python/emg-platform-core/tests/*` (conftest + test modules)
- `docs/engineering/platform-foundation-architecture.md`, `docs/engineering/storage-ports.md`
- `tools/scripts/run-typecheck.sh`
- `PHASE1_COMPLETION.md`

**Modified (additive only, no behaviour change to existing gates):**
- `Makefile` — add `typecheck` target (new target; existing targets untouched).
- `.github/workflows/ci.yml` — add a separate `typecheck` job (existing `quality` job untouched).
- `docs/engineering/technical-debt.md` — update TD-001 status.
- `EMG_ARCHITECTURE_REVIEW.md` — mark Phase 1 complete; record re-sequencing.

**Explicitly NOT changed:** any existing `libs/python/*/src`, `services/*/src`, the frozen domain models, `run-lint.sh`, `run-tests.sh`, `bootstrap.sh`, or any test in an existing package. The new package is picked up automatically by `install-libs.sh` (globs `libs/python/*`) and pytest (`testpaths=[libs,services]`) with no config change.

## 4. Migration strategy

No data or schema migration in Phase 1 (no persistence yet). The only "migration" is additive package introduction: `install-libs.sh` already globs `libs/python/*`, so the new package installs editable automatically on the next `make bootstrap`; pytest discovers its tests automatically. No developer action required beyond re-running bootstrap. The `tenant_id`/`principal` *retrofit* onto domain models is deliberately deferred to Phase 2, where it will ship with the persistence layer and a real migration plan.

## 5. Backward compatibility

100% preserved, by construction: Phase 1 adds a new package and new tooling and edits **zero** existing source. No public API of any existing package changes; no signature, field, or default is altered. `make lint`, `make test`, `make bootstrap`, and pre-commit behave exactly as before. New `make typecheck` is additive. *(Satisfies "no breaking API changes" and "preserve current behaviour".)*

## 6. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| New package's dep on `emg-memory-graph` creates a cycle | Low | `emg-platform-core` depends on `emg-memory-graph`, never the reverse; verified with an import-direction test. |
| In-memory adapter accidentally introduces nondeterminism | Low | Deterministic-only constructs; a determinism test asserts identical `content_hash()` across repeated operations. |
| `make typecheck` surfaces a latent type error and "fails CI" | Low | Per-package mypy is already clean (verified in Phase 0); the gate is added as a *separate* job so it never changes `make lint`, and any finding is a true signal, not a regression. |
| Scope creep toward real persistence | Medium | Hard scope line: ports + in-memory adapter only; Neo4j/Postgres explicitly Phase 2. Stop-and-report if any task needs a DB. |
| tenant/principal types drift from Phase 2 model retrofit | Low | Types are defined minimally and immutably now; Phase 2 consumes them rather than redefining. |

## 7. Validation strategy

After **every logical milestone** (per the phase requirements): `ruff check`, `black --check`, `pytest` (full suite — must stay ≥ 984 passed / 16 skipped, plus the new package's tests), the new per-package `mypy` (`make typecheck`), `setup-check.sh`, and GitHub Actions compatibility (YAML parse + step mirroring). Validation runs in a Linux venv using the **repo-pinned** tool versions (`black==24.10.0`, `ruff 0.6.9`, `mypy 1.x`) to mirror Mac/CI exactly. Coverage on the new package is measured and must exceed 95%.

## 8. Rollback strategy

Trivial and low-blast-radius because everything is additive:
- Pre-merge: discard the branch / `git restore`; nothing in the existing tree was touched.
- Post-commit (if needed): a single `git revert` of the Phase 1 commit(s) removes the new package and the `Makefile`/CI additions, restoring the exact Phase 0 state. No data, no schema, no consumer depends on the new package yet, so revert is safe and complete.

## 9. Expected CI impact

- **New separate `typecheck` job** in `ci.yml` running `make typecheck` (per-package mypy). Adds one parallel job; does not slow or alter the existing `quality` job.
- The existing `quality` job now also builds/tests one additional small pure-Python package (`emg-platform-core`) — negligible added time (no heavy deps).
- No change to triggers, permissions, or the lint/test/pre-commit steps.
- First push will run both jobs; both expected green.

---

## Internal Freeze-Conformance Validation

| Phase 1 element | Frozen basis | Conforms? |
|---|---|---|
| `GraphStore` / `GraphTransaction` ports | §11 (one-writer, storage-independent), §32 (GraphStore port) | ✅ implements the mandated seam |
| `InMemoryGraphStore` adapter | §32 ("in-memory adapter for tests") | ✅ exactly as specified |
| `TenantId` value type | §9, §12 ("every datum carries tenant_id") | ✅ defines the type; retrofit deferred to Phase 2 |
| `PrincipalRef` value type | §9 ("principal provenance on every mutation") | ✅ defines the type |
| No I/O / no ML in the new core | §9 ("domain core performs no I/O and no ML") | ✅ pure, deterministic |
| New lib under `libs/python/` (not top-level `platform/`) | §27 (layout is *suggested*, not frozen); §11/§32 (the *seam* is frozen) | ✅ frozen substance honored; layout kept tooling-compatible, top-level `platform/` grouping deferrable |
| Deferring Neo4j/Postgres to Phase 2 | §32 (port+in-memory now, Neo4j "for durability" next) | ✅ ordering only; no boundary changed |
| `make typecheck` (TD-001) | technical-debt.md (target Phase 1) | ✅ pays down as planned |

**No element violates the freeze.** One conscious deviation is documented and justified: the new code lives under `libs/python/emg-platform-core` rather than a new top-level `platform/` directory, because §27's folder layout is *suggested* (not part of the frozen product/domain/boundary set), and keeping it under `libs/python/` preserves the existing bootstrap/CI/pytest wiring with zero behaviour change. The frozen *substance* (ports, storage independence, in-memory adapter, tenant/principal dimensions) is fully honored.

**Stop condition armed:** if any implementation step would require touching a frozen domain model, introducing a real database, or changing an existing public API, implementation halts and reports rather than proceeding.

---

## Milestones (each validated before the next)

- **M1** — Package scaffold + `TenantId`/`PrincipalRef` + errors + `GraphStore`/`GraphTransaction` ports + `__init__`. Validate.
- **M2** — `InMemoryGraphStore` adapter + full test suite (>95% coverage). Validate.
- **M3** — TD-001: `run-typecheck.sh` + `make typecheck` + CI job. Validate (incl. GHA parse).
- **M4** — Docs (platform-foundation-architecture, storage-ports) + close-out (`PHASE1_COMPLETION.md`, TD + Review updates, baseline comparison). Validate, then present for review. **Stop before Phase 2.**
