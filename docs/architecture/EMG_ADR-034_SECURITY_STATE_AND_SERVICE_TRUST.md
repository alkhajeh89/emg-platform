# ADR-034 — Security State and Service Trust Hardening

## Status

**Accepted — SRS-2, 2026-07-30.**

## Context

The post-SRS-1 security audit found four production boundaries that were not
durably enforceable: refresh tokens were stateless and reusable; audit reads
were neither tenant- nor clearance-scoped; Knowledge Graph runtime
credentials owned migration objects; and inbound services disagreed about
the required service-token claims.

## Decision

### Refresh-token lifecycle

Identity owns a `RefreshTokenStore` port. Infrastructure supplies lock-safe
in-memory and PostgreSQL adapters. A refresh JWT carries independent `jti`
and `family_id` identifiers. Persistence stores only SHA-256 hashes of those
identifiers. Rotation atomically consumes one active token and registers its
successor. Reuse or a parallel loser revokes every token in the family.
Access-token verification rejects a revoked family. Production startup
requires the PostgreSQL adapter; legacy refresh tokens without a family must
authenticate again.

### Audit read confinement

The audit service assigns `tenant_id` from the verified producer token and
includes it in version-3 audit-event hashing. Every event list, lookup,
page, and export query receives a mandatory server-side tenant constraint
and the set of classifications authorized by the existing PEP. Filtering
occurs in storage before pagination or counts. Legacy database rows receive
the reserved `legacy-unscoped` tenant and are invisible to normal tenant
tokens.

### Database roles

`emg_knowledge_graph_migrator` owns schemas, tables, trigger functions, and
migration history. `emg_knowledge_graph_app` has schema usage and only the
DML needed by runtime repositories; it has no schema `CREATE`, DDL,
ownership, or ability to replace ledger integrity functions. Deployments
provide separate, independently rotated DSNs.

PostgreSQL row-level security is deferred. The current `GraphStore`
transaction contract does not establish a trusted database-local tenant
setting, so enabling RLS now could either deny valid work or create a false
isolation guarantee. RLS requires a separate reviewed decision covering
connection-pool reset and `SET LOCAL` semantics.

### Service-token contract

Knowledge Graph, Identity, and Audit independently validate the same
allowlisted client IDs. A token must have a verified RS256 signature,
issuer, audience, expiry, non-empty `tenant_id`, and all roles registered
for its `azp`. Roles are read from `realm_access.roles`, never inferred
solely from the client ID or a top-level self-declared field. The checked-in
Keycloak realm emits tenant, clearance, and realm-role claims for each
approved service account.

## Consequences

- Refresh and replay security now require durable state and current
  authorization, respectively.
- Audit events written through the service are tenant attributable and
  classification filtered.
- Runtime database compromise cannot alter DDL or remove ledger triggers
  using the application credential.
- Service tokens missing any required trust claim fail closed.
- ADR-033 Phase 4, schema normalizers, discovery, and supply-chain work are
  unaffected and remain outside SRS-2.
