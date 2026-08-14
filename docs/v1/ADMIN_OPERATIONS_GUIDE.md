# EMG v1 administrator and operations guide

## Operating model

PostgreSQL is authoritative. Neo4j is a rebuildable projection. Keycloak supplies identity. Studio
communicates only with Studio BFF; the BFF delegates human identity to Knowledge Graph. Audit
Projector durably delivers mutation audit intents to Audit. Environment-owned infrastructure is
not created merely because a Kubernetes reference exists.

Governed release order is:

1. database role bootstrap;
2. Audit and Knowledge Graph migrations;
3. Keycloak/projector identity provisioning;
4. consistency validation;
5. core services and Studio BFF;
6. Audit Projector;
7. Studio and ingress;
8. smoke, alert, recovery, rollback, and E2E qualification.

Use the stage annotations and commands in `docs/devops/PRODUCTION_DEPLOYMENT_GUIDE.md`. Kubernetes
does not infer cross-resource ordering. Never apply the base directory directly or deploy a bundle
containing `registry.invalid`, `example.invalid`, mutable tags, synthetic digests, or literal
Secrets.

## Preconditions

- Approved cluster/context and namespace.
- Placeholder-free TLS/DNS/ingress/egress configuration.
- Environment-owned PostgreSQL, Neo4j, Keycloak, SecretStore, IAM/Workload Identity, monitoring,
  and administratively separate remote backup custody.
- Complete immutable release manifest and resolved environment bundle.
- Required protected-environment approval and named operator/security witnesses.

Provider selections and live values are **PENDING_LIVE**. This guide does not select them.

## Readiness checks

Check Kubernetes object status and each component’s `/healthz` and `/readyz` endpoint through the
approved operational path. Liveness only proves the process responds. Readiness must remain false
when mandatory dependencies or secure configuration are unavailable. Do not patch probes to force
a rollout green.

Confirm metrics scraping, rule evaluation, and receiver delivery separately. Repository rule and
dashboard validation is not proof of live alerting.

## Data operations

- Run migrations only with the governed migrator identity.
- Run application services only with runtime identities.
- Never grant application roles `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`,
  `BYPASSRLS`, schema ownership, or cloud administrator membership.
- On managed PostgreSQL, converge legally alterable attributes and verify every effective
  attribute from `pg_roles`; fail closed on excess privilege.
- Treat Neo4j divergence as projection degradation, not authorization to make it authoritative.

## Backup, restore, and rollback

Follow `docs/operations/postgresql-backup-recovery.md`. Retention must preserve all material needed
by every valid recovery window. Backup/WAL custody must be administratively separate; a PVC alone
does not satisfy that requirement. A restore is not accepted until integrity, schema, search,
dispatch, Audit, and projection reconciliation checks pass with measured RPO/RTO.

Rollback uses a complete prior release set. The repository gate rejects incomplete, equal, newer,
unparseable, or migration-incompatible candidates. Never mix image generations or roll database
schema backward. See `docs/operations/release-promotion-and-rollback.md`.

Identity's refresh-token state is durable PostgreSQL, not in-memory: a database restore invalidates
every restored refresh family/token and requires the full ADR-043 recovery-fencing sequence before
Identity may serve traffic again — workload fence, database-session fence, a two-phase network
fence (a migrator-only reconciliation phase, then a readiness-qualification phase scoped to the
single freshly started workload instance), external recovery-authority rotation, transactional
reconciliation, and Stage-50 **recovery-qualification** mode (distinct from ordinary Stage-50, which
never touches recovery evidence). Every fence requires positive, freshly re-verified evidence — never
an assumed command exit code or elapsed time — and Stage-50 recovery qualification additionally
requires that evidence be attributable to the exact governed fence owner and the exact namespace
being recovered. Follow `docs/operations/postgresql-backup-recovery.md` step by step; do not
improvise the order or skip a fence because an earlier step succeeded.

## Maintenance cadence

| Cadence | Required action |
| --- | --- |
| Continuous | Availability, error, latency, auth, Audit, projector/dispatch, projection, search-retention, backup and storage alerts |
| Daily | Confirm backup/WAL job success, remote-copy success, rule evaluation, receiver delivery health, and expiring credentials/certificates |
| Weekly | Review failed/retried work, retained search/storage cardinality, capacity trend, denied administrative operations, and unresolved incidents |
| Monthly | Restore sample in isolation, review access and service identities, dependency/vulnerability status, certificate/secret expiry, and runbook accuracy |
| Per release | Verify manifest/signatures/provenance/SBOM/scans, migration compatibility, staging smoke, rollback target, and evidence retention |
| Per rotation | Use dual-valid overlap where supported, validate new credential, switch consumers, observe, then retire old material after its acceptance window |

Live cadence acceptance and named owners remain `PENDING_LIVE` until operational sign-off.
