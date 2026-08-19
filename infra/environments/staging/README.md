# Staging release qualification overlay

This overlay reuses the production Kubernetes base in the isolated `emg-staging`
namespace. It renders and qualifies the same topology and governed runtime image
set as production; it is not a second deployment architecture.

The checked-in overlay deliberately has no ExternalSecret resources and retains
non-routable external endpoint placeholders. Before live qualification, the
environment owner must supply staging-only External Secrets, approved TLS endpoints,
the `emg-studio-tls` certificate, the `emg-recovery-signer-tls` certificate
(distinct from production's -- see the production overlay's README item 9),
external egress policy, PostgreSQL, Neo4j, Keycloak, remote backup storage, and
the RC-C telemetry collector. Production secret paths or credentials must never
be reused in staging.

The staging `emg-knowledge-graph-secrets` contract must provide distinct
`migration-postgres-dsn` and `postgres-dsn` keys for
`emg_knowledge_graph_migrator` and `emg_knowledge_graph_app`, respectively.
The database-bootstrap Job consumes both keys before the Knowledge Graph migration;
the serving workload consumes only `postgres-dsn`.

Render the source template with:

```sh
kubectl kustomize infra/environments/staging
```

Release tooling replaces every governed `registry.invalid` fixture with the same
immutable digest set published by the ADR-040 workflow. Repository rendering is
not staging qualification. A witnessed qualification must validate signatures and
attestations, apply ordered bootstrap/migration Jobs, wait for readiness, execute
bounded smoke checks, retain evidence, and rehearse the complete rollback candidate
before production promotion can be approved.
