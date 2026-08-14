# Immutable release promotion, staging qualification, and rollback

## Governing boundary

ADR-040 governs GHCR publication, build-once images, Trivy, CycloneDX SBOMs,
keyless Cosign signatures, GitHub Artifact Attestations, immutable digest bundles,
and complete-set rollback. ADR-041 governs provisioning and migration order. This
runbook operationalizes those decisions without authorizing production deployment,
schema rollback, a new registry, or a new signing authority.

The promotion unit is the complete `release-images.json` manifest and its resolved
bundles. Individual image promotion, mutable tags, rebuilt environment images, or a
mixture of releases is forbidden.

## Release candidate creation and publication

1. Merge only a fully qualified source commit and create an approved protected `v*`
   tag. The tag commit is the release source identity.
2. The runtime-image workflow derives every service and deployment tool from
   `docker/dependencies.yaml`, including Studio, Studio BFF, Keycloak provisioner,
   and the recovery tool.
3. Each image is built once. A CRITICAL Trivy finding blocks all publication.
4. The scanned image is published to the ADR-040 GHCR path and resolved to its
   registry-confirmed digest. No later stage rebuilds it.
5. The protected `production-release` GitHub Environment approves the privileged
   publication/signing boundary. GitHub OIDC signs the digest with Cosign and GitHub
   attests the same digest. The workflow verifies issuer and workflow identity.
6. A per-image CycloneDX SBOM and verified image record are retained. Finalization
   fails unless every governed image has matching digest, source commit, workflow,
   vulnerability, SBOM, signature, and provenance evidence.

No local command in this runbook substitutes for witnessed GHCR publication, OIDC
signing, or attestation.

## Canonical release evidence

The retained artifact contains:

- `release-images.json`: exact release/tag, source repository and commit, complete
  digest set, per-image security/SBOM/signature/provenance evidence, forward-only
  migration-set fingerprint, and resolved-bundle fingerprints;
- `sboms/*.cdx.json`: one digest-bound CycloneDX SBOM per image;
- `scans/*.trivy.sarif`: the retained passing blocking-policy report per image;
- `staging-resolved.yaml` and `production-resolved.yaml`: placeholder-free immutable
  image bundles generated from the same manifest;
- `staging-qualification.json`: repository validation result. It deliberately records
  live deployment, smoke, rollback rehearsal as `PENDING` and production as `BLOCKED`;
- `rollback/release-images.json`: the same complete immutable release set, not a
  service-by-service rollback instruction.

Release artifacts are immutable after qualification. Retention duration remains an
environment governance input; evidence must not be deleted before that policy exists.

## Staging prerequisites and qualification

The `infra/environments/staging` overlay reuses the production base and namespace-
isolates it as `emg-staging`. Before execution, environment owners must provide
staging-only External Secrets, TLS, egress, PostgreSQL, Neo4j, Keycloak, remote
recovery storage, telemetry collection, and approved real endpoints. Missing inputs
are failures, never skipped checks.

For the exact retained release set:

1. Independently verify every Cosign signature and GitHub attestation against the
   ADR-040 issuer, repository, workflow, release tag, commit, and digest.
2. Verify the release manifest and SBOM checksums, then validate the resolved staging
   bundle with Kubernetes server-side dry-run in the intended cluster/context.
3. Apply staging prerequisites and wait for External Secrets and external dependencies.
4. Execute ADR-041 stages in order, waiting for success before continuing:
   `10-database-roles`; both `20-postgresql-migrations` Jobs; `30-keycloak-projector-clients`;
   `50-consistency-validation`; Identity and Audit stage 60; Audit Projector stage 70.
   The PostgreSQL migration stage includes the isolated Audit, Knowledge Graph, and
   ADR-043 Identity migration Jobs; all must complete before Stage 50.
5. Roll out Identity, Knowledge Graph, Studio BFF, Studio, recovery scheduling, and
   RC-C telemetry integration only after their prerequisites are ready.
6. Run bounded health, authentication/delegation, governed-search, mutation/outbox,
   Audit/custody, projection, Studio, backup-schedule, and metrics/alert smoke checks.
7. Record timestamps, context, namespace, manifest hash, bundle hash, Job/rollout
   outcomes, test results, operator/reviewer, and failures without secrets.

Any failed signature, provenance, vulnerability, migration, readiness, smoke, or
evidence check declares staging `FAIL` and blocks promotion. Repository-generated
`PENDING` evidence must never be edited to `PASS`; live evidence must come from the
witnessed execution system.

## Production approval and promotion

Production promotion requires staging deployment, smoke tests, and rollback rehearsal
all to be `PASS` for the exact manifest hash. Run the fail-closed gate before seeking
production approval:

```sh
python tools/ci/release_qualification.py promotion-gate \
  --evidence WITNESSED-STAGING-EVIDENCE.json \
  --manifest release-images.json
```

Production requires a deliberate protected-environment approval with the complete
evidence attached. Promotion applies the already-published production bundle; it does
not rebuild, retag, or substitute images. Apply the same ADR-041 ordering and abort on
any failed prerequisite. A generated production bundle is not evidence that this
approval or deployment occurred.

## Rollback qualification

Rollback selects one retained, previously qualified complete release manifest. Verify
its signatures, attestations, SBOMs, digest availability, configuration prerequisites,
and staging behavior. The gate rejects incomplete or mixed sets and refuses automatic
rollback across differing migration fingerprints:

```sh
python tools/ci/release_qualification.py rollback-gate \
  --current CURRENT/release-images.json \
  --previous PREVIOUS/release-images.json
```

PostgreSQL migrations are forward-only and checksum governed. Database downgrade is
not authorized. When migration sets differ, retain the current schema and qualify an
application-compatible rollback or forward fix separately; never reverse migrations
or edit migration history to make rollback pass. Rollback failure remains explicit and
traffic stays on the last safe qualified state or is isolated under incident control.

## Qualification status vocabulary

- **IMPLEMENTED:** repository inventory, release schema, complete digest resolution,
  migration/configuration binding, staging overlay, fail-closed qualification,
  promotion, and rollback validators.
- **CI-QUALIFIED:** applicable repository tests and release workflow execution passed.
  This does not imply registry publication or a deployed environment.
- **LIVE QUALIFICATION REQUIRED:** witnessed GHCR publication, Cosign/attestation,
  staging deployment/smoke, rollback rehearsal, protected production approval, and
  production deployment evidence.

Until every required witnessed state is complete, the overall Promotion P0 remains
open.
