# EMG ADR-041 — Production Provisioning Ownership & Bootstrap Contract

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-09
**Baseline:** `develop` at `ecee5fbe63637ad79f37eba3656eff117bc3f97c`.
**Resolves:** RC-1H architecture decisions for database bootstrap authority, Audit
schema ownership, projector identity inventory, bootstrap ordering, and secret custody.
**Related:** ADR-028 (Audit Reconciliation), ADR-034 (Security State and Service Trust),
ADR-038 (Human Identity Delegation Architecture), ADR-040 (Runtime Image Supply Chain),
`libs/python/emg-persistence/`, `tools/seed-data/postgres/`, and
`infra/environments/production/`.

> **This ADR authorizes architecture only.** It does not implement provisioning,
> migrations, Kubernetes Jobs, Keycloak clients, External Secrets, validation tooling,
> or runtime changes. RC-1H implementation must conform to this decision and remains a
> separate review.

> **Implementation status — 2026-08-09.** RC-1H subsequently implemented and
> repository-validated this contract: governed role bootstrap, the distinct Audit migration
> stream, the canonical projector identity inventory, per-tenant Keycloak provisioning,
> derived Audit allow-list, External Secret references, ordered stage metadata, and
> fail-closed consistency validation. Environment values and operator/CD execution remain
> operational prerequisites; Kubernetes still does not enforce cross-resource ordering.

---

## 1. Context

ADR-028 requires one stable, tenant-scoped Audit Projector Service Principal per
onboarded tenant. The token's verified `tenant_id` claim must match the claimed
dispatch row, the client must be explicitly recognized by the Audit Service, and secret
rotation must preserve the logical client identity used for audit idempotency.

The current repository implements those runtime checks but does not define a complete
production provisioning authority:

- the Keycloak realm and provisioner do not create tenant projector clients;
- projector credentials and the Audit Service client allow-list are independent inputs;
- PostgreSQL migration V007 grants privileges only if `emg_audit_projector` already
  exists, but no governed production authority creates that role;
- Audit tables are initialized by local seed SQL, with no named production migration
  owner or production migration stream; and
- Kubernetes manifests do not by themselves establish a Job-to-Deployment dependency.

Without an ownership decision, implementation would have to invent identity, database,
and deployment contracts in scripts or manifests. This ADR closes that architecture gap
without changing application behavior.

## 2. Decision Summary

EMG adopts a fail-closed, staged production provisioning contract with five authorities:

1. the **Platform Database Bootstrap Administrator** creates explicitly governed
   database-level identities before application migrations;
2. `emg_audit_migrator` owns and migrates Audit Service database objects through an
   Audit-specific stream of the existing `emg-persistence` migration framework;
3. one environment-owned **Projector Identity Inventory** is the non-secret source of
   truth for tenant/client identity;
4. Identity/Security provisions Keycloak projector clients from that inventory, while
   the same inventory derives projector runtime mapping and Audit Service allow-list
   wiring; and
5. repository validation plus operator/CD stage enforcement prevents production
   workloads from being finalized before prerequisites succeed.

No application runtime may assume bootstrap, migration-owner, Keycloak-administrator,
or secret-store-administrator authority.

## 3. PostgreSQL Bootstrap Authority

The **Platform Database Bootstrap Administrator** is the logical production authority
for PostgreSQL cluster/database prerequisites that an application migration cannot
safely own. It is an operational responsibility, not an application Service Principal
or a continuously running workload.

For the bounded Audit and Audit Projector scope, and for the pre-existing Knowledge
Graph role split governed by ADR-034, the explicitly governed production roles are:

| Role | Semantics | Responsibility |
| :--- | :--- | :--- |
| `emg_audit_migrator` | `LOGIN` | Apply and own Audit migration objects |
| `emg_audit_app` | `LOGIN` | Audit Service runtime, with append/read privileges only |
| `emg_audit_projector` | `LOGIN` | Audit Projector runtime access governed by V007 |
| `emg_knowledge_graph_migrator` | `LOGIN` | Apply and own Knowledge Graph migration objects under ADR-034 |
| `emg_knowledge_graph_app` | `LOGIN` | Knowledge Graph serving runtime with migration-governed DML only under ADR-034 |

The two Knowledge Graph roles are not a new authority introduced by this ADR. ADR-034
already fixes their identities, ownership split, and separate credential contract.
Bootstrap creates and converges them only so the canonical Knowledge Graph migration
stream can grant its governed object privileges; that stream remains the sole authority
for application-object ownership and grants.

The bootstrap authority must:

- execute before any Audit or Knowledge Graph migration that grants to these roles;
- create only roles explicitly governed by accepted architecture;
- be idempotent and converge existing roles to the governed non-privileged attributes;
- obtain its administrative credential from the environment secret-management system;
- never place a password or credential material in repository SQL, manifests, logs, or
  generated release evidence;
- never become an application runtime identity; and
- relinquish no administrative capability to the roles it creates.

Role creation and credential material are separate operations. The repository governs
role names and required attributes. The environment secret-management system governs
actual passwords, initial materialization, and rotation. Rotation must not rename a role
or expand its privileges.

Managed PostgreSQL providers may reserve alteration of superuser, replication, or
row-security-bypass attributes to the provider's true superuser. On such platforms,
bootstrap must explicitly create new roles with the governed safe attributes, verify
reserved attributes on existing roles rather than issuing a prohibited alteration, and
fail closed if any reserved attribute is elevated. It must still converge provider-
permitted attributes and credentials and verify the complete effective role state. This
is an operational compatibility rule; it does not relax the governed role contract.

PostgreSQL 16 grants a CREATEROLE administrator only ADMIN OPTION over a role it
creates, never INHERIT or SET; a non-superuser administrator therefore cannot itself
author an object with `AUTHORIZATION`/`OWNER TO` naming that role immediately after
creating it, even though it retains full ability to alter and converge the role's
attributes on every subsequent bootstrap run. Where the governed contract requires the
bootstrap authority to create a schema or reassign a table's ownership to a role it
manages, the authority must acquire that role's membership only for the statement(s)
that require it and revoke it before the enclosing transaction commits. This is the
same "relinquish no administrative capability" principle applied to a second, distinct
PostgreSQL privilege axis (the ability to act as a role, not merely to administer it):
standing usage-level membership must never persist past the operation it was acquired
for, while the ADMIN OPTION membership PostgreSQL grants automatically on role creation
is structural and load-bearing for future convergence, and is not something bootstrap
can or should relinquish.

The bootstrap authority may be implemented as a bounded one-shot Job or an equivalent
operator/CD-controlled step using existing platform patterns. It is not a new database
operator or orchestration system.

## 4. Audit Schema Ownership and Migration Authority

`emg_audit_migrator` is the canonical production owner of Audit Service PostgreSQL
objects and Audit migration history. The Audit Service runtime role
`emg_audit_app` must not own Audit tables, indexes, constraints, functions, or migration
history and must have no schema-creation or DDL privilege.

Production Audit schema evolution is governed by the existing `emg-persistence`
PostgreSQL migration framework. Its existing properties remain binding:

- forward-only ordering;
- checksum immutability after application;
- transactional PostgreSQL application;
- dirty/failed-state halting; and
- explicit one-shot execution before serving workloads.

Audit migrations form a distinct, packaged **Audit migration stream** with an
Audit-specific history namespace owned by `emg_audit_migrator`. They reuse the existing
discovery, checksum, runner, and PostgreSQL executor semantics. They must not be mixed
into the Knowledge Graph migration sequence merely to reuse its version numbers, and an
Audit migration Job must not run the Knowledge Graph default migration directory against
an Audit-only database. A separately named history namespace is a stream boundary inside
the existing framework, not a second migration framework.

The migration stream must adopt the existing Audit table definitions and constraints
without changing event, custody, hashing, idempotency, advisory-lock, tenant, reporting,
or append-only semantics. Any required adoption of pre-existing production objects must
be forward-controlled, ownership-safe, and tested against populated databases; it must
not recreate, rewrite, truncate, re-hash, or silently replace authoritative audit data.

`tools/seed-data/postgres/` remains a local-development and test-fixture mechanism. It is
not production migration authority, and production startup must not depend on mounting
or executing that directory.

## 5. Projector PostgreSQL Runtime Role

`emg_audit_projector` is a production runtime `LOGIN` role created by the Platform
Database Bootstrap Administrator before V007 is applied.

V007 remains the sole authority for its existing application-object grants:

- schema `USAGE`;
- `SELECT` on `mutation_ledger` and `mutation_dispatch`; and
- column-scoped `UPDATE` on `available_at`, `attempt_count`, `claim_owner`,
  `claim_expires_at`, and `delivered_at` in `mutation_dispatch`.

The role has no schema ownership, DDL, graph write access, ledger mutation, table-wide
`UPDATE`, `DELETE`, or privileges broader than ADR-028 D-19 and V007. Runtime
credentials are delivered through External Secrets references. The repository defines
the role and required secret reference; the environment owns credential values and
rotation.

V007's conditional guard may remain as compatibility protection, but production
validation must never treat a skipped grant as success. The role's existence and the
effective least-privilege grants must be verified after migration and before projector
rollout.

## 6. Canonical Projector Identity Inventory

Each environment has exactly one authoritative, declarative **Projector Identity
Inventory**. The repository owns its schema and validation rules; environment owners
supply its values.

Each entry contains only:

- `tenant_id` — the canonical tenant identifier; and
- `client_id` — the stable logical projector client identifier.

The inventory contains no client secret, token, password, private key, database DSN, or
Keycloak administrator credential. Tenant and client identifiers must be non-empty and
unique, and each tenant maps to exactly one client. A client may not map to more than one
tenant. Production inventory containing duplicates, omissions, unresolved placeholders,
or unknown fields fails validation.

The same validated inventory is the only source from which implementation may derive:

1. Keycloak projector client provisioning;
2. the client's tenant claim and service-role assignment;
3. the expected keys for per-tenant projector client-secret material;
4. the projector runtime tenant/client/credential mapping; and
5. the Audit Service accepted-projector client allow-list.

Independent hand-maintained identity maps or client allow-lists are forbidden. Derived
artifacts may contain different representations required by existing runtime settings,
but they must be generated or validated against the same inventory and must not become
new sources of truth.

## 7. Keycloak Projector Client Contract

Identity/Security remains responsible for projector credential issuance and validation,
as established by ADR-028 D-31. For every inventory entry, canonical Keycloak
provisioning must converge exactly one client with:

- the inventory's stable `client_id`;
- confidential-client semantics;
- service accounts enabled;
- interactive, browser, direct-access-grant, and other human login flows disabled;
- realm roles `service-account` and `svc-audit-projector` assigned to its service
  account;
- the existing internal-services audience/issuer contract; and
- a token `tenant_id` claim exactly equal to the entry's `tenant_id`.

Provisioning must be idempotent and must reject an existing client whose tenant binding,
client mode, or required role assignment conflicts with the inventory. It must not
silently repurpose or delete such a client. Secret rotation must retain the stable
`client_id`, preserving ADR-028's `(source_principal, event_id)` idempotency boundary.

One unrestricted cross-tenant projector client, wildcard registration, a default
projector identity, and tenant authority from submitted event content remain prohibited.

## 8. Audit Service Allow-List and Credential Reconciliation

The Audit Service projector allow-list is the sorted, unique set of `client_id` values
derived from the validated Projector Identity Inventory. It remains explicit and
continues to use the existing recognized-client authentication mechanism. This decision
does not authorize wildcard client trust or weaken required token claims or roles.

Projector runtime credentials are reconciled to inventory by both `tenant_id` and
`client_id`. The secret-bearing runtime representation may be assembled only after each
inventory entry resolves to exactly one environment-owned client secret.

Production finalization fails when:

- a credential refers to a tenant/client pair absent from the inventory;
- an inventory tenant/client has no corresponding credential reference;
- an allow-list entry is absent from or additional to the inventory-derived set;
- a tenant or client identifier is duplicated; or
- Keycloak's effective tenant claim or role assignment differs from the inventory.

The runtime applications retain their existing fail-closed checks. Provisioning
validation is an additional deployment boundary, not a replacement for runtime token
validation.

## 9. Canonical Bootstrap Ordering

The production sequence is:

```text
external infrastructure prerequisites
  -> Platform Database Bootstrap Administrator creates governed roles
  -> PostgreSQL application/schema migrations
  -> Keycloak projector client provisioning
  -> External Secret material is synchronized into the workload environment
  -> identity, role, grant, schema, and allow-list consistency validation
  -> Audit Service rollout
  -> Audit Projector rollout
```

External infrastructure prerequisites include reachable PostgreSQL and Keycloak
services, the approved secret-management integration, required administrative
credentials, and the environment-owned identity inventory and secret values. Their
existence does not by itself authorize workload rollout.

Every stage must produce an explicit successful outcome before the next stage begins.
Failure or indeterminate state halts finalization. Re-running a completed stage must be
safe and convergent.

The Audit Service must not start before its migration stream is current and its
inventory-derived allow-list is reconciled. The Audit Projector must not start before
the Audit Service is available and its database grants, tenant mapping, and credentials
are reconciled.

## 10. Workload Gating and Kubernetes Boundary

RC-1H implementation uses existing one-shot Kubernetes Job and manifest-validation
patterns. It does not introduce a new orchestrator.

Vanilla Kubernetes does not provide a general Job-to-Deployment dependency. Therefore:

- repository manifests and validation own structural correctness, stage definitions,
  required references, and deterministic preflight checks;
- the repository-owned deployment procedure must expose ordered, individually verifiable
  bootstrap and workload stages; and
- the environment's operator or CD system owns executing those stages, waiting for each
  Job's successful completion, approving rollout, and withholding later workload stages
  after failure.

A successful Kustomize render proves only structural renderability. It is not evidence
that roles, schemas, clients, claims, or secrets exist. Deployment readiness and restart
loops are not substitutes for bootstrap completion. A production bundle or rollout may
be finalized only after repository validation receives the required stage evidence and
finds no unresolved placeholder or inconsistency.

## 11. External Secrets and Credential Boundary

Repository-owned manifests contain secret references only. The required secret domains
are:

- Platform Database Bootstrap Administrator credential;
- Audit migration DSN for `emg_audit_migrator`;
- Audit runtime DSN for `emg_audit_app`;
- Audit Projector PostgreSQL DSN for `emg_audit_projector`;
- one projector client secret per canonical inventory entry; and
- Keycloak administrative provisioning credential.

The repository defines deterministic reference contracts and validates their coverage.
The environment secret-management system owns the values, generation or controlled
injection, storage, access policy, and rotation. No secret-store vendor is selected by
this ADR.

No secret value may appear in Git, an ADR, migration SQL, an identity inventory, a
ConfigMap, logs, validation output, generated release manifests, or deployment evidence.
Local-development fixture passwords remain explicitly non-production and must never be
promoted into a production artifact.

## 12. Repository and Operational Ownership

Repository-owned responsibilities are:

- governed database role definitions and idempotent bootstrap logic;
- the Audit migration stream and migration safety tests;
- Projector Identity Inventory schema and validation;
- Keycloak provisioning logic and conformance checks;
- deterministic derivation/reconciliation rules for runtime mapping and allow-list;
- External Secret references; and
- fail-closed structural and finalization validation.

Environment-owned responsibilities are:

- actual tenant and stable client identifiers in the inventory;
- PostgreSQL and Keycloak endpoints;
- administrative, migration, runtime, and client credential material;
- secret-store configuration and access policy;
- execution and approval of ordered production stages; and
- retention of operational execution evidence.

Environment ownership does not permit bypassing repository validation or changing the
governed role, tenant, claim, privilege, or ordering contracts.

## 13. Migration and Adoption Safety

RC-1H implementation may move the existing Audit table definitions from local seed
authority into the new Audit migration stream. This authorization is limited to
governance and safe adoption; it does not authorize changes to audit data semantics or
public APIs.

Implementation must prove:

- clean-database initialization creates the required Audit objects;
- adoption of an existing populated Audit database preserves every row and hash chain;
- the migration owner, not the runtime role, owns Audit objects and history;
- repeat execution is a no-op after successful application;
- checksum drift, dirty state, missing prerequisites, and insufficient privilege halt;
- `emg_audit_app` retains only required runtime privileges; and
- `emg_audit_projector` retains exactly the V007 privilege set.

Knowledge Graph migrations and Audit migrations remain independently runnable streams
even when an environment places their objects in the same PostgreSQL database. Neither
stream may claim or mutate the other's history or ownership.

## 14. Alternatives Rejected

- **Leave V007 dependent on an undocumented pre-created role.** Rejected because a
  skipped conditional grant can produce an apparently successful but unusable release.
- **Let an application runtime create PostgreSQL roles.** Rejected because role creation
  requires administrative authority incompatible with least-privilege runtime identity.
- **Let `emg_audit_app` own Audit schema objects.** Rejected because compromise would
  confer DDL and ownership capabilities over authoritative audit evidence.
- **Use local seed SQL as production schema authority.** Rejected because the directory
  mixes fixture/bootstrap concerns, local credentials, and no production migration
  history.
- **Run the Knowledge Graph default migration directory as the Audit migration path.**
  Rejected because the migration sets have different object ownership and lifecycle
  boundaries.
- **Introduce a second Audit migration framework.** Rejected because the existing
  `emg-persistence` runner already provides the required ordering, checksum, transaction,
  and failure semantics; Audit needs a distinct stream, not competing mechanics.
- **Maintain Keycloak clients, projector mappings, and Audit allow-lists independently.**
  Rejected because drift can misattribute tenants or make delivery permanently fail.
- **Commit projector client secrets or place them in the identity inventory.** Rejected
  because identity metadata and credential custody are separate trust boundaries.
- **Use one unrestricted cross-tenant projector identity.** Rejected by ADR-028's
  per-tenant identity and source-principal stability decisions.
- **Rely on Deployment readiness alone.** Rejected because readiness cannot create a
  missing role, schema, client, claim, or secret and cannot establish ordered bootstrap.

## 15. Architecture Boundaries

This decision preserves:

- ADR-028 tenant-partitioned projector identities, stable source principals, and
  fail-closed tenant matching;
- ADR-034 token verification, Audit tenant attribution, and runtime/migration separation;
- ADR-038 delegated-human identity and synchronous fail-closed audit behavior;
- V007's existing least-privilege grant semantics;
- PostgreSQL as authoritative persistence;
- the existing Audit Service authentication and public HTTP APIs;
- the External Secrets reference pattern; and
- provider-neutral application deployment.

It introduces no new public API, audit event shape, hash input, advisory-lock semantic,
tenant semantic, mutation behavior, GraphStore behavior, Policy Engine behavior, or
authorization rule.

## 16. Consequences

### Positive

- Every production database and identity prerequisite has a named owner.
- Audit schema evolution gains forward-only, checksum-verified production governance.
- Projector clients, tenant claims, runtime credentials, and Audit trust are reconciled
  to one non-secret source of truth.
- Workload finalization can fail before an unusable or dangerously divergent rollout.
- Runtime identities retain least privilege and never receive bootstrap authority.

### Costs and constraints

- The existing migration framework requires an Audit-specific stream/history binding.
- Environments must maintain a validated inventory and one secret per tenant client.
- Operator/CD procedures must enforce stage completion because Kubernetes rendering does
  not establish cross-resource execution order.
- Existing Audit databases require a tested, non-destructive ownership-adoption path.

## 17. Acceptance Criteria

RC-1H implementation is conformant only when it demonstrates all of the following:

- idempotent creation of the three governed Audit/projector roles and the two ADR-034
  Knowledge Graph roles without repository passwords;
- role bootstrap completion before V007 and Audit migrations;
- exact V007 least-privilege grants for `emg_audit_projector`;
- a dedicated `emg_audit_migrator`-owned Audit migration stream using
  `emg-persistence` semantics;
- clean initialization and populated-database adoption without audit semantic or data
  changes;
- one valid per-environment inventory with unique tenant/client bindings;
- idempotent Keycloak client provisioning with required roles, claim, audience, and
  disabled interactive flows;
- exact derivation and reconciliation of projector runtime mapping and Audit allow-list;
- complete External Secret reference coverage with no committed values;
- fail-closed rejection of missing, unknown, duplicate, divergent, or placeholder inputs;
- an explicit ordered bootstrap procedure with verifiable stage completion; and
- production Kustomize rendering plus validation that distinguishes renderability from
  deployability.

## 18. Non-Goals

This ADR does not implement RC-1H, provision an environment, select a secret-store vendor,
select production tenants, create credentials, change an application API, change audit or
mutation semantics, introduce database high availability, define backup policy, modify
ADR-028, or automate a production deployment.

## Ratification

This ADR was checked against ADR-028, ADR-034, ADR-038, ADR-040, and the current
`emg-persistence` migration contract. No accepted architecture assigns the Audit schema
owner, the projector role-creation authority, or a competing projector identity source
of truth. The Audit-specific migration stream extends the existing framework's governance
without making the Knowledge Graph migration set authoritative for Audit objects.

**Review Outcome: Accepted.** RC-1H implementation is authorized subject to this complete
ownership, ordering, least-privilege, source-of-truth, and fail-closed contract.
