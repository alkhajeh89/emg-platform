# Production environment overlay (RC-1A)

This Kustomize overlay is the production deployment artifact for the RC1
single-replica topology. Render it with:

```sh
kubectl kustomize infra/environments/production
```

Before deployment, the platform operator must:

1. Replace every `registry.invalid/...@sha256:...` fixture with an immutable,
   published image digest. RC-1A does not publish, sign, promote, retain, or
   construct rollback artifacts; those remain RC-1C / RC001-H08.
2. Replace every `*.production.example.invalid` endpoint with the approved TLS
   endpoint for external PostgreSQL, Neo4j, Keycloak, and other dependencies.
3. Install External Secrets Operator and provide a provider-specific
   `ClusterSecretStore` named `emg-production-secrets` (or patch the reference).
   No provider credentials or secret values belong in this repository.
4. Provision the TLS Secret named `emg-studio-tls` through the cluster's
   certificate mechanism and configure the ingress host.
5. Provide a StorageClass suitable for the Identity audit-spool PVC.
6. Add environment-specific egress NetworkPolicies or CNI policy for each
   approved external dependency.

## Network boundary

Portable Kubernetes NetworkPolicy enforces default-deny ingress and egress for
EMG workloads, explicit DNS access, and the declared in-cluster application
flows. Standard NetworkPolicy cannot restrict arbitrary external destinations
by FQDN. `external-egress.example.yaml` is deliberately not included in the
overlay: it documents the CIDR-based input shape without guessing production
addresses. FQDN-aware controls, NAT/egress gateway policy, TLS inspection, and
External Secrets controller egress are cluster/CNI responsibilities.

Until the environment-specific external egress rules exist, workloads and Jobs
fail closed because their mandatory dependencies are unreachable.

## Secret and job isolation

The checked-in `ExternalSecret` resources contain remote keys only. Kubernetes
Secrets are created by the operator; absent Secrets prevent container startup.
The Knowledge Graph migration credential is mounted only in the migration Job.
The Keycloak administrator credential is mounted only in the provisioning Job.

## Runtime limitations

All serving workloads are single replica. Studio BFF uses process-local opaque
sessions and `Recreate`; a restart invalidates sessions and users must
reauthenticate. Direct Redis or datastore access by Studio BFF is not introduced.
This limitation blocks horizontal Studio BFF scaling but does not block the
approved single-replica RC1 topology.
