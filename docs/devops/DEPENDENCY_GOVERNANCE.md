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
`push` and `pull_request`, installing `pyyaml` + `tomli` and then running, in
order:
1. `tools/ci/check_dependency_manifest.py` — for every `type: service` entry,
   confirms its Dockerfile exists and contains a `COPY libs/python/{dependency}`
   line for each declared dependency. Libraries are skipped (they have no
   Dockerfile). Exits 1 on any missing entry.
2. `tools/ci/check_dependency_drift.py` — for every entry (service or
   library), parses its `pyproject.toml`, extracts the `emg-*` dependencies
   actually declared in code, and compares that set against the manifest's
   `dependencies` list. Reports any dependency present in code but missing
   from the manifest, and exits 1 if any are found. Supports Python 3.10+ via
   a `tomllib`-with-`tomli`-fallback import.

This job previously existed in triplicate — the same two scripts were also
wired into two standalone workflow files
(`.github/workflows/dependency-check.yml` and
`.github/workflows/dependency-validation.yml`) with overlapping branch
triggers and no behavioral difference from the `ci.yml` job. Both were
removed; `ci.yml`'s `dependency-validation` job is the single enforcement
point.

## Developer Workflow
When adding a new internal `emg-*` dependency to any package:
1. Add it to the package's `pyproject.toml`.
2. Add it to that package's `dependencies:` list in `docker/dependencies.yaml`
   (under `services:`, using the existing `type` for that package).
3. If the package is a service, add the matching `COPY` and `pip install`
   lines to its Dockerfile, following the existing pattern above.
4. Run the two checks locally before opening a PR:
   ```
   python tools/ci/check_dependency_manifest.py
   python tools/ci/check_dependency_drift.py
   ```
5. When adding a brand-new service or library, add its entry directly under
   `services:` in `docker/dependencies.yaml` — never as a top-level sibling
   key — so it is covered by both scripts from the start.

## Constraints
- `check_dependency_drift.py` currently only detects dependencies present in
  code but missing from the manifest (`actual - declared`). It does not flag
  the reverse case — a dependency declared in the manifest that is no longer
  used in code (stale/orphaned entries).
- Drift detection is only as accurate as each package's `pyproject.toml`. A
  package with an empty or unpopulated `pyproject.toml`
  (`libs/python/emg-entity-resolution/pyproject.toml` is currently a 0-byte
  file) will report as "aligned" with zero dependencies rather than flagging
  that its manifest entry may be incomplete.

## Dependencies
- PyYAML (manifest parsing)
- `tomllib` (Python 3.11+) / `tomli` (Python 3.10 fallback)
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
Both validation scripts run in seconds with no external services required
(no database, no Docker daemon), so they run early in CI and give fast
feedback on a manifest/Dockerfile/pyproject mismatch before the slower
build/test jobs run.

## Open Questions
- Should `check_dependency_drift.py` also detect stale manifest entries
  (declared but unused)? Not currently required by any consumer, but noted
  above as a known gap.
- Should `libs/python/emg-entity-resolution/pyproject.toml` be populated with
  its real dependencies? Currently empty; out of scope for dependency
  governance itself, but drift detection cannot do anything useful for this
  package until it is.

## Cross References
- [CI Pipeline](CI_PIPELINE.md)
- [Build Pipeline](BUILD_PIPELINE.md)

## Future Considerations
- Extend `check_dependency_drift.py` to flag manifest entries with no
  corresponding code usage (bidirectional drift detection).
- Consider a `make check-dependencies` target so both scripts run as one
  local command instead of two.
