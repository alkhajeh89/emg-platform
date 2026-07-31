# CI Pipeline

## SRS-3 supply-chain gates

CI installs `requirements-dev.lock` and `requirements-production.lock` with
hash verification. Change the corresponding input file, regenerate with
`pip-compile --generate-hashes --allow-unsafe --strip-extras`, and review the
complete lock diff. Never hand-edit a lock.

Every third-party GitHub Action and container is pinned to an immutable commit
or image digest. CI blocks vulnerable production dependencies, critical
container vulnerabilities, and committed secrets. It uploads JSON/SARIF
reports plus a deterministic CycloneDX SBOM.

Version tags also produce a deterministic source archive, SBOM, local in-toto
provenance statement, and GitHub build-provenance attestation. Verify the
attestation and each subject SHA-256 before deployment.

## Purpose
To execute automated quality checks on pushed code and pull requests.

## Scope
Defines the CI workflow using GitHub Actions.

## Repository Evidence
- `.github/workflows/ci.yml`

## Current Implementation
GitHub Actions workflow `CI` triggered on `push` and `pull_request` for `main` and `develop` branches.
- Jobs: `quality` and `typecheck`.
- Runner: `ubuntu-latest`.
- Environment: Python 3.10.
- Dependency Installation: `pip install -r requirements-dev.txt` and editable installs via `tools/scripts/install-libs.sh` and `tools/scripts/install-services.sh`.
- Commands: `make lint`, `make test`, `pre-commit run --all-files`, `make typecheck`.
- No artifacts are produced or published.

## Constraints
TBD — requires engineering or architecture decision

## Dependencies
- GitHub Actions
- Python 3.10
- Makefile

## Security Considerations
TBD — requires engineering or architecture decision

## Operational Considerations
Pipeline execution is triggered by push and pull requests on `main` and `develop` branches.

## Open Questions
TBD — requires engineering or architecture decision

## Cross References
- [Build Pipeline](BUILD_PIPELINE.md)

## Future Considerations
TBD — requires engineering or architecture decision
