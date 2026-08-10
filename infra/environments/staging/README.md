# Staging release qualification overlay

This overlay reuses the production Kubernetes base in the isolated `emg-staging`
namespace. It renders and qualifies the same topology and governed runtime image
set as production; it is not a second deployment architecture.

The checked-in overlay deliberately has no ExternalSecret resources and retains
non-routable external endpoint placeholders. Before live qualification, the
environment owner must supply staging-only External Secrets, approved TLS endpoints,
the `emg-studio-tls` certificate, external egress policy, PostgreSQL, Neo4j,
Keycloak, remote backup storage, and the RC-C telemetry collector. Production
secret paths or credentials must never be reused in staging.

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
