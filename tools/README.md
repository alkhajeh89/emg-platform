# /tools — Internal Developer Tooling

Per Engineering Master Plan §3: "internal developer tooling: scaffolding
generators, local environment scripts, and CI helper scripts." Pipeline
definitions here are versioned like any other shared library (Engineering
Master Plan §6).

| Path | Purpose |
| --- | --- |
| `scripts/_venv.sh` | Sourced helper: resolves repo root + `.venv` interpreter paths and the supported-Python check used by the other scripts (not executed directly) |
| `scripts/bootstrap.sh` | One-command local environment setup, invoked by `make bootstrap` (creates `.venv`, installs the dev toolchain + all editable packages, git hooks, `.env`, optional docker infra) |
| `scripts/setup-check.sh` | Non-destructive diagnostic of the local environment, invoked by `make setup-check` |
| `scripts/install-libs.sh` | Installs all `libs/python/*` packages editable in a single resolver pass so proprietary sibling deps resolve locally |
| `scripts/install-services.sh` | Installs all installable `services/*` packages (those with a `pyproject.toml`) editable with dev extras |
| `scripts/build-libs.sh` | Builds all `libs/python/*` packages (sdist + wheel) |
| `scripts/run-lint.sh` / `run-fmt.sh` / `run-tests.sh` | Lint / format / test helpers invoked by the `Makefile`; all use the `.venv` tools and fail with a clear message if `make bootstrap` has not been run |
| `scripts/new-service.sh` | Scaffolding generator for a new backend service directory under `/services` |
| `scripts/dependency-audit.sh` | SCA scan helper (`pip-audit`) |
| `scripts/run-integration-tests.sh` | Integration test entry point (skeleton; services register suites here as they land) |
| `scripts/configure-branch-protection.sh` | Applies branch-protection rules via the GitHub CLI (`make branch-protection`) |
| `ci-templates/service-ci-template.yml` | Reusable workflow template a new service's own CI wires into, per FEAT-01-4 |

> **CI note.** A repository-level CI workflow (`.github/workflows/ci.yml`) and
> repo settings (`.github/settings.yml`) are referenced by `CONTRIBUTING.md`/
> `README.md` as the intended pipeline but are **not present in the repository
> yet**. The lint/test/build/audit scripts above are written to be the single
> source of truth those workflows will call once added, and are fully usable
> locally today via the `Makefile`.
