# Persistence Operations — `emg-persistence`

**Type:** Living engineering reference (L4). Kept current with `develop`.
**Governing authority:** `docs/phases/phase-2/PHASE2_ARCHITECTURE.md` Revision 3;
accepted addendum `EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md` (P-02).
**Status baseline:** `develop` at `69e2267` (2026-08-09), after RC-1C … RC-1H.
**Companion:** `docs/engineering/persistence-architecture.md`.

> **This document claims no production readiness.** It describes how the
> implemented persistence layer is operated and what remains deferred. Items in
> §11 are open and must not be read as delivered.

---

## 1. Startup and migrations

Migrations are **forward-only** and **checksum-immutable**
(`migrations/runner.py:42, 119-137`). Applied migration files must never be
edited; a checksum change halts the runner with `ChecksumMismatchError` rather
than continuing.

Order of operations for a deployment:

1. Run the migration job to completion **before** any serving instance starts.
   It is a one-shot job with its own credential.
2. Confirm it exited successfully. A dirty or failed migration state halts the
   runner (`DirtyMigrationError`, `FailedMigrationError`) — it does not
   auto-repair.
3. Start serving instances with the runtime credential only.

PostgreSQL migrations are transactional. Neo4j migrations are idempotent
(`CREATE CONSTRAINT/INDEX IF NOT EXISTS`) and may be re-run safely.

Current required Knowledge Graph PostgreSQL set: **V001 through V008**. V004 must be applied
before any mutation traffic; V005 and V006 must be applied before granting the
runtime role access; V007 requires `emg_audit_projector` to exist first; V008
fail-closed preflight and evidence constraints must succeed before evidentiary
reliance. The distinct Audit stream uses `audit_schema_migrations` and must be
applied as `emg_audit_migrator` before Audit Service rollout.

## 2. Credentials — runtime versus migration

Governed production roles, never shared:

| Role | Purpose | Privileges |
| :--- | :--- | :--- |
| `emg_knowledge_graph_migrator` | Owns schema objects; runs migrations | DDL, ownership |
| `emg_knowledge_graph_app` | Serving runtime | Narrow DML only |
| `emg_audit_migrator` | Owns Audit objects and `audit_schema_migrations` | Audit DDL and ownership only |
| `emg_audit_app` | Audit Service runtime | `SELECT, INSERT` on Audit and custody tables; no DDL/update/delete/truncate |
| `emg_audit_projector` | Audit Projector runtime | V007 schema usage, ledger/dispatch reads, and five dispatch update columns only |

`emg_knowledge_graph_app` after V005 + V006:

- `SELECT, INSERT` on `tenants`, `graph_revisions`, `evidence_ledger`,
  `mutation_ledger`, `mutation_ledger_resource`.
- `SELECT, INSERT` plus **column-scoped** `UPDATE` on `graph_head`,
  `mutation_idempotency`, `mutation_dispatch` (P-03 / V006). Table-wide
  `UPDATE` is revoked.
- `SELECT, INSERT, UPDATE, DELETE` on `mutation_idempotency` only — the
  `DELETE` exists solely for expired-claim replacement.
- `SELECT` on `schema_migrations`.
- No schema ownership, no DDL.

The Knowledge Graph service enforces the separation at startup: production
refuses to start when the runtime and migration DSNs are identical
(`emg_knowledge_graph_api/dependencies.py:239-247`), and requires TLS on both
DSNs and on Keycloak (`config.py:100-116`).

`evidence_ledger` is `SELECT, INSERT` only for the runtime role. V008 additionally
enforces append-only behavior against the owner with a `BEFORE UPDATE OR DELETE`
trigger and validates sequence, hash shape, and genesis structure. These
database controls do not cryptographically recompute entry hashes or chain links;
repository verification remains mandatory.

## 3. PostgreSQL pool settings and lifecycle

Environment prefix `EMG_PERSISTENCE_` (or `EMG_KNOWLEDGE_GRAPH_API_` at the
service boundary, which forwards them).

| Setting | Default | Bound | Meaning |
| :--- | :--- | :--- | :--- |
| `postgres_dsn` | none | scheme-validated | Authoritative DSN. Absent → in-memory mode |
| `postgres_pool_min_size` | `1` | `>= 0` | Minimum pooled connections |
| `postgres_pool_max_size` | `10` | `>= 1`, `>= min` | Maximum pooled connections |
| `connect_timeout_seconds` | `10.0` | `> 0` | Connect **and** pool-acquisition timeout |

Lifecycle behaviour to expect:

- **Lazy.** Building the store opens no connection and constructs no Neo4j
  driver. The pool is created and opened on first acquisition.
- **Bounded.** Acquisition blocks up to `connect_timeout_seconds`, then fails.
  Raising `postgres_pool_max_size` above the database's own `max_connections`
  budget across all replicas will exhaust the server, not the pool.
- **Reset on return.** A connection with a non-`IDLE` transaction status is
  rolled back before reuse; one that cannot be reset is closed and replaced
  within the pool's bounds. Leaked transaction state is not returned to the
  next caller.
- **Failed open is not cached.** If `pool.open()` raises, the pool is closed
  and the error propagates; a subsequent acquisition retries cleanly.

## 4. Neo4j settings and fallback behaviour

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `neo4j_uri` | none | Serving projection URI. Absent → projection disabled |
| `neo4j_user` / `neo4j_password` | none | Credentials; password is `SecretStr` and never logged |
| `neo4j_max_pool_size` | `10` | Driver pool bound |

Behaviour:

- Neo4j is **optional**. With `neo4j_uri` unset the store serves every read
  from PostgreSQL.
- The driver is constructed lazily on first use.
- `read()` consults the authoritative PostgreSQL head first, then serves
  through the projection with read-repair. Any failure resolving the projection
  degrades to the authoritative PostgreSQL snapshot.
- **Neo4j being down degrades reads, never fails them, and never blocks
  writes.** Writes do not touch Neo4j at all.
- `ProjectionLagError` is internal and is never surfaced from `read()` or
  `write()`.

Projection freshness is maintained by read-repair and by explicit
`catch_up_projection(tenant)` / `rebuild_projection(tenant)`. There is no
continuous worker — see §11.

## 5. Health and readiness expectations

- **Liveness** should not depend on either datastore.
- **Readiness** should probe PostgreSQL, because PostgreSQL is authoritative
  and the service cannot serve correctly without it.
- **Readiness must not fail on Neo4j alone.** A Neo4j outage is a degraded
  serving path, not an unready service; failing readiness on it would remove
  capacity that can still serve correctly from PostgreSQL.
- The Knowledge Graph service additionally gates startup on schema-catalog
  load, policy-config validation, production store-backend rejection, and TLS
  validation. A missing policy file is **not** a startup error — it yields an
  empty, default-deny ruleset, so every request returns 403. Alert on a
  sustained 403 spike after deployment rather than assuming a quiet deploy.

## 6. Dispatch attempt bounds

`claim_dispatch` requires an explicit `max_attempts` and rejects values below
1. The claim predicate excludes rows at or above the bound
(`attempt_count < max_attempts`), so a permanently failing row stops being
reclaimed instead of spinning. Claims use `FOR UPDATE SKIP LOCKED` with an
explicit `limit`, and leases expire via `claim_expires_at`.

Operationally, a row with `delivered_at IS NULL` and `attempt_count` at the
bound is **exhausted** — it will not be retried and requires investigation.

The Audit Projector consumes the `audit` channel. Undelivered rows now represent
pending, claimed, retry-scheduled, or exhausted work. Monitor backlog state and
attempt exhaustion; do not delete poison rows or fabricate replacement events.

## 7. Evidence-ledger integrity checks

- **Per-entry verification is automatic.** Every `get` and `list_range`
  recomputes the entry hash and refuses to return content on mismatch. No
  operator action enables this.
- **Chain verification is explicit.** `verify_range(tenant, start_seq, end_seq)`
  returns a report carrying `valid`, `verified_entries`, `first_failing_seq`,
  and a bounded `failure_kind` (`entry_hash`, `payload_mismatch`, `prev_hash`,
  `sequence`). Run it deliberately; it is never triggered by a read or an
  append.
- **Range reads are unbounded.** `list_range` and `verify_range` accept
  arbitrary ranges with no server-side cap. Verify in bounded windows on a large
  chain rather than requesting the whole history at once.
- **A detected break does not stop capture.** Appends continue to link to the
  current stored tail — deliberately, so corrupting one historical row cannot
  deny evidence capture. The break stays detectable at its original `seq`
  forever.
- **Never repair.** There is no repair, rewrite, re-hash, or replay path, and
  none may be added. A detected break is quarantined by `seq` range and
  escalated. Correcting a mistaken capture means appending a new entry.
- `EvidenceLedgerIntegrityError` is **never retryable**. Retrying it is always
  wrong. `PersistenceConflictError` is a different condition and *is*
  retryable.

## 8. Backup and recovery boundaries

- **PostgreSQL is the only thing that must be backed up.** It is authoritative
  for revisions, head pointers, outbox, mutation ledger and dispatch, and the
  evidence ledger.
- **Neo4j needs no backup.** It is a rebuildable projection; restore it with
  `rebuild_projection(tenant)` from PostgreSQL.
- **The evidence ledger cannot be reconstructed.** It has no upstream source.
  Losing it loses the record permanently. Treat its backup as the highest-value
  item in the database.
- **A restored ledger carries no integrity claim by itself.** Run `verify_range`
  over the restored ranges before relying on it.
- Provider-neutral full backup, WAL archiving/PITR, encrypted wrappers,
  retention, manifests, restore verification, checksum validation, and
  evidence-anchor verification are implemented under `infra/backup/` and
  `tools/backup/` and governed by ADR-039. Target-environment scheduler, KMS,
  cross-region storage, and witnessed production rehearsal remain operational
  prerequisites.

## 9. Troubleshooting

| Symptom | Likely cause | Action |
| :--- | :--- | :--- |
| `PersistenceConflictError` on write | Concurrent head advance (expected) | Re-open the transaction and retry. Sustained rates indicate write contention on one tenant |
| `SnapshotIntegrityError` | Stored revision failed hash verification | Do not retry. Investigate the row; this indicates corruption or out-of-band modification |
| `EvidenceLedgerIntegrityError` | Evidence row failed verification | Do not retry. Run `verify_range` to locate `first_failing_seq`; escalate. Never repair |
| Reads slow, writes fine | Neo4j degraded; falling back to PostgreSQL | Check Neo4j health. Correctness is unaffected |
| Reads stale relative to writes | Projection lag; no continuous worker | Run `catch_up_projection(tenant)`. See §11 |
| Pool acquisition timeouts | `postgres_pool_max_size` too low, or a leaked connection | Compare pool bound against concurrency and the server's `max_connections` |
| Migration halts on start | Checksum mismatch, or dirty/failed state | Never edit an applied migration. Investigate the recorded state and add a new forward migration |
| Every request returns 403 after deploy | Policy file missing or mispathed → empty default-deny ruleset | Verify `EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH` resolves inside the container |
| Service refuses to start in production | Runtime and migration DSNs identical, memory backend selected, or TLS missing | Intentional fail-closed gates. Fix configuration |
| `audit` dispatch rows remain undelivered | Projector outage, retry schedule, expired lease, or exhausted attempts | Inspect structured backlog state and projector telemetry; preserve durable rows and replay safely |

## 10. Shutdown behaviour

- `PooledConnectionProvider.close()` closes the pool, is **idempotent**, and
  refuses further acquisition afterwards with a clear error.
- The Knowledge Graph service owns and closes both the pool and the lazy Neo4j
  projection through its store-runtime `close_resources` chain (P-04,
  `78a3919`).
- `write()` performs no work after returning (ADR-6) — there is no hidden
  post-return worker to drain, so shutdown does not need to wait for one.
- In-flight transactions are the caller's responsibility; the provider does not
  cancel them.

## 11. Remaining operational prerequisites and post-v1 work

1. **Continuous Neo4j `ProjectionWorker` daemon and lifecycle — post-v1** — TD-002, open and
   accepted. `ProjectionWorker` is a library class with no deployment. Freshness
   relies on read-repair and explicit catch-up.
2. **Metrics collection, dashboards, tracing, and alerting — operational** — owned by
   ADR-015 / FEAT-12-3. The persistence layer and ADR-027 emit; nothing
   collects.
3. **Production recovery execution — operational** — configure scheduler,
   encryption/KMS custody, cross-region storage, and conduct a witnessed
   rehearsal using the implemented ADR-039 tooling.
4. **Production provisioning execution — operational** — provide the canonical
   tenant inventory and secrets, then enforce ADR-041 stage completion through
   operator/CD before Audit and projector rollout.
5. **Range-size bounds on evidence reads** — `list_range` / `verify_range`
   accept unbounded ranges; pagination shape is an open implementation detail
   under P-02 §K.4.
6. **Datastore HA and failover — operational** — production topology remains
   environment-owned; repository Kustomize and recovery tooling do not select
   an HA product or prove failover.

---

## Related documents

- Architecture: `docs/engineering/persistence-architecture.md`
- Technical debt: `docs/engineering/technical-debt.md`
- Production readiness: `docs/architecture/EMG_PRODUCTION_READINESS_ROADMAP.md`
- Evidence ledger contract: `docs/architecture/EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md`
