# Production Kubernetes base

`base/` contains the provider-neutral RC-1A workload foundation.  It defines
single-replica, `Recreate` Deployments for Identity, Audit, Knowledge Graph,
and Studio BFF; one-shot Knowledge Graph migration and Keycloak provisioning
Jobs; the Identity audit-spool PVC; Services; and portable NetworkPolicies.

The base is not deployable by itself.  Use an environment overlay and replace
the deliberately synthetic image digests.  It does not provision a cluster,
database, graph store, identity provider, ingress controller, TLS certificate,
External Secrets Operator, or secret backend.
