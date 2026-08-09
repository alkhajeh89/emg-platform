# EMG Production Deployment Guide

This guide records the mandatory SRS-3 deployment controls. Local
`docker-compose.yml` remains development-only and contains deliberately marked
local credentials.

## Required production configuration

- Set every service deployment environment explicitly to `production`.
- Supply secrets through the platform secret store; never bake them into an
  image, manifest, environment file, or CI log.
- Terminate public TLS at the trusted ingress and use authenticated encrypted
  transport between services. Keycloak and audit service URLs must use HTTPS.
- PostgreSQL DSNs must set `sslmode=verify-full` (or, during a controlled
  certificate transition, `verify-ca`/`require`). Runtime and migration
  credentials for Knowledge Graph must remain distinct.
- Redis, when deployed for a consuming service, must use TLS and authentication.
  The current application services do not consume Redis.
- Production startup must never use an in-memory persistence backend.

## Runtime controls

Run service images as their packaged non-root user with a read-only root
filesystem, all Linux capabilities dropped, `no-new-privileges`, a bounded
`/tmp`, and platform-enforced CPU, memory, PID, replica, and request-rate
limits. Preserve `/healthz` and `/readyz` probes. The Compose limits are
development examples, not production capacity sizing.

Before promotion, verify the image digest, SBOM, provenance attestation,
vulnerability report, migration result, and readiness response.

## Runtime image release contract

ADR-040 is implemented by `.github/workflows/runtime-image-release.yml` and
`tools/ci/runtime_image_release.py`:

1. An approved `v*` tag derives the governed runtime image inventory.
2. Each image is built once and must pass the blocking Trivy critical-severity
   gate before publication.
3. The scanned build is published to GHCR and resolved to an immutable digest.
4. Cosign signs and verifies that digest using GitHub Actions OIDC; GitHub
   runtime provenance and a per-image CycloneDX SBOM are retained.
5. Finalization generates `release-images.json`, a placeholder-free
   `production-resolved.yaml`, retained SBOMs, and a complete rollback digest
   set.

The checked-in `registry.invalid` references are non-deployable source-template
fixtures. Deploy only the generated resolved bundle. The protected
`production-release` environment and a witnessed first live GHCR/OIDC/Cosign
release remain operational prerequisites.

## Provisioning and rollout contract

ADR-041 repository resources are implemented, but Kubernetes does not infer
Job-to-Deployment dependencies. Operator/CD must wait for each successful
stage:

```text
external infrastructure and secret references
→ database role bootstrap and bounded existing-Audit ownership adoption
→ Audit and Knowledge Graph migrations
→ Keycloak projector client provisioning
→ final External Secret synchronization
→ provisioning consistency validation
→ Audit Service rollout
→ Audit Projector rollout
```

Stage 10 validates the exact accepted pre-existing Audit schema before
transferring its two governed tables to `emg_audit_migrator`; it never rewrites
Audit or custody rows. If an earlier V001 attempt is already dirty from the
ownership defect, follow the explicit `audit-retry-v001` procedure in
`infra/environments/production/README.md`. Do not clear or delete the dirty
history row manually.

Knowledge Graph V005 is a released immutable migration. Fresh migrations use
the repository's checksum-preserving scoped compatibility path; existing
successful V005 databases receive forward V009. An exact dirty V005 caused by
the historical schema-wide operation must use the bounded
`knowledge-graph-retry-v005` procedure in the production README before the
ordinary migration Job is rerun.

Run `tools/ci/validate_production_provisioning.py` against the production
overlay before finalization. A successful render or readiness probe does not
prove that identities, grants, secrets, migrations, or stage completion exist
in the target environment.

## Remaining environment-owned prerequisites

- Production tenant identity inventory and actual credentials.
- External Secrets Operator plus an approved provider-specific secret store.
- TLS certificates, approved external endpoints, and egress policy.
- Production observability/alerting and capacity/HA decisions.
- Backup scheduler, encryption/KMS custody, cross-region storage, and a
  witnessed recovery rehearsal.
