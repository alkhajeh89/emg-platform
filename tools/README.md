# /tools — Internal Developer Tooling

Per Engineering Master Plan §3: "internal developer tooling: scaffolding
generators, local environment scripts, and CI helper scripts." Pipeline
definitions here are versioned like any other shared library (Engineering
Master Plan §6).

| Path | Purpose |
| --- | --- |
| `scripts/new-service.sh` | Scaffolding generator for a new backend service directory under `/services` |
| `scripts/configure-branch-protection.sh` | Applies `.github/settings.yml`'s branch protection ruleset via GitHub CLI (fallback if the Settings App is not installed) |
| `scripts/bootstrap.sh` | One-command local environment setup, invoked by `make bootstrap` |
| `scripts/run-lint.sh` / `run-fmt.sh` / `run-tests.sh` | CI/local helper scripts invoked by `.github/workflows/ci.yml` and the `Makefile` |
| `scripts/install-libs.sh` / `build-libs.sh` | Installs/builds all `/libs` Python packages in editable/build mode |
| `scripts/dependency-audit.sh` | SCA scan helper (pip-audit) used by the `security-scan` CI job |
| `scripts/run-integration-tests.sh` | Integration test entry point (skeleton this sprint; services register suites here as they land) |
| `ci-templates/service-ci-template.yml` | Reusable workflow template a new service's own CI wires into, per FEAT-01-4 |
