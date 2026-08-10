# RC-1A Production Deployment Foundation

## Scope and topology

RC-1A supplies a Kustomize deployment artifact for one production replica of
Identity, Audit, Knowledge Graph, Studio BFF, and Studio. Knowledge Graph migration and
Keycloak realm provisioning are separate one-shot Jobs. PostgreSQL, Neo4j,
Keycloak, the Kubernetes cluster, External Secrets Operator, ingress/TLS, and
the secret backend are prerequisites rather than resources managed here.

`docker-compose.yml` remains a development-only environment. This foundation
does not change persistence, PolicyEngine, authorization, or mutation semantics.

## Production startup gates

Every service rejects unknown service-prefixed environment variables. In
addition, production startup fails under these conditions:

| Workload | Fail-fast conditions |
| --- | --- |
| Identity | Keycloak and Audit URLs are not HTTPS; PostgreSQL does not require TLS or has a blank/development password; the audit spool is relative, under a temporary directory, or its parent is absent/not writable; the policy bundle is absent. |
| Audit | Keycloak is not HTTPS; PostgreSQL does not require TLS or has a blank/development password; the policy bundle is absent. |
| Knowledge Graph | Keycloak or Audit is not HTTPS; runtime or migration PostgreSQL lacks TLS or a non-development password; Neo4j is not `neo4j+s` or has blank/development credentials; policy or schema catalog is absent. |
| Studio BFF | Keycloak, Knowledge Graph, redirect, or frontend URL is not HTTPS; OIDC secret is blank/development; cookie names lack `__Host-`; session bounds are invalid. |
| Studio | The governed image build cannot resolve its fixed internal Studio BFF service destination; no secret or browser-visible backend configuration is accepted. |

Secret-backed environment variables use `secretKeyRef`; if External Secrets
Operator has not materialized a required Secret/key, Kubernetes prevents the
container from starting. No credential value is stored in the manifests.

## Probe contract

`/healthz` is process-only for every service. It does not contact dependencies.
Production `/readyz` checks are bounded by a two-second configurable timeout and
are read-only:

| Workload | Readiness evidence |
| --- | --- |
| Identity | Public Keycloak JWKS, read-only PostgreSQL `SELECT 1`, writable mounted spool directory, and Audit liveness. Audit unavailability is degraded but does not remove readiness while the durable spool is usable. |
| Audit | Store health/read-only database query. |
| Knowledge Graph | GraphStore health, public Keycloak JWKS, and Audit liveness. |
| Studio BFF | Public Keycloak discovery and JWKS plus Knowledge Graph readiness. |
| Studio | Process liveness and ability to serve the standalone Next.js application. BFF dependency readiness is gated separately before Studio rollout. |

No readiness path logs in, exchanges a token, writes application state, emits an
audit event, or runs a migration. Mandatory dependency failure produces HTTP
503. Identity remains ready during Audit outage only because durable local
acceptance is available; a missing/unwritable spool produces 503.

## Durable Identity audit spool

Identity mounts a dedicated `ReadWriteOnce` PVC at
`/var/lib/emg-identity/audit-spool`. The existing atomic append, fsync, bounded
retention, and replay behavior is unchanged; RC-1A changes only the storage
medium from container-local filesystem to persistent storage. With one Identity
replica and `Recreate`, the same PVC is reattached after restart and pending
records remain available for replay. PVC backup/PITR and generic Audit dispatch
resilience remain outside RC-1A.

## Security boundary

Pods run non-root with a read-only root filesystem, dropped capabilities,
`RuntimeDefault` seccomp, bounded resources, and no service-account token
automount. Default-deny NetworkPolicies isolate EMG pods; DNS and declared
in-cluster flows are explicit. External egress is an environment input because
portable Kubernetes NetworkPolicy has no FQDN policy primitive. The operator
must use validated CIDRs, an egress gateway, or CNI-specific FQDN controls.

Migration database credentials occur only in the migration Job. Keycloak
administrator credentials occur only in the provisioning Job. Studio BFF has no
datastore mount or dependency and retains opaque process-local sessions.

## Deliberately unresolved RC1 work

RC-1A does not close backup/PITR/recovery (RC001-C01), generic audit-dispatch
resilience (RC001-H06), image publishing/signing/provenance/promotion/rollback
(RC001-H08), observability (RC001-H09), or evidence-ledger hardening
(RC001-M05). The checked-in image digests are synthetic validation fixtures and
must be replaced with published digests before deployment.
