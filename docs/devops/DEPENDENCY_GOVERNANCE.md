# Dependency Governance

## Purpose
To keep Docker image dependencies for every service and library in the monorepo
in sync with a single declared source of truth, and to fail CI automatically
when a package's real dependencies (as declared in its own `pyproject.toml`)
drift out of alignment with what is built into its Docker image or recorded in
the manifest.

## Scope
Defines the dependency manifest schema, the two validation scripts that
enforce it, the CI job that runs them, the existing Dockerfile pattern all
service images follow, and the workflow a developer follows when adding or
changing an internal `emg-*` dependency.

## Repository Evidence
- `docker/dependencies.yaml`
- `tools/ci/check_dependency_manifest.py`
- `tools/ci/check_dependency_drift.py`
- `tools/ci/check_implicit_dependencies.py`
- `tools/ci/tests/test_check_implicit_dependencies.py`
- `.github/workflows/ci.yml` (`dependency-validation` job)
- `services/identity/Dockerfile`
- `services/audit/Dockerfile`

## Ownership Model
`docker/dependencies.yaml` is the single source of truth for which internal
`emg-*` packages each service or library depends on. It is a flat mapping
under one top-level `services:` key; a `type` field (`service` or `library`)
distinguishes the two, rather than splitting them into separate top-level
sections. Both validation scripts iterate this one mapping, so every entry —
service or library — is checked by the same code path. There is deliberately
no second, parallel `libs:` section: a prior manifest edit added a library
entry (`entity-resolution`) as a top-level sibling key instead of nesting it
under `services:`, which silently excluded it from both scripts (neither
iterates anything outside `services`). That entry has since been corrected;
new entries must always be added under `services:`, never alongside it.

Each entry carries:
- `type` — `service` (has a Dockerfile, deployed independently) or `library`
  (installed into other packages, no Dockerfile of its own).
- `path` — location of the package relative to the repo root.
- `dockerfile` — required for `type: service`, omitted for `type: library`.
- `dependencies` — the list of internal `emg-*` packages this component
  depends on.

## Manifest Workflow
1. A package's real dependencies live in its own `pyproject.toml`
   (`[project.dependencies]`), same as any Python package.
2. `docker/dependencies.yaml` restates the internal-`emg-*` subset of those
   dependencies for two purposes: verifying a service's Dockerfile actually
   `COPY`s and installs every declared dependency, and detecting drift between
   what the code imports and what the manifest lists.
3. When you add a new internal dependency to a package, update both files in
   the same change: the package's `pyproject.toml`, and its entry in
   `docker/dependencies.yaml`. If the package is a `type: service`, also add
   the corresponding `COPY` + `pip install` lines to its Dockerfile.

## Docker Dependency Rules
Both existing service Dockerfiles (`services/identity/Dockerfile`,
`services/audit/Dockerfile`) already follow one consistent, multi-stage
pattern. This is the reusable standard — new services should copy it rather
than invent a new shape:

1. **Explicit `COPY` per dependency** — each internal library is copied into
   the build stage individually (`COPY libs/python/emg-x /build/libs/python/emg-x`),
   never with a wildcard. This keeps the manifest's `dependencies` list and the
   Dockerfile's `COPY` lines directly comparable, which is exactly what
   `check_dependency_manifest.py` checks (it greps the rendered Dockerfile
   content for `libs/python/{dependency}` for every entry in the manifest).
2. **Install in dependency order** — `pip install` lists the same libraries in
   the same order as the `COPY` lines, followed by the service package itself.
3. **Fail early on a missing dependency** — because each library is `COPY`'d
   and installed explicitly (not resolved from an index), a dependency missing
   from the Dockerfile fails the build immediately rather than surfacing later
   as a runtime `ImportError`. CI catches the equivalent gap even earlier, via
   `check_dependency_manifest.py`, before an image is even built.
4. **Match `pyproject.toml` exactly** — the set of libraries copied and
   installed must equal the package's declared internal dependencies; neither
   more (unused `COPY`s bloat the image and hide real coupling) nor fewer
   (missing at runtime).
5. **Multi-stage build** — a `base` stage compiles and installs everything; a
   slim `runtime` stage copies only `site-packages` and installed console
   scripts out of it, runs as a non-root user, and defines a `HEALTHCHECK`.

## CI Enforcement
The `dependency-validation` job in `.github/workflows/ci.yml` runs on every
`push` and `pull_request`, installing `pyyaml` + `tomli` + `pytest` and then
running, in order:
1. `tools/ci/check_dependency_manifest.py` — for every `type: service` entry,
   confirms its Dockerfile exists and contains a `COPY libs/python/{dependency}`
   line for each declared dependency. Libraries are skipped (they have no
   Dockerfile). Exits 1 on any missing entry.
2. `tools/ci/check_dependency_drift.py` — for every entry (service or
   library), parses its `pyproject.toml`, extracts the `emg-*` dependencies
   actually declared in code, and compares that set against the manifest's
   `dependencies` list. Reports any dependency present in `pyproject.toml`
   but missing from the manifest, and exits 1 if any are found. Supports
   Python 3.10+ via a `tomllib`-with-`tomli`-fallback import.
3. `pytest tools/ci/tests/ -v` — unit tests for the checker described below,
   run against synthetic fixtures. This directory is deliberately outside
   the root `pyproject.toml`'s `[tool.pytest.ini_options] testpaths` (which
   scopes `make test` to `libs` and `services` only), so it is invoked here
   with an explicit path rather than relying on `make test` to discover it.
4. `tools/ci/check_implicit_dependencies.py` — parses every `.py` file under
   each manifest component's `src/` with Python's `ast` module and compares
   the `emg-*` packages actually imported by the code against that
   component's own `pyproject.toml` dependencies. This is a different
   direction of comparison than script 2: `check_dependency_drift.py`
   compares `pyproject.toml` against the manifest; this script compares real
   source imports against `pyproject.toml` itself. It is what would have
   caught `emg-persistence`'s undeclared `emg-memory-graph` import (see
   `EMG_ARCHITECTURE_DECISION_REGISTER.md`, OBS-A-001) before it was found
   manually during an architecture review. Imports inside `if TYPE_CHECKING:`
   blocks are reported separately (informational, does not fail the build) —
   see "Implicit Dependency Detection" below.

This job previously existed in triplicate — the same two scripts were also
wired into two standalone workflow files
(`.github/workflows/dependency-check.yml` and
`.github/workflows/dependency-validation.yml`) with overlapping branch
triggers and no behavioral difference from the `ci.yml` job. Both were
removed; `ci.yml`'s `dependency-validation` job is the single enforcement
point.

## Implicit Dependency Detection
`tools/ci/check_implicit_dependencies.py` (ECP-2) closes a gap that neither
of the two original scripts covers: both of them only ever compare two
*declared* lists against each other (`pyproject.toml` vs. the manifest).
Neither reads a single line of actual source code, so a package that imports
another `emg-*` package without declaring it anywhere would pass both checks
silently — which is exactly what happened with `emg-persistence` and
`emg-memory-graph` before it was manually found and fixed (ECP-1).

How it works:
- Walks the full AST of every `.py` file under a component's `src/`
  (`ast.parse` + a full node walk, not a top-level-only scan), so a deferred
  import inside a function body — a real, existing pattern in this repo,
  e.g. `emg_persistence/neo4j/lazy.py` — is still caught.
- Resolves each imported top-level module name to its dash-cased `emg-*`
  package name (`emg_common_types` → `emg-common-types`); anything not
  starting with `emg_` (third-party imports) is ignored.
- Excludes self-imports and relative (`from .x import y`) intra-package
  imports.
- Distinguishes imports inside `if TYPE_CHECKING:` blocks from ordinary
  runtime imports. A runtime import of an undeclared `emg-*` package fails
  the build (`❌`). A `TYPE_CHECKING`-only import of an undeclared package is
  reported as informational (`ℹ️`) rather than failing, since it doesn't
  affect what gets installed at runtime — but if the same package is *also*
  imported at runtime elsewhere in the same component, it is still treated
  as a hard failure. As of this writing, no package in this repository has a
  `TYPE_CHECKING`-guarded cross-package `emg-*` import (the existing
  `TYPE_CHECKING` usage in `emg-persistence`, `emg-audit-pipeline`,
  `emg-knowledge-lifecycle`, and `emg-telemetry` guards either third-party or
  same-package relative imports), so this distinction is currently latent —
  documented for when it first applies, not retrofitted to a real case.

Known, deliberate limitations (v1 scope):
- No support for dynamic imports (`importlib.import_module("emg_x")` with a
  computed argument). No such usage exists anywhere in this repository today.
- No optional-dependency (`try: import emg_x / except ImportError:`)
  handling. No such pattern exists anywhere in this repository today. If one
  is introduced later, it should be treated as a distinct, explicitly-allowed
  category rather than retrofitted speculatively now.
- Like `check_dependency_drift.py`, this script has no unit tests of its own
  prior to ECP-2 — `tools/ci/tests/test_check_implicit_dependencies.py` is
  the first pytest coverage for any script in `tools/ci/`.

## Developer Workflow
When adding a new internal `emg-*` dependency to any package:
1. Add it to the package's `pyproject.toml`.
2. Add it to that package's `dependencies:` list in `docker/dependencies.yaml`
   (under `services:`, using the existing `type` for that package).
3. If the package is a service, add the matching `COPY` and `pip install`
   lines to its Dockerfile, following the existing pattern above.
4. Run the checks locally before opening a PR:
   ```
   python tools/ci/check_dependency_manifest.py
   python tools/ci/check_dependency_drift.py
   pytest tools/ci/tests/ -v
   python tools/ci/check_implicit_dependencies.py
   ```
5. When adding a brand-new service or library, add its entry directly under
   `services:` in `docker/dependencies.yaml` — never as a top-level sibling
   key — so it is covered by both scripts from the start.

## Constraints
- `check_dependency_drift.py` currently only detects dependencies present in
  `pyproject.toml` but missing from the manifest (`actual - declared`). It
  does not flag the reverse case — a dependency declared in the manifest
  that is no longer used in code (stale/orphaned manifest entries). This gap
  is distinct from what `check_implicit_dependencies.py` addresses (below)
  and remains open — see Open Questions.
- `check_implicit_dependencies.py` compares actual source imports against
  `pyproject.toml`, which closes the specific gap that let
  `emg-persistence`'s undeclared `emg-memory-graph` import go undetected.
  It does **not** address the manifest-vs-code-usage direction above: a
  package can still declare an `emg-*` dependency in its `pyproject.toml`
  and manifest entry that its code no longer actually imports, and neither
  script will flag that as stale.
- Both drift-style checks are only as accurate as each package's
  `pyproject.toml`. A package with an empty or unpopulated `pyproject.toml`
  (`libs/python/emg-entity-resolution/pyproject.toml` is currently a 0-byte
  file) will report as "aligned" with zero dependencies rather than flagging
  that its manifest entry may be incomplete — `check_implicit_dependencies.py`
  would report a real finding here only if that package's code actually
  imported something; today it does not (its `__init__.py` is empty), so it
  currently reports clean by coincidence, not because the gap is resolved.
  This reporting gap is unchanged by the bootstrap fix noted immediately
  below (it concerns CI's validation scripts, not what gets installed).
- **Repository integrity fix (repair, not a D-A-002 resolution):**
  `tools/scripts/install-libs.sh` previously globbed every
  `libs/python/*/pyproject.toml` unconditionally, so
  `emg-entity-resolution`'s 0-byte `pyproject.toml` was passed to the same
  single `pip install -e ...` invocation as the 17 real libraries — it built
  successfully (pip's default setuptools backend tolerates an empty
  `pyproject.toml` and silently produces a nameless, dependency-less
  `emg_entity_resolution-0.0.0` package), so bootstrap did not fail, but a
  non-functional, unowned scaffold was being editable-installed as if it
  were real. `install-libs.sh` now skips any package directory whose
  `pyproject.toml` is empty/whitespace-only, printing an explicit
  "unpopulated library scaffold" notice instead of silently installing it —
  mirroring how a `services/*` directory with no `pyproject.toml` at all is
  already skipped by `install-services.sh`. This is a bootstrap-hygiene fix
  only: it does not populate the package, remove it, or answer D-A-002.
- `check_implicit_dependencies.py` only detects statically-visible imports
  (module-level or nested inside function bodies/`if` blocks, anything
  `ast.walk` reaches). It does not detect dynamic imports
  (`importlib.import_module` with a computed name) or optional
  (`try/except ImportError`) imports — neither pattern exists anywhere in
  this repository today.

## Dependencies
- PyYAML (manifest parsing)
- `tomllib` (Python 3.11+) / `tomli` (Python 3.10 fallback)
- `ast` (Python standard library — implicit-dependency detection, no
  third-party parsing library)
- `pytest` (unit tests for `check_implicit_dependencies.py`)
- GitHub Actions
- Docker

## Security Considerations
Pinning exactly which internal packages are copied into an image (rather than
resolving a service's full dependency tree from an index at build time)
limits a service's build-time and runtime surface to packages explicitly
reviewed for that service, and makes an unexpected new transitive `emg-*`
dependency visible as a CI failure rather than a silent image-size or
attack-surface change.

## Operational Considerations
All three validation scripts (manifest, drift, implicit-dependency) run in
seconds with no external services required (no database, no Docker daemon),
so they run early in CI and give fast feedback on a manifest/Dockerfile/
pyproject/source mismatch before the slower build/test jobs run.
`check_implicit_dependencies.py` parses every `.py` file under `src/` for
every manifest component on each run; at the current repo size (18 libraries
+ 2 services) this remains a sub-second operation, but it is the most
expensive of the three checks and is sequenced last in the CI job for that
reason.

## Open Questions
- Should stale manifest entries (declared in `docker/dependencies.yaml` and
  `pyproject.toml` but no longer imported by any code) be detected? Not
  currently required by any consumer, and distinct from what ECP-2 added —
  noted above as a known, still-open gap.
- Should `libs/python/emg-entity-resolution/pyproject.toml` be populated with
  its real dependencies (or the package removed entirely)? Currently empty;
  out of scope for dependency governance itself, and blocked on
  `EMG_ARCHITECTURE_DECISION_REGISTER.md` D-A-002 (Entity Resolution
  Ownership, Open) — no implementation should depend on this package until
  that decision is resolved. `install-libs.sh` now skips installing it (see
  above) purely as a bootstrap-integrity repair; this is deliberately
  narrower than populating/removing it and does not pre-empt D-A-002.
- Should a package's `TYPE_CHECKING`-only reference to an undeclared `emg-*`
  package require the same fix as a runtime one, or a lighter-weight one
  (e.g. a `dev`/type-checking-only extra)? No real case exists yet to decide
  against; `check_implicit_dependencies.py` reports it informationally today
  rather than pre-deciding the policy.

## Cross References
- [CI Pipeline](CI_PIPELINE.md)
- [Build Pipeline](BUILD_PIPELINE.md)
- `EMG_ARCHITECTURE_DECISION_REGISTER.md` — OBS-A-001 (the observation that
  led to ECP-1 and ECP-2), D-A-002 (blocks populating
  `emg-entity-resolution`'s `pyproject.toml`)

## Future Considerations
- `check_implicit_dependencies.py` (ECP-2) still does not flag manifest
  entries with no corresponding code usage — that remains a distinct,
  unaddressed direction (stale/orphaned entries), noted under Open Questions.
- Consider a `make check-dependencies` target so all four checks
  (`check_dependency_manifest.py`, `check_dependency_drift.py`,
  `pytest tools/ci/tests/`, `check_implicit_dependencies.py`) run as one
  local command instead of four separate invocations.
- Consider extracting the shared manifest/pyproject-loading logic currently
  duplicated between `check_dependency_drift.py` and
  `check_implicit_dependencies.py` into a small common helper module.
  Deliberately not done as part of ECP-2 itself, to avoid touching the
  already-approved, working `check_dependency_drift.py` for an unrelated
  change.
