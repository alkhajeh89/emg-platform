# Rollback Strategy

## Purpose

Restore a previously approved complete runtime image set without rebuilding,
retagging, or mixing image versions.

## Implemented Repository Contract

ADR-040 finalization retains `release-images.json` under the release evidence
and rollback directories. It maps every governed runtime component to the
immutable GHCR digest, source commit, verified signing identity, provenance,
and SBOM from one release.

Rollback uses the retained complete image set to generate or recover a resolved
production bundle. It never:

- rebuilds an old release;
- deploys a mutable tag;
- mixes selected images from different releases;
- edits a synthetic `registry.invalid` fixture into a deployable reference; or
- bypasses signature, provenance, or completeness verification.

## Procedure

1. Select an approved retained release evidence artifact.
2. Verify every digest's Cosign identity and GitHub provenance.
3. Verify the complete governed image set and retained SBOM checksums.
4. Use the corresponding resolved bundle or deterministically resolve the
   source template from that manifest.
5. Apply the bundle through the normal environment promotion controls.
6. Verify migration compatibility, readiness, and authoritative data integrity.
7. Record the rollback release, operator approval, reason, and outcome.

Database rollback is not performed by reverting forward-only migrations. When
data recovery is required, use ADR-039 restore/PITR procedures and verify Audit
and evidence chains after recovery.

## Operational Prerequisites

- Retain release evidence, OCI digests, signatures, provenance, and SBOMs for
  the governed rollback window.
- Ensure the target registry still retains every referenced digest.
- Maintain operator/CD approval and production access controls.
- Rehearse both image rollback and data recovery in the target environment.

## Cross References

- `docs/architecture/EMG_ADR-039_BACKUP_PITR_AND_RECOVERY_GOVERNANCE.md`
- `docs/architecture/EMG_ADR-040_RUNTIME_IMAGE_SUPPLY_CHAIN.md`
- `docs/devops/RELEASE_MANAGEMENT.md`
