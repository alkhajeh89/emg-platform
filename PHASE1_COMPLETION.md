# Phase 1 — Completion Report (Platform Foundation)

**Phase:** 1 — Platform Foundation
**Date:** 2026-07-19
**Branch:** `develop` (base: Phase 0 `a118e3f`)
**Status:** Complete; awaiting review before Phase 2.
**Governing baseline:** `EMG_PRODUCT_ARCHITECTURE_FREEZE.md` (v1.0-FROZEN). Every deliverable cites a frozen section.
**Scope rule honored:** purely additive — one new package plus new tooling/docs; **zero** edits to any existing library or service source.

---

## Completed work

1. **`libs/python/emg-platform-core`** — the storage-independence seam (Freeze §9, §11, §12, §32):
   - **Ports** (`ports/graph_store.py`): `GraphStore` + `GraphTransaction` `Protocol`s and the `WriteReceipt` value type — the storage-independent contract (Freeze §11, §32).
   - **Identity** (`identity/`): `TenantId` (multi-tenancy spine, Freeze §12), `PrincipalRef` + `PrincipalKind` (mutation provenance, Freeze §9), and `SYSTEM_TENANT` / `SYSTEM_PRINCIPAL`.
   - **Adapter** (`adapters/in_memory.py`): `InMemoryGraphStore` — deterministic, tenant-scoped, lock-guarded, over `emg-memory-graph` (Freeze §32 "in-memory adapter for tests").
   - **Errors** (`errors.py`): `PlatformCoreError` / `TransactionStateError` deriving from `emg_errors.EMGError`, matching repo convention.
2. **TD-001 resolved** — `tools/scripts/run-typecheck.sh` (per-package `mypy --strict`), `make typecheck` target, and a **separate** CI `typecheck` job. `make lint` unchanged.
3. **Documentation** — `docs/engineering/platform-foundation-architecture.md`, `docs/engineering/storage-ports.md` (contract reference), both freeze-cited; plus `PHASE1_PLAN.md` (the executed plan).
4. **Close-out** — technical-debt register updated (TD-001 → RESOLVED), Architecture Review updated (Phase 1 marked complete; persistence re-sequenced to Phase 2).

## Remaining work (deferred, not Phase 1 scope)

- **Phase 2 — Persistence Binding:** Neo4j + Postgres adapters behind the Phase 1 `GraphStore` port; migrations; transactional write path; the `tenant_id`/`principal` retrofit onto persisted domain models (Freeze §9, §12, §30, §31).
- Top-level `platform/` directory grouping (Freeze §27, *suggested* layout) — deferrable; the foundation currently lives under `libs/python/` to preserve existing bootstrap/CI/pytest wiring with zero behaviour change.

## Technical debt

| ID | Title | Severity | Status |
|----|-------|----------|--------|
| TD-001 | `mypy --strict` not enforced in `make lint` / CI | Low | **RESOLVED (Phase 1)** — `make typecheck` per-package + CI job |

No new technical debt introduced. Full detail: `docs/engineering/technical-debt.md`.

## Review corrections (architectural-review round)

The first Phase 1 submission was returned with two contract gaps in the
transaction design; both are now fixed:

1. **Transaction atomicity.** The adapter previously released the store lock
   during the transaction body, permitting lost updates and a direct write
   landing between snapshot and commit. Fixed with the simplest correct design
   (Freeze §32): the transaction now holds the store's reentrant lock across the
   **entire** unit of work (snapshot → body → commit/abort), making transactions
   strictly serialisable with each other and with direct writes.
2. **Commit receipts + lifecycle.** `GraphTransaction` now exposes
   `txn.receipt` (a `WriteReceipt`) after a successful commit; accessing it
   before commit or after a rollback raises `TransactionStateError`. The
   transaction has explicit COMMITTED/ABORTED closure (state machine), so
   `read()`/`stage()`/`receipt` cannot be misused after the context ends —
   including on the rollback path (previously the txn was left internally open).
3. **`WriteReceipt.content_hash`** now validates a lowercase SHA-256 hex shape
   (`^[0-9a-f]{64}$`) instead of length-only.

New adversarial concurrency + lifecycle tests cover: two concurrent transactions
cannot lose an update; a direct write cannot be overwritten by a stale
transaction; exception → rollback; rolled-back and committed transactions are
closed; receipt present after commit / unavailable before commit; receipt field
correctness; and continued `runtime_checkable` Protocol conformance.

## Validation summary

All gates run in a Linux venv using the **repo-pinned** tool versions (`black==24.10.0`, `ruff 0.6.9`, `mypy 1.20.2`) to mirror Mac/CI exactly.

| Gate | Result |
|------|--------|
| `ruff check libs services` | ✅ All checks passed |
| `black --check libs services` | ✅ 316 files unchanged |
| `pytest` (full suite) | ✅ **1031 passed, 16 skipped** |
| `emg-platform-core` tests | ✅ **47 passed**, **100% coverage** (181/181 statements; target > 95%) |
| `make typecheck` (mypy --strict, per package) | ✅ passed for **18 packages** |
| `pre-commit run` (all 6 hooks) | ✅ passed |
| `setup-check.sh` | ✅ exit 0 (editable-install integrity OK, incl. new package) |
| CI workflow YAML | ✅ parses; 2 jobs (`quality`, `typecheck`) |
| GitHub Actions compatibility | ✅ jobs mirror local gates; `make lint` unchanged |

New package test categories: import surface, identity value types, port contracts (WriteReceipt hex validation + structural conformance), in-memory store (read/write, tenant isolation, determinism, transaction commit/rollback/lifecycle, receipts), **adversarial concurrency** (no lost updates, no stale overwrite), adversarial inputs (control-char/bidi/overlong-label rejection).

## Baseline comparison with Phase 0

| Metric | Phase 0 | Phase 1 | Δ |
|--------|---------|---------|---|
| Shared libraries (`libs/python/*`) | 15 | 16 | +1 (`emg-platform-core`) |
| Tests passed | 984 | 1031 | +47 (all 984 preserved) |
| Tests skipped | 16 | 16 | 0 |
| Black-checked files | 297 | 316 | +19 (new package + tests + docs) |
| Type-checked packages (mypy --strict, enforced) | 0 (not gated) | 18 | +18 (TD-001 closed) |
| CI jobs | 1 (`quality`) | 2 (`quality`, `typecheck`) | +1 |
| Existing source files modified | — | 0 | 0 (additive only) |
| Open technical-debt items | 1 (TD-001) | 0 | −1 |

**Zero regressions:** every Phase 0 test still passes; no existing API, behaviour, or gate changed.

## Risks

- **Low — CI time.** A second job (`typecheck`) and one extra package add modest time; both jobs install the full toolchain without pip caching (as in Phase 0). Add caching if CI duration becomes a concern.
- **Low — foundation-vs-persistence coupling.** The `GraphStore` port is designed before the Neo4j adapter exists; if Phase 2 reveals a needed contract change, it is an additive port evolution (the in-memory adapter and its tests are the executable contract Neo4j will be held to). Mitigated by keeping the port minimal and domain-only.
- **None affecting correctness:** the full suite is unchanged at 984 preserved + 40 new; the new package is 100% covered and type-clean.

---

**Next:** hold for review. Do not begin Phase 2 (Persistence Binding) until Phase 1 is approved.
