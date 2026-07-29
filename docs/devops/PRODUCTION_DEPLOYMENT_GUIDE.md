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
