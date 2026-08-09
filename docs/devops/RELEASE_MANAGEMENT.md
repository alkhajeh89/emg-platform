# Release Management

## Purpose

Describe the repository-implemented ADR-040 runtime image release path and the
operational gates that remain outside the repository.

## Scope

The governed runtime inventory contains Identity, Audit, Audit Projector,
Knowledge Graph, Studio BFF, and the Keycloak provisioner. Source archives are
not deployment identity; production deploys immutable OCI digests.

## Implemented Repository Contract

`.github/workflows/runtime-image-release.yml` runs only for `v*` tags. It:

1. derives the governed inventory from `docker/dependencies.yaml`;
2. builds every image once;
3. blocks publication on the Trivy critical-severity gate;
4. publishes the scanned build to GHCR;
5. signs and verifies the immutable digest with keyless Cosign and GitHub
   Actions OIDC;
6. creates GitHub runtime-image provenance and retains a CycloneDX SBOM;
7. generates a complete `release-images.json`, placeholder-free
   `production-resolved.yaml`, and rollback digest set.

`tools/ci/runtime_image_release.py` fails finalization on missing/duplicate
records, mutable or synthetic references, modified SBOMs, incomplete image
coverage, digest/commit mismatch, or unresolved `registry.invalid` fixtures.

## Promotion Controls

- Privileged publication uses the protected `production-release` environment.
- Arbitrary branches and pull requests have no package, signing, or attestation
  authority.
- Build, scan, publication, signing, provenance, release manifest, deployment
  bundle, and rollback evidence describe the same immutable build.
- Failed or indeterminate mandatory stages halt release finalization.

## Operational Prerequisites

- Configure reviewers/protection for `production-release`.
- Grant the repository package and OIDC permissions required by ADR-040.
- Execute and witness the first live GHCR/Cosign/OIDC release.
- Set artifact/package retention policies consistent with governance.
- Execute ADR-041 target-environment provisioning before workload rollout.

Repository implementation is release-candidate capable; it is not proof that a
production release has been published or deployed.

## Cross References

- `docs/architecture/EMG_ADR-040_RUNTIME_IMAGE_SUPPLY_CHAIN.md`
- `docs/architecture/EMG_ADR-041_PRODUCTION_PROVISIONING_OWNERSHIP_AND_BOOTSTRAP_CONTRACT.md`
- `docs/devops/PRODUCTION_DEPLOYMENT_GUIDE.md`
- `docs/devops/ROLLBACK_STRATEGY.md`
