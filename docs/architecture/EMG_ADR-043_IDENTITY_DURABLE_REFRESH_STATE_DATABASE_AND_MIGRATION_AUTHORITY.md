# EMG ADR-043 — Identity Durable Refresh State Database and Migration Authority

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-14
**Baseline:** `develop` at `b3e6cc76f0df10d9f7566ea97575dadf4d7cebb1`.
**Resolves on acceptance:** the production database placement, ownership, migration,
bootstrap, credential, least-privilege, adoption, and recovery authority missing from
ADR-034's durable Identity refresh-state requirement.
**Related:** ADR-034 (Security State and Service Trust), ADR-035 (Human Principal
Authentication), ADR-038 (Human Identity Delegation Architecture), ADR-039 (Backup,
PITR and Recovery Governance), ADR-040 (Runtime Image Supply Chain), and ADR-041
(Production Provisioning Ownership & Bootstrap Contract).

> **This ADR authorizes architecture only after acceptance.** It does not implement a
> migration, create a role or credential, change application SQL, modify a manifest,
> access a target database, or authorize RC.9 publication. Implementation requires a
> separate review after acceptance.

> **Implementation status — 2026-08-14.** RC.9 repository implementation packages the isolated
> Identity V001 stream, governed bootstrap/adoption and Stage-50 validation, schema-qualified
> runtime access, environment-owned migration/runtime secret references, local migration reuse,
> and mandatory post-restore refresh-state invalidation. Target execution and qualification remain
> operational prerequisites.

---

## 1. Context

ADR-034 requires production Identity to use the PostgreSQL `RefreshTokenStore`. The
implemented adapter stores SHA-256 hashes of refresh-token and family identifiers,
atomically rotates a token, revokes a family on reuse, and checks family activity.
Production configuration rejects the in-memory adapter, non-TLS PostgreSQL transport,
blank credentials, and the local-development credential.

The only current structural definition is
`tools/seed-data/postgres/007_identity_refresh_tokens.sql`. It creates
`identity_refresh_token_families`, `identity_refresh_tokens`, an index, and a local
`emg_identity_app` role with a committed local-only password. ADR-041 explicitly says
seed data is not production migration authority and permits bootstrap to create only
roles governed by accepted architecture. Its closed role list and migration streams
cover Audit, Audit Projector, and Knowledge Graph, not Identity.

The Identity Deployment already receives an environment-owned
`EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN`, but no governed authority creates its role,
schema, objects, grants, migration history, or pre-start validation. Using the seed SQL
in a target environment would make a development password and an ungoverned DDL path
production authority.

## 2. Scope and non-supersession

This ADR governs only durable Identity refresh-token PostgreSQL placement, roles,
schema, objects, migration history, bootstrap order, credentials, legacy-seed adoption,
validation, backup, and recovery. It does not change token claims, token lifetime,
rotation or reuse semantics, login, delegation, authorization, Keycloak topology, Audit
semantics, or any other Identity persistence.

It extends ADR-041 by governing two additional roles and one isolated migration stream.
It neither supersedes nor relaxes ADR-041. Until this ADR is accepted, ADR-041's existing
five-role boundary remains authoritative and implementation is not authorized.

## 3. D-1 — Database placement

Identity durable refresh state SHALL use the existing environment's EMG PostgreSQL
database and SHALL be isolated in a dedicated `emg_identity` schema. It SHALL NOT use
the Knowledge Graph or Audit migration history, schema ownership, or runtime role.

A separate Identity database is rejected for V1. It would add an independent database
provisioning, availability, backup/PITR, restore-order, monitoring, and credential
boundary without improving the application-level token secrecy already provided by
hash-only storage and dedicated roles. Co-placement retains the governed PostgreSQL
backup/recovery path and current single DSN endpoint while schema ownership, grants,
credentials, and migration history provide the required separation.

Co-placement does not authorize cross-schema access. A future separate database may be
adopted only through an accepted amendment with migration, recovery, and cutover rules.

## 4. D-2 — Production roles and attributes

The Platform Database Bootstrap Administrator SHALL create and converge exactly these
additional `LOGIN` roles under ADR-041's role lifecycle:

| Role | Authority |
| :--- | :--- |
| `emg_identity_migrator` | Own the `emg_identity` schema, Identity migration history, tables, constraints, and indexes; apply the Identity migration stream |
| `emg_identity_app` | Identity runtime access to the closed refresh-state object set only |

Both roles SHALL be `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
NOREPLICATION NOBYPASSRLS`. Neither may receive `cloudsqlsuperuser`, another provider
administrator role, or membership in another EMG role. Managed-provider convergence
and verification SHALL follow ADR-041's accepted fail-closed rule.

`emg_identity_migrator` SHALL NOT create roles or databases. Bootstrap SHALL create the
`emg_identity` schema owned by `emg_identity_migrator`, revoke `CREATE` from PUBLIC,
and leave the migrator able to create and alter objects only through ownership of that
schema and its Identity objects. The runtime role SHALL own no object and migration
history SHALL not be accessible to it.

## 5. D-3 — Authoritative schema

After implementation, the sole production structural authority SHALL be the packaged
Identity PostgreSQL migration stream in `emg-persistence`. Its initial migration SHALL
establish exactly:

```text
emg_identity.identity_refresh_token_families
  family_hash  TEXT PRIMARY KEY
  created_at   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
  revoked_at   TIMESTAMPTZ NULL

emg_identity.identity_refresh_tokens
  token_hash   TEXT PRIMARY KEY
  family_hash  TEXT NOT NULL
               REFERENCES emg_identity.identity_refresh_token_families(family_hash)
  status       TEXT NOT NULL CHECK status IN ('active', 'rotated', 'revoked')
  expires_at   TIMESTAMPTZ NOT NULL
  rotated_at   TIMESTAMPTZ NULL

idx_identity_refresh_tokens_family
  BTREE (family_hash)
```

The foreign key SHALL use PostgreSQL's default non-cascading delete behavior. No
sequence is required. `emg_identity_migrator` SHALL own the schema, both tables, their
constraints and index, and the migration-history table. Runtime application SQL SHALL
address the dedicated schema deterministically; it SHALL NOT depend on a mutable ambient
`search_path` controlled by a caller.

The schema stores hashes and lifecycle state only. It carries no raw token, password,
tenant-supplied authority, or browser session material.

## 6. D-4 — Runtime least privilege

`emg_identity_app` SHALL receive:

- `USAGE` on schema `emg_identity`;
- table `SELECT` and `INSERT` on both refresh-state tables;
- column-scoped `UPDATE (revoked_at)` on `identity_refresh_token_families`; and
- column-scoped `UPDATE (status, rotated_at)` on `identity_refresh_tokens`.

It SHALL NOT receive `DELETE`, `TRUNCATE`, schema `CREATE`, table-wide `UPDATE`, DDL,
ownership, migration-history access, sequence privileges, cross-schema grants, role
creation, or database creation. PUBLIC SHALL receive no privilege on the schema or
tables. Grants SHALL be explicit; `ALL TABLES IN SCHEMA` and broad default privileges
are prohibited.

`DELETE` and `TRUNCATE` are denied because runtime rotation and reuse handling require
only inserts and lifecycle updates. Destructive removal is not a serving responsibility,
could erase replay evidence, and has no accepted retention contract. Any future purge
requires a separately governed retention decision and bounded maintenance authority.

## 7. D-5 — Identity migration stream

Identity migrations SHALL form a distinct packaged PostgreSQL stream:

- directory: `emg_persistence/migrations/identity_postgres/`;
- numbering: independent `V001`, `V002`, ... inside that directory;
- history: `emg_identity.identity_schema_migrations`;
- runner/executor: the existing `emg-persistence` discovery, checksum, transactional
  runner, and PostgreSQL executor;
- DSN: `EMG_IDENTITY_MIGRATION_POSTGRES_DSN`, authenticating exactly as
  `emg_identity_migrator`; and
- runtime DSN: `EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN`, authenticating exactly as
  `emg_identity_app`.

Identity version numbers SHALL NOT share or collide with the Knowledge Graph default or
Audit streams. Migration execution SHALL be one-shot and complete before Identity
serving startup. Checksum mismatch, dirty state, wrong role, wrong schema, or incomplete
history SHALL halt deployment.

## 8. D-6 — Clean creation and legacy adoption

For a clean database or one without Identity tables, bootstrap SHALL create/converge the
roles and owned schema, and Identity V001 SHALL create the objects and grants.

For a database containing the two exact old local-seed tables in the default schema,
bootstrap MAY adopt them only when all of the following hold:

1. both tables exist and neither is missing;
2. columns, types, nullability, defaults, primary keys, foreign key, status check, and
   family index exactly match D-3;
3. no conflicting `emg_identity` object or partial Identity migration history exists;
4. the operation can transactionally move both tables into `emg_identity`, transfer
   ownership to `emg_identity_migrator`, revoke prior/PUBLIC privileges, and preserve
   rows, object identity, constraints, and index; and
5. post-adoption validation proves the D-3/D-4 contract before V001 is recorded.

Adoption SHALL NOT drop, recreate, truncate, rewrite, repair, or silently coerce data or
structure. A partial, divergent, ambiguously owned, or non-transactionally adoptable
installation SHALL fail closed and require an operator-reviewed remediation plan.

The V001 implementation SHALL safely recognize an already adopted exact structure and
record it through the normal migration transaction without maintaining a second DDL
definition.

## 9. D-7 — Local-development seed disposition

`tools/seed-data/postgres/007_identity_refresh_tokens.sql` SHALL cease to define tables,
constraints, indexes, or production-like grants. Local orchestration MAY retain a
clearly local-only `emg_identity_app` credential/bootstrap wrapper, but it SHALL invoke
or consume the packaged Identity migration through the same migration runner used by
production. There SHALL be one structural definition: Identity V001.

No local credential may enter an image, resolved target bundle, migration, ConfigMap,
release evidence, or target secret value. Production validation SHALL continue to
reject blank, non-TLS, wrong-role, or `local_dev_only` refresh DSNs.

## 10. D-8 — Bootstrap and rollout order

The governed order SHALL be:

1. the existing EMG PostgreSQL database and environment secret integration exist;
2. the Platform Database Bootstrap Administrator creates/converges
   `emg_identity_migrator` and `emg_identity_app` and creates the owned
   `emg_identity` schema, performing exact legacy adoption if applicable;
3. separate environment-owned migration and runtime credentials are delivered through
   the established Secret/ExternalSecret boundary;
4. the one-shot Identity migration Job runs the isolated Identity stream as
   `emg_identity_migrator`;
5. Stage-50 validation verifies migration history, schema, objects, ownership,
   constraints, index, effective role attributes, exact grants, denied destructive/DDL
   operations, DSN role separation, and absence of development credentials;
6. only after every preceding result is explicit PASS may the Identity serving workload
   start; and
7. post-deployment qualification verifies readiness, login/register/rotation/reuse,
   fail-closed datastore loss, Audit behavior, and recovery behavior without retaining
   tokens or credentials.

This extends ADR-041's stage model. It does not change the ordering or authority of the
existing Audit, Projector, Knowledge Graph, or Keycloak steps. Implementations SHALL
assign an unambiguous pre-serving stage to the Identity migration and SHALL prevent
Identity rollout when Stage-50 Identity validation is absent or indeterminate.

## 11. D-9 — Credential contract

Migration and runtime credentials SHALL be distinct, independently rotatable,
environment-owned values. Repository manifests SHALL contain references only. The
environment's approved secret-management integration owns generation, custody, access,
materialization, and rotation. Rotation SHALL preserve logical role names and SHALL NOT
recreate schema objects or expand grants.

The bootstrap administrator credential SHALL remain separate from both Identity roles.
The migration credential SHALL not be mounted into the serving Deployment. The runtime
credential SHALL not be mounted into the migration Job. DSNs, passwords, and tokens
SHALL NOT appear in logs, validation output, release evidence, ADRs, or Git.

## 12. D-10 — Backup, recovery, and security

Because Identity state is co-located in the governed EMG PostgreSQL database, ADR-039
physical backup, WAL, manifest, encryption-wrapper, remote-custody, retention, and PITR
requirements SHALL include the `emg_identity` schema and Identity migration history.
Backup verification SHALL fail if either table or the Identity history is absent.

A point-in-time restore can resurrect a token that was rotated or a family that was
revoked after the selected recovery point. Therefore Identity SHALL remain stopped or
not ready after restore until an authorized recovery step invalidates all restored
refresh families and tokens, after which users must authenticate again. This invalidation
SHALL be an explicit, audited recovery operation using migration/recovery authority, not
an application-runtime `DELETE` or `TRUNCATE`. Implementing and testing that operation is
required before target recovery qualification; this ADR does not claim it already exists.

Database and backup transport/encryption SHALL follow existing production TLS and
ADR-039 encryption/custody requirements. Refresh state SHALL remain hash-only. Database
unavailability, migration uncertainty, wrong ownership, or validation failure SHALL fail
closed: production Identity SHALL not fall back to memory, and operations requiring
durable refresh state SHALL not claim success.

Refresh rows contain security state shared by all tenants but no caller-controlled tenant
authority. Only Identity runtime and the governed migration/recovery authorities may
access them. Administrative adoption, migration, restore invalidation, credential
rotation, and validation outcomes SHALL be auditable without exposing hashes or DSNs.

## 13. D-11 — Required validation

Repository and live qualification SHALL prove at minimum:

- exact stream discovery, numbering, checksum, history namespace, and idempotency;
- clean V001 creation and exact non-destructive legacy adoption;
- table, column, default, constraint, foreign-key, index, schema, and ownership state;
- role attributes and strict migrator/runtime/admin separation;
- successful family creation, token insertion, rotation, activity check, and reuse
  revocation through `emg_identity_app`;
- denial of runtime `DELETE`, `TRUNCATE`, DDL, schema creation, ownership change,
  migration-history access, and unauthorized column updates;
- rejection of wrong-role, shared, blank, non-TLS, and local-development DSNs;
- bootstrap, migration, Stage-50, Deployment, and ExternalSecret reference consistency;
- backup inclusion, isolated restore, mandatory post-restore invalidation, and re-login;
  and
- no secret material in source, images, manifests, logs, or retained evidence.

Mocked SQL inspection alone is insufficient for privilege, adoption, rotation, and
recovery claims. Those require environment-gated real PostgreSQL tests.

## 14. Implementation consequences after acceptance

The RC.9 implementation SHALL be a separate change containing only the minimum required:

1. packaged `identity_postgres/V001` and Identity stream/history helpers;
2. bootstrap role/schema/adoption integration and CLI inputs;
3. one-shot Identity migration Job and separate migration DSN secret reference;
4. Stage-50 database validation and production manifest/ExternalSecret consistency;
5. schema-qualified Identity adapter SQL;
6. local seed reduction to credential/bootstrap wrapper with no structural DDL;
7. unit and real PostgreSQL migration, adoption, privilege, rotation/reuse, recovery,
   configuration, manifest, and validation tests;
8. backup manifest/verification inclusion and post-restore invalidation tooling; and
9. administrator, recovery, provisioning, service, and RC.9 documentation updates.

No application endpoint, token semantic, database vendor, secret provider, deployment
component, or product feature is authorized.

## 15. Consequences and rejected alternatives

### Consequences

- Identity refresh state gains one authoritative schema and migration stream.
- Runtime compromise cannot destroy refresh evidence or alter DDL.
- The existing database and recovery pipeline gain Identity security-state obligations.
- Recovery intentionally invalidates restored refresh sessions to prevent token reuse
  across the recovery boundary.
- RC.9 requires a migration-set change, rebuilt images/evidence, and complete staging,
  rollback, recovery, and authenticated qualification.

### Rejected alternatives

- **Execute seed SQL in staging:** rejected because it embeds a development password and
  is not migration authority.
- **Put Identity tables in the Knowledge Graph or Audit stream:** rejected because it
  creates ownership/history collisions and cross-service authority.
- **Use one migrator/runtime role:** rejected because runtime DDL/ownership violates
  least privilege.
- **Separate Identity database for V1:** rejected for the additional operational and
  recovery boundary described in D-1.
- **Allow runtime DELETE/TRUNCATE:** rejected because serving semantics do not require
  them and deletion would erase replay evidence.
- **Automatically recreate or coerce legacy tables:** rejected because it risks silent
  data loss and unverifiable adoption.

## 16. Acceptance gate

Before acceptance, the Decision Authority SHALL confirm the co-located database choice,
dedicated schema and roles, exact grants, destructive-operation denial, recovery-wide
family invalidation, and ADR-041 extension. Acceptance SHALL record a decision date using
the repository convention. Only then may implementation begin.

---

## Amendment 1 — Replay-resistant recovery freshness authority

**Amendment status:** Accepted
**Amendment decision date:** 2026-08-14
**Proposed:** 2026-08-14
**Revised:** 2026-08-14, in response to independent review findings P0-A (external authority
rollback protection) and P0-B (enforceable recovery fencing); further revised 2026-08-14 in
response to a second independent review's fence-release-ordering and network-fence-enumeration
findings; further revised 2026-08-14 in response to a third independent review's network-fence
readiness contradiction and unverified-provider-capability findings; further revised 2026-08-14 in
response to a fourth independent review's finding that mechanism 3b was not a linearizable
serialization primitive; accepted 2026-08-14 after a fifth independent review found no remaining
material architecture, concurrency, replay, fencing, recovery, or privilege gap
**Decision authority:** Project Architect
**Effect before acceptance:** None; superseded by acceptance. This amendment now carries the same
authority as the base ADR-043 decision. Implementation remains a separate, subsequent review,
consistent with Section 14's implementation-consequences contract and this amendment's own A13
gate; this acceptance authorizes proceeding to that implementation review, not target execution
itself.

**Review disposition.** The first independent architecture/security review did not accept this
proposal. It found the external authority's non-reuse requirement (A3, prior text) normative but
unenforced — a mutable value with a "never reuse" policy statement, not a rollback-resistant
mechanism (**P0-A**) — and found the fencing discussion (prior A3/A9) descriptive of intent
without a named fence owner, without required positive evidence per fence, and without a
distinct database-session fence (**P0-B**). This revision closes both findings by requiring the
Approved Recovery Authority to provide platform-guaranteed monotonic, non-reused version history
plus a serialized-rotation guarantee (A3, A3.1, A3.2), by carrying that authority revision
alongside the generation everywhere the generation is compared (A3.3, A4, A5, A6, A8), and by
adding a dedicated four-part recovery fencing protocol with a named owner and mandatory positive
evidence per fence (A9). It does not change D-1 through D-11, the runtime least-privilege grants
(D-4), reconciliation atomicity's transactional core (A6), or any already-accepted contract.

A second independent review found the redesign sound but identified two remaining explicitness
gaps: the fence-release conditions (prior A9.6) did not state an explicit, ordered sequence, and
the network fence (A9.4) lacked the same explicit failure-mode and adversarial-test treatment
already given to the workload and database-session fences. This was remediated by making fence
release an explicit ordered gate and by extending A9.7/A12 with parallel network-fence failure and
test coverage.

A third independent review found two further material defects. First, A9.4 and the fence-release
sequence (A9.6) contradicted each other: A9.4 restricted recovery-target network reachability to
governed recovery/migration actors only, while A9.6 simultaneously required the freshly started
Identity workload — which authenticates as `emg_identity_app`, never as `emg_identity_migrator` —
to independently query that same target to prove readiness, with no stated exception. Second, A3's
claim that GCP Secret Manager, AWS Secrets Manager, and HashiCorp Vault's KV v2 engine all natively
satisfy the complete five-capability contract was unverified and does not hold: AWS Secrets
Manager's `VersionId` is an opaque, unordered identifier with no native conditional-write
primitive and satisfies neither capability 2 nor capability 3; GCP Secret Manager satisfies
capabilities 1, 2, 4, and 5 but its `AddSecretVersion` operation has no conditional-write
precondition and does not natively satisfy capability 3 as originally worded. This revision
resolves both findings without introducing any new platform component: A9.4 is split into an
explicit two-phase network fence (a reconciliation-fence phase restricted to recovery/migration
actors; a separately evidenced readiness-qualification-fence phase admitting only the freshly
started Identity workload identity, which still falls short of restoring client service), with the
phase transition made its own evidenced step in A9.6; and A3 capability 3 is restated as a required
security property — serialized rotation with fail-closed conflict detection — satisfiable either by
an authority's native atomic conditional write (Vault KV v2's `cas` parameter) or, where
unavailable, by a documented read-verify-after-write detection procedure built only from the
already-required immutable/monotonic/queryable history capabilities (GCP Secret Manager). AWS
Secrets Manager is removed as a qualifying example; it does not meet the capability contract under
either mechanism.

A fourth independent review FAILED this revision on the concurrent-rotation control itself. It
found that the read-verify-after-write procedure just described as "mechanism 3b" does not
establish a linearization point: the predecessor check it depends on requires strongly consistent
(linearizable) reads of the authority's ordered version history immediately after a concurrent
write, but capability 4 as worded never required that consistency strength, and authoritative GCP
Secret Manager documentation confirms the service does not provide it — Secret Manager's documented
strong-consistency guarantee covers only adding a version and then directly accessing that exact,
already-known version number; listing or ordering the version history, which the predecessor check
requires, is documented as only eventually consistent. Under that documented behavior, two
coordinators reading the same predecessor can each independently observe a stale ordering and each
conclude their own write was the accepted transition — the coordinator-level equivalent of two
conflicting transitions both being treated as successful, which capability 3 exists to prevent.
Eventual detection of the resulting mismatch (by A6's pre-commit re-check or A8's live-pair equality
requirement) is not equivalent to preventing the belief from arising, and neither was offered as the
primary concurrency control. The review also found no adversarial test for a coordinator crashing
between mechanism 3b's unconditional write and its post-write verification. This revision resolves
both findings by redefining capability 3 as a strict single-linearization-point requirement (A3);
restricting mechanism 3a to genuine provider-native atomic conditional writes (unchanged in
substance, now stated more precisely, with an explicit history-retention-configuration condition);
restricting mechanism 3b to a genuine alternative provider-native serialization primitive — an
atomic lease, exclusive lock, or conditional metadata transition — and removing the read-verify-
after-write procedure as a qualifying mechanism in its own right; removing the claim that GCP Secret
Manager alone qualifies as an Approved Recovery Authority for concurrent generation rotation (it now
qualifies only if paired with a separately governed native serialization primitive, which this
revision does not select, invent, or authorize); adding an explicit eight-property authority
qualification gate; rewriting the rotation algorithm (A3.2) around a single atomic accept/reject
step with explicit crash semantics for every stage of rotation; and extending A12 with adversarial
tests for the authority-rotation layer, including dual-writer races and every named rotation crash
point. It introduces no new EMG platform component, does not make PostgreSQL a freshness or lock
authority, and does not invent a distributed lock service. It does not change A2, A4, A9, A10, A11,
D-1 through D-11, or any other already-independently-passed contract.

A fifth independent review confirmed the redefined capability 3, the redefined mechanisms 3a and
3b, the authority qualification gate, the rewritten A3.2 rotation algorithm and its A3.2.1 crash
semantics, and the extended A12 adversarial-test contract each hold under adversarial analysis of
the same-predecessor dual-writer race (both interleavings), every named authority-rotation crash
point, and independent verification against authoritative provider documentation. It confirmed no
regression in any previously-passing area (A1–A2, A4–A11) and found no material architecture,
concurrency, replay, fencing, recovery, or privilege gap remaining. It confirmed GCP Secret Manager
alone does not qualify and is not treated as qualifying anywhere in this document, that any future
GCP-plus-external-primitive qualification remains an undecided possibility rather than a selected
component, and that Vault KV v2 qualifies only conditionally on explicit history-retention
configuration. Amendment 1 is accepted on this basis. Implementation of the two outstanding P0
remediations (exact legacy-adoption security-state validation, already clarified as required by
accepted D-6 in A11; and this amendment's replay-resistant recovery-freshness protocol) remains a
separate, subsequent implementation review, per Section 14's implementation-consequences contract
and this amendment's own A13 gate; this acceptance authorizes that review to proceed, not target
execution itself.

### A1. Context and subordinate scope

D-10 requires Identity to remain stopped or not ready after a physical restore or PITR until
all restored refresh state is invalidated. A completion marker stored only in PostgreSQL cannot
prove that property: restoring PostgreSQL restores both historical refresh rows and the marker
that previously described those rows as safe.

This amendment supplies the missing recovery-freshness protocol. It is subordinate to ADR-043
because it governs only the pre-serve recovery invariant of the same Identity schema, roles,
migration stream, readiness boundary, and recovery operation. It creates no independent product,
deployment, database, provider, or secret-management boundary and therefore does not warrant a
new ADR.

The core invariant is:

> After any governed physical restore or PITR, no Identity instance may become ready or serve
> refresh-token operations until all restored refresh families and tokens have been invalidated
> and PostgreSQL records satisfaction of a recovery generation that was established outside,
> and was not rolled back with, the restored database.

No state restored solely from PostgreSQL may attest to PostgreSQL's current recovery freshness.

### A2. Alternatives evaluated

| Authority | Decision | Analysis |
| :--- | :--- | :--- |
| PostgreSQL recovery/timeline identity | Rejected as sole authority; retain as recovery evidence | Timeline and recovery metadata are database-local/provider-sensitive, are restored with or derived from the recovered cluster, and do not portably distinguish every full-copy restore. They cannot alone establish a value that did not roll back with PostgreSQL. |
| Environment-governed recovery generation bound to the authority's own monotonic version history | **Selected** | A fresh, non-reused generation is established in the environment's existing external configuration/secret-management control plane before a recovered database can be exposed to Identity. Non-reuse is enforced structurally, not merely by policy: the approved authority MUST expose an immutable, monotonically-numbered version history per object (A3), and the generation's accompanying authority revision is that platform-assigned version identifier, which the platform itself never decreases or reassigns. It survives database rollback because neither the generation nor its revision is stored in PostgreSQL backup/WAL. Missing, malformed, stale, non-monotonic, or mismatched state fails readiness closed. |
| Kubernetes-owned ConfigMap/annotation | Rejected as system of record | These are deployment inputs, not a rollback-protected authority; Git/Kubernetes rollback or object recreation could replay an old value. Kubernetes may materialize the authoritative value, but may not originate it or be its system of record. |
| Provider restore metadata | Rejected as normative authority | It can strengthen evidence but is not portable across managed PostgreSQL and self-managed recovery, and its identity/authenticity semantics vary by provider. |

### A3. External Recovery Generation Authority

Each environment SHALL maintain one current **Identity Recovery Generation** in one **Approved
Recovery Authority**: an administratively controlled external configuration/secret-management
system that provides, for the specific object holding the generation, all of the following
capabilities. A system lacking any of these capabilities is not an Approved Recovery Authority
for this purpose, regardless of its use elsewhere in the environment:

1. **Immutable, append-only version history.** Every value ever written to the object is
   retained and individually addressable; no prior version's content may be edited, and no
   version identifier may be reassigned to different content.
2. **Monotonically advancing, non-reused version identifiers.** Each write is assigned a version
   identifier from a strictly increasing, platform-managed sequence for that object. The
   platform itself — not application logic — SHALL guarantee that no version identifier is ever
   issued twice and that the sequence never decreases, including after the deletion, disabling,
   or destruction of any version.
3. **Serialized rotation with a single linearization point.** For any transition `(N, Rn) →
   (N+1, Rn+1)`, the Approved Recovery Authority itself SHALL provide exactly one authoritative
   linearization point at which it atomically determines whether `Rn` is still the object's current
   version identifier and, from that single determination, either accepts the transition (creating
   `Rn+1` as the new current version) or rejects it. Two competing transitions proposed against the
   same predecessor `Rn` SHALL NOT both be accepted; once one is accepted, every other transition
   against that same `Rn` SHALL be rejected by the authority itself — not merely detected as
   conflicting after each has already been independently treated as successful by its own
   coordinator. Detection performed only after both transitions have already been treated as
   successful is insufficient. Read-after-write verification of the object's version history, by
   itself, is insufficient: such a read is not the linearization point, and a strongly consistent,
   single-object read-after-write guarantee is not implied by capabilities 1, 2, or 4 alone (version
   immutability, monotonic numbering, and mere queryability do not by themselves establish that a
   history read immediately reflects a concurrent writer's write). An administrative assumption that
   only one recovery coordinator will run at a time is also insufficient; this capability SHALL be
   satisfied by the platform itself, not by process discipline or RBAC scoping alone (capability 5
   governs who may act, not how concurrent acts are serialized). The platform SHALL support at least
   one of the following mechanisms, for the specific object holding the generation, sufficient to
   provide this property:
   - **mechanism 3a — native atomic conditional writes:** creating a new version only if the
     object's current version identifier equals a caller-supplied expected value (compare-and-set or
     an equivalent optimistic-concurrency primitive), with the authority atomically and exclusively
     accepting at most one of any competing writes conditioned on the same expected value and
     rejecting every other. The accepted write's atomic acceptance by the authority is the
     linearization point; or
   - **mechanism 3b — an alternative native serialization primitive:** a documented, provider-native
     mechanism, distinct from version creation itself, that establishes the identical single
     linearization point for the specific object holding the generation — for example a provider-
     native atomic lease, an exclusive lock, or an atomic compare-and-set on a separate
     authority-owned metadata object that gates which version-creation call is permitted to proceed.
     The coordinator SHALL acquire or win that primitive before, and as the sole precondition for,
     creating the new version; the primitive's own atomic accept/reject decision — not any
     subsequent read of the version history — is the linearization point. A procedure consisting of
     an unconditional version-creation write followed by re-reading the object's version history to
     infer which of two concurrent writers "won" does NOT qualify as mechanism 3b under this
     capability, regardless of how the history is ordered or how soon after the write it is read,
     because no step in that procedure is an authority-side atomic accept/reject decision against a
     caller-supplied expected predecessor — it is detection, performed after the fact, not
     serialization.

A provider possessing capabilities 1, 2, 4, and 5 but no primitive satisfying mechanism 3a or a
qualifying mechanism 3b does NOT satisfy capability 3 and therefore is NOT an Approved Recovery
Authority for concurrent generation rotation, regardless of how the other four capabilities might
otherwise recommend it.

4. **Queryable version history.** The full ordered list of version identifiers and their
   creation time SHALL be retrievable by the governed recovery tooling for audit and for the
   pre-rotation non-reuse check in A3.2. Retrievability alone does not establish the read
   consistency required for any security decision made from that history; A3.1's rollback/replay
   comparison and A3.2's non-reuse check SHALL be made only against a read whose consistency
   guarantee is affirmatively documented for the specific operation used, not assumed from this
   capability's presence.
5. **Independent, RBAC/audit-governed mutation.** Existing environment RBAC, approval, and audit
   controls SHALL restrict who may create a new version, distinct from and independent of
   Identity's own runtime identity and privileges. This capability governs authorization, not
   concurrency; it does not substitute for capability 3.

**Authority qualification gate.** Before any external system, in a specific configuration, may be
used as the Approved Recovery Authority for the recovery-generation object, provisioning/release
governance SHALL prove, and record evidence for, all of the following. Failure to prove any one
property means the system/configuration is NOT an Approved Recovery Authority for this purpose:

1. immutable or rollback-protected version history (capability 1);
2. monotonic, non-reused revision semantics (capability 2);
3. generation-reuse detection derived from that history (A3.2 step 2);
4. rollback/replay detection derived from that history (A3.1);
5. a documented, provider-native single linearization point for rotation (capability 3, satisfied by
   mechanism 3a or a qualifying mechanism 3b as defined above);
6. that competing transitions proposed against the same predecessor cannot both be accepted by that
   linearization point;
7. that the history retention required by capabilities 1 and 4 is explicitly configured and
   preserved for at least the environment's required recovery/audit retention window, not left at an
   unexamined provider default; and
8. that every read used to make a security decision under A3.1, A3.2, A4, or A8 carries the
   consistency guarantee its use requires, as affirmatively documented for that specific operation.

This gate applies once, at qualification/provisioning time, for each environment and each Approved
Recovery Authority object; it is independent of, and in addition to, the per-rotation procedure in
A3.2. An Approved Recovery Authority that fails this gate SHALL NOT be referenced by any
environment's recovery configuration, and any existing reference to a system that fails this gate
is itself a fail-closed condition equivalent to a missing authority (A3.3, A8).

Independent verification against authoritative provider documentation for the two providers named
elsewhere in EMG's environment inventory establishes the following, as of this revision. HashiCorp
Vault's KV v2 engine satisfies capability 3 natively via its documented `cas` write parameter
(mechanism 3a): the write is conditioned on the caller-supplied expected current version, the
backend atomically accepts or rejects it, and the accepted write is the linearization point. Vault
KV v2 qualifies as an Approved Recovery Authority only when its deployment configuration also
satisfies capability 1's and capability 4's retention requirement: KV v2 retains a bounded number of
versions per key, governed by the `max-versions` configuration (`0` meaning unlimited), and permits
versions to be permanently destroyed; deployment SHALL set `max-versions` and the
delete-version-after policy for the recovery-generation object so that the complete version history
required for non-reuse detection (A3.2 step 2) and rollback/replay detection (A3.1) is preserved for
at least the environment's required recovery/audit retention window. A provider left at a default
that silently prunes history does not satisfy capability 1 or capability 4 regardless of the `cas`
parameter's correctness, and therefore does not pass the qualification gate. GCP Secret Manager
provides capabilities 1, 2, 4, and 5 natively — its version numbers are monotonic, non-reused
integers, and destroyed versions are never reissued — but independent verification of authoritative
Google documentation confirms its `AddSecretVersion` operation carries no expected-current-version
precondition of any kind (no ETag or other conditional-write parameter is honored on that call), and
its documented strong-consistency guarantee is narrower than any read-verify procedure would
require: only "add a version, then access that exact version by its own version number" is
guaranteed strongly consistent; listing or ordering the version history — the operation any
read-after-write procedure would depend on to infer a predecessor — is documented as eventually
consistent. GCP Secret Manager therefore has no known native primitive satisfying mechanism 3a, and
no read-verify procedure built from its documented consistency guarantees can satisfy mechanism 3b
as defined above. **GCP Secret Manager ALONE does NOT qualify as an Approved Recovery Authority for
concurrent generation rotation and does NOT pass the qualification gate.** GCP Secret Manager could
qualify only if paired with a separately governed, provider-native or independently provisioned
serialization primitive that itself supplies the missing linearization point (for example, some
other atomic lease or lock service gating AddSecretVersion calls for the specific object); this
amendment does not select, invent, evaluate, or authorize any such component, and until one is
separately proposed and independently reviewed against the qualification gate above, GCP Secret
Manager is not an Approved Recovery Authority under this contract. AWS Secrets Manager continues to
not qualify, for the reasons already established: its `VersionId` is an opaque, randomly-assigned
identifier with no platform-guaranteed ordering, so it satisfies neither capability 2 nor capability
3 by any mechanism. A provider is deliberately not selected by this amendment; any environment-
approved system independently proven, under the qualification gate above, to meet all required
capabilities — via mechanism 3a or a qualifying mechanism 3b — qualifies. Repository manifests may
contain only a reference to the object, never its content.

#### A3.1 Generation and authority revision

The **generation** is a newly generated, globally unique, opaque value of at least 128 bits,
encoded as a canonical lowercase UUID, written as the content of a new version of the Approved
Recovery Authority object. The generation value alone is not confidential and SHALL NOT be
treated as an authentication credential; its integrity and freshness are security-sensitive.

The **authority revision** is the version identifier the Approved Recovery Authority itself
assigns to the version currently holding the current generation — never a value invented,
computed, or assigned by Identity, the recovery coordinator, or any application code. A
generation and its authority revision are always handled as one inseparable pair: `(generation,
authority_revision)`.

**Revision ordering.** Authority revision `R2` is newer than `R1` if and only if the Approved
Recovery Authority's own version sequence orders `R2` after `R1` (for an integer sequence, `R2 >
R1`). This ordering is structural and platform-guaranteed (A3 capability 2), not inferred from
generation content, wall-clock time, or PostgreSQL timeline/LSN identifiers.

**Rollback/replay detection.** A candidate `(generation, authority_revision)` pair is accepted as
current only when the authority revision equals the Approved Recovery Authority's own
currently-reported latest version identifier for that object. Any pair whose authority revision
is lower than the highest revision ever recorded in the object's queryable history (A3 capability
4) is a **detected rollback/replay** — regardless of whether its generation happens to be
textually novel or a repeat — and SHALL be rejected and logged as a security event by any
governed component that observes it, never merely treated as an ordinary mismatch.

#### A3.2 Rotation and non-reuse enforcement

The authorized recovery coordinator SHALL rotate the generation by:

1. reading the Approved Recovery Authority's current authoritative version identifier and full
   version history for the object (A3 capability 4);
2. validating that history against A3.1's rollback/replay detection and confirming no
   indeterminate authority state exists;
3. generating a fresh candidate UUID and confirming, from that history, that its exact value has
   never appeared as the content of any prior version (non-reuse check);
4. invoking the Approved Recovery Authority's mechanism-3a or qualifying mechanism-3b
   serialization primitive (A3 capability 3), supplying the version identifier read in step 1 as
   the expected current predecessor, to attempt to create a new version containing the candidate
   generation;
5. the authority — at its own single linearization point (A3 capability 3) — atomically accepts or
   rejects this transition; this atomic accept/reject decision, and nothing read before or after
   it, is the sole concurrency control;
6. if rejected — a **concurrent rotation conflict** — the coordinator SHALL abort this attempt,
   re-read the now-current authoritative state, and either resume as a fresh attempt from step 1
   against that new state or halt and report; it SHALL NOT retry blindly against the stale expected
   value that was just rejected, and SHALL NOT treat its own rejected attempt as authoritative,
   reference it from any materialization, or supply it to a reconciliation transaction (A6);
7. if accepted, the coordinator captures the authority's own response as the newly authoritative
   `(generation, authority_revision)` pair — the version identifier the authority itself assigned,
   never a value computed, inferred, or assumed by the coordinator;
8. the coordinator independently re-reads the authority's current state and version history as
   defense-in-depth verification that the accepted pair is free of corruption or unexpected
   rollback evidence; this step verifies the outcome of step 5 and SHALL NOT be treated as the
   mechanism that decided the outcome;
9. the coordinator materializes the resulting pair through the existing governed delivery path
   (A3.3); and
10. recovery proceeds past this point only after the coordinator has positively confirmed, per
    A3.3 and A9, that materialization and controller synchronization are proven — never assumed
    from the passage of time.

The authority's atomic acceptance at step 5 is the single linearization point required by A3
capability 3. Step 8 is verification and defense-in-depth; it is not, and does not substitute for,
the concurrency control performed at step 5.

This makes concurrent rotations mutually exclusive by construction, not merely in effect: the
authority itself accepts at most one competing transition against a given expected predecessor and
rejects every other, at the single linearization point of step 5, regardless of whether the
qualifying mechanism is 3a or 3b. The losing coordinator's rejection is delivered by the authority
at the moment of its own attempt — not inferred afterward from an independent comparison of
separately-read state — and fails closed rather than silently overwriting, racing, or reconciling
PostgreSQL against an unverified pair. Throughout this amendment, references to a "CAS-protected"
rotation or pair denote a rotation performed via mechanism 3a or a qualifying mechanism 3b; both
provide the identical normative guarantee of A3 capability 3 because both are decided at a single
authority-side linearization point, never by post-hoc detection alone.

The authorized recovery coordinator SHALL rotate the generation **before** a restored PostgreSQL
target is reachable by any Identity serving workload, per the A9 fencing protocol. A restore
performed without first rotating the authority is an unauthorized recovery and SHALL NOT be
eligible for traffic release. Backup selection or application rollback SHALL NOT rotate the
generation; only clean-environment initialization and a physical database restore/PITR establish
a new generation.

#### A3.2.1 Authority-rotation crash semantics

The coordinator, the network between the coordinator and the Approved Recovery Authority, and the
authority's own client-visible response may each fail independently at any point in A3.2. No such
failure may cause generation reuse or an uncontrolled second rotation. At minimum:

- **Crash before the step 5 linearization decision.** No new authoritative generation exists; the
  object's current version identifier is unchanged from what step 1 read. Recovery MAY safely
  restart from A3.2 step 1 by reading the (unchanged) authoritative state.
- **Crash after the authority accepts the transition (step 5) but before the coordinator records or
  observes that response.** The coordinator SHALL NOT create another generation blindly. On restart
  or replacement, it SHALL first read the authority's current state and version history (A3
  capability 4) and determine, from that history alone, whether the candidate UUID it had generated
  already appears as the content of a version. If so, that accepted transition is the current
  authoritative pair, and the resumed coordinator SHALL adopt it (proceeding from step 8) rather
  than attempt a new rotation. If the outcome cannot be determined from the authority's own state,
  the ambiguity is an indeterminate state; recovery SHALL fail closed and halt for operator review
  rather than attempt a new rotation against a possibly-already-superseded predecessor.
- **Crash after a successful authority transition (step 5) but before materialization (step 9).**
  Recovery remains fenced (A9). The resumed coordinator re-reads the current authoritative pair —
  already the pair from the crashed attempt, since step 5 had already completed — and materializes
  that same pair. It SHALL NOT perform a second rotation merely because delivery to the
  materialization path failed or was not observed to complete.
- **Crash after materialization (step 9) but before PostgreSQL reconciliation (A6) begins.**
  Recovery remains fenced (A9). The resumed coordinator reuses the same authoritative `(generation,
  authority_revision)` pair — re-verified per step 8 — and reconciliation (A6) resumes against that
  pair. No new generation is established merely because reconciliation had not yet started.

In every case, the authoritative state after any crash is exactly whatever the Approved Recovery
Authority itself last accepted at its own linearization point (step 5). A resumed or replacement
coordinator's first action is always to read that state, never to assume a prior attempt's outcome
or to rotate again without first establishing, from the authority's own state, that no unresolved
accepted transition already exists.

#### A3.3 Materialization

The existing external-configuration controller boundary SHALL materialize both the current
generation and its authority revision as one read-only mounted file, not a process
environment-variable snapshot. Identity SHALL re-read that file for every readiness evaluation
and refresh-token request. The workload receives no provider credential and no Kubernetes API
permission, and performs no direct call to the Approved Recovery Authority.

The materialized file is only a delivery cache; its mere existence, or its equality with a stale
PostgreSQL-recorded pair, is never freshness proof by itself. During ordinary operation (no
recovery in progress), a materialized `(generation, authority_revision)` pair that exactly
matches the PostgreSQL-recorded `(reconciled_generation, reconciled_authority_revision)` pair
(A4) is accepted as current, because no rollback opportunity exists outside a recovery window:
PostgreSQL's own record can change only through the governed reconciliation transaction (A6) or a
physical restore. Recovery-window freshness — proving the controller's delivered pair is not
stale relative to the live authority immediately before a fence is released — is a distinct
recovery-coordinator responsibility defined in A9, not an ongoing Identity capability.

Missing, blank, malformed, unavailable, or multiply-valued authority state is indeterminate and
SHALL make production Identity non-ready.

### A4. PostgreSQL recovery-state contract

The Identity migration stream SHALL add exactly this singleton relation:

```text
emg_identity.identity_recovery_state
  singleton_id                  SMALLINT PRIMARY KEY CHECK (singleton_id = 1)
  reconciled_generation         UUID NOT NULL
  reconciled_authority_revision TEXT NOT NULL
  reconciled_at                 TIMESTAMPTZ NOT NULL
```

`reconciled_authority_revision` SHALL store the Approved Recovery Authority's own version
identifier (A3.1) exactly as reported at reconciliation commit time, encoded as text to remain
neutral across authority providers whose native version identifiers are integers, opaque
strings, or other totally ordered representations; the migration stream SHALL NOT reinterpret,
truncate, or recompute this value. Exactly one row SHALL exist after initial bootstrap
reconciliation. The relation, constraint, and row are owned by `emg_identity_migrator`; the same
role remains migration and recovery authority. No sequence or additional index is required.

`emg_identity_app` SHALL receive only `SELECT` on this relation, in addition to D-4. It SHALL
receive no `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, ownership, DDL, or sequence privilege on it.
PUBLIC and every unrelated role SHALL have no privilege. Recovery-state mutation is permitted
only to `emg_identity_migrator` acting through the governed bootstrap/recovery commands.

This relation is a **reconciliation record, not a freshness authority.** PostgreSQL's copy of the
generation and authority revision proves only what was true at the moment of the last committed
reconciliation; it SHALL never be read as evidence that no later rotation has since occurred. The
serving application SHALL compare the full row — both `reconciled_generation` and
`reconciled_authority_revision` — against its externally delivered `(generation,
authority_revision)` pair (A3.3); it SHALL NOT infer freshness from timestamps, PostgreSQL
timeline identifiers, row presence alone, or `reconciled_generation` in isolation.

### A5. State machine and actors

The externally required `(generation, authority_revision)` pair and the PostgreSQL reconciled
pair are the authoritative inputs. `READY` is an evaluated serving condition, not a separately
persisted state.

| State | Condition | Permitted actor and transition |
| :--- | :--- | :--- |
| `NORMAL` | Current external `(generation, authority_revision)` pair equals the PostgreSQL reconciled pair | Identity may evaluate dependencies and become `READY`. Ordinary restart/rollout remains in this state. |
| `RECOVERY_DETECTED` | Recovery is declared and the recovery coordinator establishes a fresh, CAS-protected external pair before target exposure (A3.2, A9) | Recovery coordinator only; serving remains isolated/non-ready. |
| `INVALIDATION_REQUIRED` | PostgreSQL pair is missing or differs from the externally required pair | Identity may observe only and remains non-ready; recovery authority may start reconciliation once A9 fencing evidence exists. |
| `INVALIDATION_IN_PROGRESS` | The recovery transaction has begun and holds locks on recovery state and both refresh tables | `emg_identity_migrator` only. Concurrent refresh writes cannot commit through the locked/quiesced target. |
| `RECOVERY_RECONCILED` | One transaction has invalidated every family/token and then recorded the externally required pair | PostgreSQL commit establishes this state atomically. Fences remain closed until A9.6 is separately satisfied. |
| `READY` | Pairs match and all ordinary mandatory readiness dependencies pass | Identity readiness only; no database mutation. |

An external `(generation, authority_revision)` pair different from the PostgreSQL-recorded pair is
a mismatch requiring reconciliation, evaluated by equality of the full pair. Independently, any
candidate authority revision lower than the highest revision ever recorded in the authority's
queryable history (A3.1) is a detected rollback/replay and SHALL be rejected and logged as a
security event, whether or not it would otherwise have produced a pair match. Repeating
reconciliation for the same pair SHALL be idempotent: it re-verifies invalidate-safe state and
records the same pair without making a valid row active. Reconciliation presented with a pair
that no longer equals the current external authority's live state at commit time SHALL abort
before commit (A6).

### A6. Transaction and crash contract

The external authority is changed first; no distributed atomic commit is claimed. The database
reconciliation command SHALL receive the current external generation through the governed
environment boundary and, in one PostgreSQL transaction as `emg_identity_migrator`:

1. verify its effective role and the exact governed schema/history/security state;
2. lock the singleton recovery-state relation and both refresh tables against concurrent writes;
3. set every non-revoked family `revoked_at` and every token status to `revoked` without
   `DELETE` or `TRUNCATE`;
4. prove within the same transaction that no family remains unrevoked and no token remains in a
   non-revoked status; and only then
5. insert or update the singleton row to the supplied required `(generation, authority_revision)`
   pair and commit.

Any error, failed proof, cancellation, or crash before commit rolls back both invalidation and the
recovery-state record, so readiness remains denied. A crash after commit is safe: invalidation and
the matching record are both durable, and a retry is idempotent. The CAS-protected rotation in
A3.2 is the primary concurrency control; as defense in depth, if the external authority's live
`(generation, authority_revision)` pair differs from the value supplied to this transaction, the
command SHALL re-read/verify the authoritative pair immediately before database commit through the
recovery orchestrator, and a mismatch aborts. This is an ordered protocol, not a false claim of
atomicity across the external system and PostgreSQL. Fence release remains governed separately by
A9.6 regardless of this transaction's outcome.

### A7. Replay-resistance proof

Let `G` denote a generation and `R` its authority revision, always handled as the pair `(G, R)`.
Let `Rmax` denote the highest authority revision ever observed in the Approved Recovery
Authority's queryable history (A3.1/A3 capability 4) at the time of any check.

**(A) A historical PostgreSQL backup contains valid refresh credentials and a reconciled pair
`(N, Rn)`.** The backup is inert until restored; by itself it establishes nothing about the live
authority.

**(B) The external authority legitimately advances to a new pair `(N+, Rn+1)`, `Rn+1 > Rn`.**
This can only occur through the CAS-protected rotation in A3.2: the coordinator confirms, from the
authority's full history, that the new generation value has never appeared before (A3.2 step 3),
and the authority itself — at its own single linearization point (A3 capability 3, A3.2 step 5) —
atomically accepts that transition only if `Rn` is still the current version identifier.

**(C) Someone attempts to replay `N` at revision `Rn`** — i.e. to make the authority report `(N,
Rn)` as current again, whether by operator action, attacker action, or a configuration-store
rollback. A3's required capability 2 (monotonically advancing, non-reused version identifiers,
platform-guaranteed) means no write — including one that reintroduces the literal content `N` —
can be assigned a version identifier `<= Rmax`. A write reintroducing `N`'s content necessarily
receives a new revision `Rk > Rmax`, and A3.1's rollback/replay detection additionally flags it
because its content matches a version already present in history. Either way, the authority never
again reports authority revision `Rn` as current; the pair `(N, Rn)` cannot become the live
authority state again.

**(D) A stale Identity pod still holds materialized `(N, Rn)`.** A stale pod is excluded from the
recovery target throughout both A9.4 phases: Phase 1 admits only `emg_identity_migrator` through
the reconciliation tooling, and Phase 2 admits only the specific fresh workload identity started
for readiness qualification (A9.6 step 6) — a stale pod is neither. Because a fenced pod also
cannot serve refresh traffic (A9.2), the pod's stale materialization is inert for the duration
that matters, and it cannot obtain a network path to the recovery target under either phase to
observe or influence the reconciled state. Once the fence fully releases (A9.6 step 9) and the pod
resumes normal operation, its next readiness evaluation re-reads the materialized file; if that
file is also stale relative to the now-current `(N+, Rn+1)`, the comparison in A4/A8 fails and the
pod remains/returns non-ready — it can never reach `READY` while holding a pair that does not
equal PostgreSQL's current reconciled pair, which by (C) can never again be `(N, Rn)`.

**(E) PostgreSQL is restored from the backup in (A), reintroducing row `(N, Rn)`.** Per (C), the
live authority cannot be made to report `(N, Rn)` again. Readiness and request-time evaluation
therefore compare the restored row against a live authority state that provably cannot match it,
so the restored pair alone can never satisfy A4/A8. The restore is additionally denied network
reachability by any Identity serving workload until reconciliation (A9.4).

**(F) Reconciliation crashes before commit.** A6 step 5 (commit) is the sole point at which the
invalidation and the new `(generation, authority_revision)` pair become visible. A6's transaction
covers invalidation and the pair write together; rollback on any pre-commit failure reverts both,
so no partially-invalidated or partially-recorded state is ever observable. The fence (A9) remains
closed; Identity remains non-ready; a retry re-executes A6 from a clean, unmodified starting state.

**(G) Reconciliation commits but the recovery coordinator crashes before releasing the fence.**
Fence release is a distinct, explicit step (A9.6) performed only by the fence owner after Stage-50
and recovery-witness approval, never an automatic consequence of a database commit. A crashed
coordinator leaves the fence closed — Identity remains non-ready and the network/session fences
remain in force — which is safe by construction (A9.7). A resumed or replacement coordinator
re-verifies Stage-50 and witness evidence and only then performs the release; no implicit or
time-based release exists.

**(H) An old PostgreSQL session survives unless explicitly fenced.** A9's database-session fence
is a mandatory precondition to reconciliation, not a best-effort step: reconciliation (A6) SHALL
NOT begin until the recovery coordinator has positive evidence (A9.3) that no session
authenticated as `emg_identity_app` from outside the governed reconciliation path exists against
the recovery target. An environment that cannot produce that evidence fails closed before
reconciliation begins (A9.7), so a surviving stale session interacting with the recovery target
during the fenced window is excluded by the gate itself rather than argued away after the fact.

In every case (A)–(H), Identity reaches `READY` or accepts a refresh-token operation only through
the single path defined by A4/A8: a live materialized `(generation, authority_revision)` pair
equal to PostgreSQL's `(reconciled_generation, reconciled_authority_revision)`, itself only ever
written by a committed A6 transaction using a pair that was, at read time, the Approved Recovery
Authority's own current, CAS-protected, non-reused state. No combination of backup replay,
authority replay, stale delivery, or coordinator crash can produce that equality outside a
completed, witnessed reconciliation.

### A8. Bootstrap, readiness, and rollout

For a clean environment, the external authority SHALL establish the initial `(generation,
authority_revision)` pair before database bootstrap. Bootstrap creates roles/schema; migrations
create the recovery relation; initial reconciliation runs as `emg_identity_migrator` and records
that pair after proving the empty/new refresh-state set safe. Stage-50 then validates structure
and authority. Backup establishment begins only after this sequence. This explicit initialization
distinguishes a new database from an unreconciled restored database without requiring token
invalidation on ordinary pod restarts.

Production liveness remains process-only and SHALL NOT depend on PostgreSQL or the external
authority. Production readiness SHALL be true only when:

1. the continuously mounted `(generation, authority_revision)` pair is present and canonically
   valid;
2. a bounded read using `emg_identity_app` returns exactly one recovery-state row;
3. both `reconciled_generation` and `reconciled_authority_revision` equal the externally
   delivered pair; and
4. every other mandatory Identity readiness dependency passes.

Failure, timeout, absence, duplicate row, malformed value, or any partial mismatch SHALL return
non-ready. Refresh-token serving routes SHALL use the same cached-for-at-most-one-request gate or
an equivalent request-time fail-closed guard, so loss of readiness cannot leave an already-routed
pod serving refresh operations during endpoint propagation. Readiness SHALL never mutate recovery
state or perform invalidation. Recovery-window freshness assurance beyond this ordinary
per-request comparison is provided by the A9 fencing protocol, not by the readiness check itself.

Stage annotations remain machine-checkable orchestration metadata, not enforcement. Deployment
promotion SHALL require completed migration, initial/recovery reconciliation, and Stage-50 PASS.

### A9. Recovery Fencing Protocol

This section defines the enforceable fence required by D-10 and A3.2, independently of, and prior
to, the restore/PITR procedure in A10.

**A9.1 Fence owner.** The **authorized recovery coordinator** (A3.2) is the single accountable
actor for establishing, transitioning, and releasing every fence defined in this section,
including every phase transition of the network fence (A9.4). No other actor, automated process,
or passage of time may establish, transition, or release a fence. Fence-owner actions SHALL be
auditable (actor identity, action, target, timestamp).

**A9.2 Workload fence.** Before a recovery target becomes reachable by any Identity serving
workload, the fence owner SHALL:

1. remove the Identity serving workload from all client-traffic paths (e.g., withdraw it from the
   Service/load-balancer/ingress that routes refresh requests to it), and
2. reduce the Identity serving workload to zero running replicas, or an equivalent governed
   mechanism that makes every existing pod incapable of accepting new connections.

**Positive evidence** required before proceeding: a query against the governed
orchestration/traffic-management system itself (not an assumed command exit code) showing zero
Identity replicas serving traffic and zero routable endpoints for refresh requests. This evidence
does not depend on, and SHALL NOT be inferred from, projected-volume/Secret propagation to any
pod — propagation speed is irrelevant once no pod exists to observe it.

**A9.3 Database session fence.** Before reconciliation begins, the fence owner SHALL ensure, using
the recovery target's own administrative session-management capability (terminating existing
backend sessions/connections, or an equivalent mechanism that revokes further use of
already-established sessions/credentials for the affected role), that no session opened by a
stale Identity workload before A9.2 retains usable access to the recovery target. This
requirement is stated architecturally; the specific command is an implementation detail of the
governed recovery tooling for the target's actual database platform, not a normative part of this
amendment.

**Positive evidence** required before proceeding: a query against the recovery target's own
session/connection state, captured after A9.2 and before reconciliation, showing zero active
sessions authenticated as `emg_identity_app` other than the reconciliation coordinator's own
session.

**A9.4 Restore/network fence.** The network fence is a two-phase gate. Only the fence owner may
transition it between phases, and every transition requires its own positive evidence from the
authoritative network/access-control system, captured at the time of the transition — never
inferred from an earlier phase's evidence or from elapsed time.

**Phase 1 — Reconciliation fence.** From the start of restore until the transition to Phase 2
(A9.6 step 5), the recovery target SHALL be reachable only by governed recovery/migration actors
(i.e., `emg_identity_migrator` through the reconciliation tooling), enforced at the network or
access-control layer (e.g., firewall, security group, private connectivity scope) — not by
application-level credential gating alone, which a stale pod's still-materialized DSN could
otherwise satisfy. No Identity serving workload identity, fresh or stale, has a network path to
the recovery target during Phase 1; in particular, `emg_identity_app` has no path.

**Positive evidence** required to establish Phase 1: a network-reachability or access-control-
policy check confirming every Identity serving workload's network identity has no path to the
recovery target, captured before restore begins.

**Phase 2 — Readiness-qualification fence.** The fence owner may transition the network fence from
Phase 1 to Phase 2 only after the reconciliation transaction has committed (A9.6 step 1), Stage-50
has passed (A9.6 step 2), and the authority pair and materialization have been independently
reconfirmed (A9.6 steps 3–4). Under Phase 2, network reachability to the recovery target is
narrowed, not opened: reachability is restricted to the specific network identity of the Identity
workload instance the fence owner is about to start or has just started for readiness
qualification (A9.6 step 6) — never to any prior, stale Identity workload identity, and never to
ordinary client-facing traffic. `emg_identity_migrator`'s Phase 1 access is not required to persist
into Phase 2 and MAY be withdrawn at the same transition. Database privileges reachable over this
path remain exactly the accepted `emg_identity_app` runtime least-privilege grants (D-4, A4); the
network transition grants no additional privilege. Because the workload fence (A9.2) has held
Identity at zero running replicas throughout Phase 1 and remains in force through this transition,
no stale Identity pod exists to be granted or to retain a network path when Phase 2 begins.

**Positive evidence** required to establish Phase 2: a network-reachability or access-control-
policy check, captured at the moment of transition, confirming (a) the recovery target is
reachable by the specific fresh Identity workload identity and by no other Identity workload
identity, and (b) client-facing traffic routing (A9.2) remains completely fenced. **Network access
granted under Phase 2 is solely for readiness qualification and does NOT constitute restoration of
client service; the two SHALL NOT be treated as the same event, and Phase 2 evidence alone SHALL
NOT be read as satisfying A9.2's release condition.**

Before final fence release (A9.6 step 9), the fence owner transitions the network fence from Phase
2 to normal operating-policy network access, with its own positive evidence that the transition
has occurred.

**A9.5 Preconditions to reconciliation.** Reconciliation (A6) SHALL NOT begin until A9.2, A9.3,
and the A9.4 Phase 1 reconciliation fence have each produced their required positive evidence, and
the external authority has been rotated (A3.2, mechanism 3a or 3b) to a new, non-reused
`(generation, authority_revision)` pair. Any one fence lacking positive evidence halts the
procedure before reconciliation begins.

**A9.6 Conditions for fence release.** Recovery fence release is itself a gated, ordered recovery
step; it is never an automatic side effect of any single earlier step succeeding. The fence owner
SHALL release client-traffic fencing and restore Identity's normal-operating-policy database
access only after ALL of the following have occurred, strictly in this order:

1. the PostgreSQL reconciliation transaction (A6) has committed successfully, recording the new
   `(generation, authority_revision)` pair;
2. Stage-50 recovery validation (A11) has explicitly passed against the reconciled state;
3. the recovery coordinator has independently confirmed, directly against the Approved Recovery
   Authority, that it still reports the expected current `(generation, authority_revision)` pair —
   not inferred from step 1 or step 2 alone;
4. the recovery coordinator has independently confirmed that the controller-materialized file
   fresh Identity workloads will consume contains that exact current pair;
5. the fence owner has transitioned the A9.4 network fence from Phase 1 (reconciliation fence) to
   Phase 2 (readiness-qualification fence) and has captured the Phase 2 positive evidence required
   by A9.4 — this transition alone grants network access for readiness qualification only and does
   NOT restore client service;
6. fresh Identity workloads are started — this is itself a gated recovery step, not an
   unsupervised consequence of steps 1–5 — while client traffic remains fenced (A9.2) and while
   recovered-database access remains scoped to the Phase 2 fresh-workload-identity path
   established in step 5;
7. every started fresh Identity workload reaches `READY` using the full Amendment 1 readiness
   predicate (A8), which requires that workload's own `emg_identity_app` database session over the
   Phase 2 network path — proof that the fresh workload independently observes the current pair
   through its own qualification-scoped access, not an assumption carried over from steps 3–5;
8. the accountable recovery witnesses required by the recovery governance contract record their
   approval of the evidence from steps 1–7; and only then
9. the fence owner transitions the A9.4 network fence from Phase 2 to normal operating-policy
   network access, with positive evidence that the transition has occurred, and releases
   client-traffic fencing, restoring Identity's normal-operating-policy access to the recovered
   database and to client-facing service. Step 9's two actions together are what constitute
   restoration of client service; no earlier step, including the Phase 2 transition in step 5,
   does so.

No step in this sequence may be skipped, reordered, or satisfied by an elapsed timeout in place of
its required positive evidence. In particular:

- reconciliation success (step 1) alone SHALL NOT release any fence;
- Stage-50 PASS (step 2) alone SHALL NOT release any fence;
- controller/materialization synchronization (steps 3–4) alone SHALL NOT release any fence;
- the Phase 1→Phase 2 network-fence transition (step 5) alone SHALL NOT release any fence and
  SHALL NOT be treated as restoring client service;
- starting a fresh workload (step 6) does not itself constitute readiness and SHALL NOT release
  any fence; and
- no client traffic and no ordinary Identity database access SHALL be restored before a fresh
  Identity workload has independently reached `READY` (step 7) and witness approval (step 8) is
  recorded.

**A9.7 Failure semantics.** Every fence remains closed and Identity remains non-ready unless its
own success is explicitly evidenced. Specifically:

- **Partial workload shutdown** (some replicas or routes not confirmed removed): the recovery
  target remains unreachable to Identity; reconciliation SHALL NOT begin.
- **Inability to terminate database sessions:** reconciliation SHALL NOT begin; the procedure
  halts and requires operator-reviewed remediation, per D-6's equivalent fail-closed posture.
- **Incomplete or unverifiable recovery-target network fence at establishment (A9.4 Phase 1):**
  the recovery procedure halts before restore and before reconciliation; the recovery target is
  not exposed to any Identity serving workload; reconciliation is not attempted until the fence
  owner produces the required Phase 1 positive network/access-control evidence.
- **Network-fence evidence lost or becomes unverifiable after Phase 1 establishment but before
  reconciliation begins:** this is treated identically to Phase 1 never having been established —
  reconciliation SHALL NOT begin until the fence owner re-establishes and re-verifies Phase 1.
- **Phase 1→Phase 2 network-fence transition (A9.6 step 5) cannot be positively verified:** the
  transition is treated as not having occurred; the network fence remains in Phase 1; no fresh
  Identity workload SHALL be started (A9.6 step 6) until the fence owner produces the required
  Phase 2 positive evidence.
- **Phase 2 transition is observed to grant, or cannot positively exclude, network reachability
  for a stale Identity workload identity:** this is a Phase 2 establishment failure; the fence
  owner SHALL immediately treat the network fence as compromised, revert to and re-verify Phase 1,
  and re-attempt the Phase 2 transition only after re-establishing that no stale identity has a
  path to the recovery target.
- **Phase 2 transition is observed to expose, or cannot positively exclude exposure of, ordinary
  client-facing traffic routing to the recovery target or to the fresh workload:** this is a
  Phase 2 establishment failure; the fence owner SHALL immediately re-close client-traffic fencing
  (A9.2) if any doubt exists that it already holds, revert to and re-verify Phase 1, and treat any
  network access granted so far as void of readiness-qualification standing.
- **Network-fence evidence lost after reconciliation (A6) commits but before a fresh Identity
  workload reaches `READY` (A9.6 step 7):** fence release SHALL NOT proceed; A9.6 steps 4–6 are
  treated as unproven regardless of steps 1–3 having succeeded, and the fence owner SHALL
  re-verify the network fence, including reverting to Phase 1 if necessary, before any further
  workload startup or traffic-restoration action continues.
- **Network-fence evidence lost after fresh workload startup but before witness approval or final
  release (A9.6 steps 8–9):** traffic and database-access restoration SHALL NOT proceed; the
  fence owner SHALL re-verify network isolation, including reverting to Phase 1 if necessary,
  before resuming toward release.
- **Authoritative network/access-control state becomes unknown or contradictory at any point
  before fence release:** recovery returns to a fail-closed state equivalent to the network fence
  never having been verified; the sequence SHALL restart from re-establishing and re-verifying
  Phase 1 rather than proceeding on stale or ambiguous evidence.
- **Authority rotation succeeds but restore fails:** the new generation exists but no
  reconciliation is attempted; the fence remains closed; a subsequent restore attempt requires the
  fence owner to re-verify all A9.2–A9.4 evidence (state may have changed since rotation).
- **Restore succeeds but reconciliation (A6) fails or is aborted:** per A7(F), fences remain closed
  and Identity remains non-ready; retry re-executes A6 from its rolled-back starting state.
- **Reconciliation succeeds but Stage-50 validation (A11) fails:** fences remain closed
  notwithstanding the committed reconciliation; A9.6 step 2 was not satisfied, so release is not
  authorized.
- **Stale materialization observed at any point before release:** treated as an A9.6 step 4
  failure; release is denied until the controller demonstrably delivers the current pair.
- **Controller/operator (fence owner) crash at any point:** per A7(G), all fences remain closed by
  construction; a resumed or replacement coordinator re-verifies every prior step's evidence,
  including the network fence's current phase, before proceeding — no step is assumed still valid
  from before the crash.
- **Retry of the recovery procedure:** SHALL restart from re-verifying A9.2–A9.4 evidence — with
  the network fence reset to Phase 1 — not resume from an assumed midpoint or an assumed Phase 2
  state; only the A6 database transaction itself is idempotent (A6, A7) in the narrow sense of
  safely repeatable with the same pair.

### A10. Restore, PITR, and rollback procedure

Full restore and PITR use the same protocol, applying the A9 fencing protocol at each referenced
step:

1. establish the workload, database-session, and network fences (A9.2–A9.4 Phase 1) and confirm
   all required positive evidence before proceeding;
2. establish a fresh external recovery generation under recovery approval and audit, using the
   CAS-protected, history-checked rotation in A3.2;
3. wait for controller synchronization of that exact `(generation, authority_revision)` pair and
   verify the mounted file while the A9 fences remain closed;
4. restore/replay PostgreSQL and collect provider/timeline evidence where available, with the
   network fence (A9.4 Phase 1) still in force;
5. an attempted Identity startup/readiness check observes the pair mismatch (A4/A8) and is
   denied — this step is only reachable if some fence were bypassed, and exists as defense in
   depth, not as the primary control;
6. run A6 reconciliation using `emg_identity_migrator`;
7. retry safely after any pre-commit failure (A7(F)); after success, verify the exact row state,
   migration history, ACLs, and that restored credentials remain revoked;
8. run Stage-50 and recovery qualification (A11); and
9. release the A9 fences, fresh workload traffic, and database access only by completing every
   ordered step of A9.6 in full, including its own fresh-workload-readiness and witness-approval
   steps.

An application image/configuration rollback without database restore does not rotate the external
generation and does not invalidate refresh state. It remains ready if it understands this accepted
gate contract and all values match. An application version that predates the mandatory gate SHALL
not be an eligible rollback target once the recovery-state migration is applied. A database
rollback, full restore, or PITR always requires a fresh generation, the A9 fencing protocol, and
reconciliation.

### A11. Stage-50 and legacy-adoption clarification

Stage-50 SHALL validate the recovery relation, singleton constraint and cardinality, ownership,
exact runtime `SELECT` grant, absence of runtime mutation/DDL privileges, absence of PUBLIC or
unrelated-role authority, and role membership/cross-schema prohibitions. It validates the supplied
environment `(generation, authority_revision)` pair's shape and wiring but SHALL NOT create,
rotate, or reconcile a recovery generation. During a recovery qualification, Stage-50 SHALL
additionally confirm that the A9 fence positive-evidence records exist and are attributable to the
fence owner for the recovery being validated. A generation/revision or fence-evidence mismatch is
a deployment/recovery gate failure, distinct from structural Stage-50 validation.

P0-1 requires no new architectural decision. D-6 already requires exact compatibility, revocation
of prior/PUBLIC privileges, and post-adoption proof of D-3/D-4. For avoidance of doubt, the phrase
"exact legacy adoption" includes all security-material catalog state. Before adoption, bootstrap
SHALL reject any unexpected table or column grantee/ACL (including PUBLIC), wrong or ambiguous
owner, user-defined trigger, enabled or forced row-level security, policy, security label, rule,
or other table property capable of changing access or behavior. It SHALL not silently normalize
such divergence. After adoption and after migration, Stage-50 SHALL prove exact owners and ACLs,
no PUBLIC/unrelated grantee, no unexpected trigger, no RLS/FORCE RLS/policy/rule/security-label,
no runtime migration-history access, no role membership, and no unintended cross-schema authority.
Only PostgreSQL-required internal constraint triggers are permitted.

### A12. Mandatory adversarial validation

Implementation and qualification SHALL include real PostgreSQL and real Approved-Recovery-Authority
tests where catalog, transaction, authority, or recovery semantics are material. Tests SHALL prove,
at minimum:

- normal process restart, pod rollout, and application rollback without database rollback remain
  ready with no refresh invalidation;
- missing/malformed external generation or revision, missing/duplicate recovery-state row, and
  every generation/revision mismatch are non-ready and refresh operations fail closed;
- an attempt to make a previously accepted `(generation, authority_revision)` pair current again
  (external authority rollback/replay attempt) is detected and rejected by the authority's own
  monotonic-version guarantee (A3.1), whether attempted directly against the authority or via a
  restored PostgreSQL row alone;
- an attempt to reuse a generation value already present in the authority's history is rejected
  by the pre-rotation history check (A3.2);
- a stale authority revision presented after a legitimate rotation is rejected as non-current;
- a stale materialized delivery file (controller not yet synchronized to the latest authority
  state) fails A9.6 step 4 and blocks fence release;
- two competing rotation attempts against the same expected prior revision: the Approved Recovery
  Authority's own single linearization point (A3 capability 3, A3.2 step 5) accepts at most one and
  rejects the other at the moment of the attempt itself — not after the fact, and not by either
  coordinator independently inferring the outcome from a subsequent read — and the rejected
  coordinator does not silently overwrite, race, or reconcile against the winner (A3.2);
- two coordinators read the same predecessor revision and each independently attempt rotation:
  exactly one attempt is accepted at the authority's linearization point and the other is rejected
  by the authority itself; both interleavings — coordinator A's attempt reaching the linearization
  point before coordinator B's, and coordinator B's reaching it before coordinator A's — are
  exercised, and in neither case do both coordinators conclude success;
- a competing same-predecessor transition is rejected by the authority's own serialization
  primitive (mechanism 3a's conditional-write rejection, or a qualifying mechanism 3b's
  lease/lock/metadata-CAS rejection) rather than inferred from a subsequent read of version
  history;
- no two different generations are ever simultaneously treated as successful/authoritative by two
  different coordinators for the same predecessor, at any point before either proceeds to
  materialization or reconciliation;
- a coordinator crash before the authority's linearization decision (A3.2 step 5) leaves no new
  authoritative generation, and recovery safely restarts from a fresh read of authority state
  (A3.2.1);
- a coordinator crash after the authority accepts a transition but before the coordinator records
  or observes that acceptance (A3.2 steps 5–7) does not produce a second, independent rotation: the
  resumed coordinator discovers and adopts the already-accepted pair from the authority's own
  history, or fails closed if it cannot determine the outcome from that history alone (A3.2.1);
- a coordinator crash after a successful authority transition but before materialization does not
  trigger a second rotation; the resumed coordinator materializes the same already-accepted pair
  (A3.2.1);
- a coordinator crash after materialization but before PostgreSQL reconciliation begins does not
  trigger a second rotation; reconciliation resumes against the same already-accepted,
  already-materialized pair (A3.2.1);
- a stale read of the authority's current version identifier — an expected predecessor that is no
  longer current at the moment of the linearization decision — is rejected at that decision rather
  than accepted;
- an Approved Recovery Authority configuration with insufficient history retention (for example, a
  Vault KV v2 `max-versions` setting that would prune history needed for non-reuse or rollback
  detection) fails the authority qualification gate (A3) and is rejected before use, independent of
  whether its `cas` semantics are otherwise correct;
- a candidate provider or configuration lacking a provable single linearization point for
  capability 3 (no mechanism 3a and no qualifying mechanism 3b) is rejected by the authority
  qualification gate (A3) and is never used as an Approved Recovery Authority, regardless of how
  well it satisfies capabilities 1, 2, 4, and 5;
- an implementation that attempts to satisfy capability 3 using only an eventually consistent
  history-listing read performed after an unconditional write is rejected at qualification time as
  not meeting mechanism 3b, independent of how the write itself behaves, and is not treated as
  equivalent to native compare-and-set;
- GCP Secret Manager, used alone with no separately governed native serialization primitive, fails
  authority qualification for concurrent generation rotation, and any implementation or
  configuration claiming otherwise fails qualification review;
- Vault KV v2 qualification is validated against both its native `cas` write semantics (rejecting a
  competing write against a stale expected version) and its configured history retention
  (`max-versions`/delete-version-after) sufficient to preserve the non-reuse and rollback-detection
  history required by A3.1 and A3.2;
- a stale running Identity pod holding a superseded pair can neither receive refresh traffic
  (A9.2) nor reach a recovery target (A9.3, A9.4) during a fenced recovery window, independent of
  whether it has observed the new materialized file;
- a PostgreSQL session opened before the database-session fence cannot execute further
  authenticated statements against the recovery target once A9.3 evidence is captured;
- reconciliation (A6) is refused, or the procedure halts, when workload fencing (A9.2) cannot
  produce its required positive evidence;
- reconciliation (A6) is refused, or the procedure halts, when database-session fencing (A9.3)
  cannot produce its required positive evidence;
- a recovery-target network fence (A9.4 Phase 1) that cannot be established halts the procedure
  before restore and before reconciliation, with Identity remaining unable to serve traffic or
  reach the target (A9.7);
- during the Phase 1 reconciliation fence, `emg_identity_app` (the identity a fresh serving
  workload would authenticate as) cannot reach the recovered database — only
  `emg_identity_migrator` through the reconciliation tooling can (A9.4 Phase 1);
- network-fence evidence that cannot be positively verified is treated as fence absence and blocks
  reconciliation and fence release alike, in either phase (A9.7);
- a network fence established and then observed incomplete before reconciliation completes keeps
  recovery fenced and prevents progression to serving (A9.7);
- the Phase 1→Phase 2 network-fence transition (A9.6 step 5) cannot be positively verified: no
  fresh Identity workload is started, and the network fence is treated as remaining in Phase 1
  (A9.7);
- a stale Identity workload identity cannot obtain, and is not granted, the Phase 2
  readiness-qualification network path — only the specific freshly started, recovery-qualified
  workload identity may reach the recovered database under Phase 2 (A9.4 Phase 2, A9.6 step 5);
- the freshly started, recovery-qualified Identity workload successfully reaches the recovered
  database and completes its readiness read (A8 item 2) using only the Phase 2
  readiness-qualification network path, proving that path — and only that path — carries the
  required `emg_identity_app` access (A9.4 Phase 2, A9.6 steps 6–7);
- ordinary client-facing traffic routing remains unavailable throughout the Phase 2
  readiness-qualification window, before witness approval, and before final release (A9.2, A9.4
  Phase 2, A9.6);
- a freshly started Identity workload that fails to reach `READY` during Phase 2 results in no
  client-service restoration: the network fence does not transition to normal operating policy,
  and client-traffic fencing (A9.2) is not released (A9.6 steps 7–9, A9.7);
- a Phase 2 transition whose positive evidence cannot be independently verified is treated as
  fence establishment failure and blocks any further recovery progress until re-verified (A9.4
  Phase 2, A9.7);
- a Phase 2 transition that is observed to grant, or cannot positively exclude, network
  reachability for a stale Identity workload identity is treated as fail-closed: the network fence
  reverts to Phase 1 and the recovery procedure halts pending re-verification (A9.7);
- a Phase 2 transition that is observed to expose, or cannot positively exclude exposure of,
  ordinary client-facing traffic routing is treated as fail-closed: client-traffic fencing (A9.2)
  is immediately re-confirmed, the network fence reverts to Phase 1, and the recovery procedure
  halts pending re-verification (A9.7);
- a network fence lost after reconciliation (A6) commits but before a fresh Identity workload
  reaches `READY` blocks traffic/database-access release and requires re-verification, including
  reverting to Phase 1 if necessary, before the sequence may continue (A9.6 steps 4–7, A9.7);
- a network fence lost after fresh workload startup but before witness approval or final fence
  release keeps client-traffic and database-access restoration prohibited (A9.6 steps 8–9, A9.7);
- successful readiness qualification followed by recovery-witness approval results in the network
  fence transitioning from Phase 2 to normal operating-policy access and client-traffic fencing
  being released — and only that sequence, never Phase 2 access alone, results in client service
  being restored (A9.4 Phase 2, A9.6 steps 7–9);
- a fence-release sequencing test proves traffic and database access cannot be restored before, in
  order: reconciliation commit, Stage-50 validation PASS, authority-pair re-verification,
  controller/materialization re-verification, the Phase 1→Phase 2 network-fence transition, fresh
  workload startup, fresh workload `READY`, and recovery-witness approval (A9.6);
- a request/readiness attempt made before reconciliation completes observes the pair mismatch and
  is denied;
- a failed or aborted reconciliation leaves no partial invalidation and no recovery-state write
  (A7(F));
- a crash before the A6 commit is safely retryable from a clean rolled-back state;
- a crash after the A6 commit but before fence release leaves fences closed and is resumed safely
  by a coordinator that re-verifies all prior evidence (A7(G), A9.7);
- repeated reconciliation for the same pair is idempotent and does not activate an invalid row;
- a Stage-50 validation failure after successful reconciliation blocks fence release (A9.6 step 2);
- a fence-release attempt missing any required A9.6 evidence, for any of its nine steps, is
  refused;
- a restored historical refresh credential (token/family) is rejected after reconciliation
  invalidation, i.e. restored-token replay fails;
- a successful final cutover — full A9/A10 sequence, including every A9.6 step in order, completed
  and witnessed — results in Identity reaching `READY` and correctly serving refresh operations
  against the recovered database; and
- adoption and Stage-50 reject unexpected table/column/PUBLIC grants, ownership, user triggers,
  RLS, FORCE RLS, policies, rules, security labels, history exposure, role membership, and
  cross-schema authority while exact clean adoption succeeds.

Physical full-restore and PITR tests SHALL exercise the complete sequence from A9 fence
establishment, through external authority rotation, restore, a pre-invalidation Identity
readiness/refresh attempt, reconciliation, Stage-50, fence release, and post-recovery credential
rejection. Mocks, invoking invalidation before Identity starts, or skipping fence-evidence
verification do not prove the security boundary.

### A13. Consequences and acceptance gate

Acceptance would add one singleton table with two governed columns (`reconciled_generation`,
`reconciled_authority_revision`), one runtime `SELECT`, one non-secret externally governed
`(generation, authority_revision)` input bound to a capability-qualified Approved Recovery
Authority, one authority qualification gate, one serialized rotation procedure decided at a single
authority-side linearization point (native CAS or an equivalent native serialization primitive)
with explicit crash semantics for every stage of rotation (A3.2, A3.2.1), one four-part recovery
fencing protocol (A9) whose network fence is itself two-phase, and one ordered recovery/cutover
protocol (A10). It does not widen refresh-table mutation, grant runtime administrative authority,
select a specific provider, require manual action for ordinary restart/rollout, or change token
semantics.

Before acceptance, an independent architecture/security review SHALL confirm: the Approved
Recovery Authority's required capabilities and authority qualification gate, the two mechanisms by
which capability 3 may be satisfied and that each provides a genuine single linearization point
rather than post-hoc detection, and the resulting rollback/replay-detection guarantee (A3, A3.1);
the serialized rotation procedure, its authority-side linearization point, its per-stage crash
semantics, and its concurrent-rotation handling (A3.2, A3.2.1); the non-distributed transaction
proof extended to authority revision (A6, A7); the fence owner, workload, database-session, and
two-phase network fence definitions and their positive-evidence requirements, including the
explicit non-equivalence of Phase 2 network access and restoration of client service (A9); the
fence-release conditions and failure semantics (A9.6, A9.7); the request-time and readiness
fail-closed serving guard (A4, A8); the exact database grants; clean bootstrap; recovery sequencing
(A10); application rollback restriction; P0-1 clarification (A11); and the extended physical
adversarial test contract, including the authority-rotation-layer tests (A12). A fifth independent
review confirmed all of the above with no remaining material gap; this amendment is accepted, with
acceptance date 2026-08-14 recorded using the repository convention. Target execution of the P0
remediations this amendment authorizes remains a separate, subsequent implementation review,
consistent with Section 14's implementation-consequences contract for the base decision; it is not
authorized by this acceptance alone.
