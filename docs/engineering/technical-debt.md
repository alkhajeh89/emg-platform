# Engineering Technical-Debt Register

Deliberate, tracked debt for the EMG platform. Each item records root cause, why
it is currently accepted, the recommended resolution, and the phase in which it
is expected to be paid down. Items here are *conscious engineering decisions*,
not unknown defects. (Repository-wide `grep` finds no `TODO`/`FIXME`/`HACK`
markers in `src`; debt is documented, not scattered.)

| ID | Title | Severity | Status | Target phase |
|----|-------|----------|--------|--------------|
| TD-001 | `mypy --strict` not enforced in `make lint` / CI | Low | Open (accepted) | Phase 1 (Platform Foundation), or earlier DX task before Phase 2 |

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
