# PostgreSQL backup, PITR, and disaster recovery runbook

## Scope and objectives

PostgreSQL is authoritative for EMG relational state, including the audit and digital-evidence
custody ledgers. This runbook supplies the provider-neutral recovery foundation and RC-E
operational scheduling; it does not provide high availability, replication topology, or a cloud
storage service.

The production objectives are:

- **RPO: 5 minutes.** Continuous WAL archiving with `archive_timeout = 300` limits the normal
  unarchived interval. An incident that also destroys the live database host may lose up to five
  minutes after the most recently durably copied WAL segment. Operators must alert if the archive
  age exceeds five minutes.
- **RTO: 4 hours.** This covers incident declaration, backup selection, decryption, restore,
  WAL replay, evidence verification, and controlled service re-entry. Dataset growth must be
  measured in rehearsals; if the observed p95 exceeds four hours, capacity or the objective must
  be changed through the architecture process.

These are operational targets, not guarantees. A successful quarterly rehearsal is the evidence
that the current data volume and infrastructure can meet them.

## Backup policy

A full physical backup runs daily at 01:00 UTC. PostgreSQL archives WAL continuously, with a
five-minute archive timeout. Retain at least 35 daily full backups and never fewer than two valid
full backups. WAL required to recover every retained full backup must be retained; delete WAL only
after establishing the earliest retained backup's starting WAL boundary. The supplied retention
tool intentionally plans/deletes only full-backup directories because safe WAL pruning requires
PostgreSQL-aware boundary information and must be implemented by the repository operator.

Backups must be copied to at least one administratively separate failure domain. The repository
interface is a mounted POSIX filesystem, so local disk, object-gateway mounts, offline media, and
other implementations can be selected without changing these tools.

Every base-backup file and archived WAL segment must be encrypted before entering the repository.
The runtime supplies executable wrappers through `EMG_BACKUP_ENCRYPT_COMMAND` and
`EMG_BACKUP_DECRYPT_COMMAND`; wrappers accept `INPUT OUTPUT` arguments. Keys and DSNs come from
the environment's secret manager or root-readable files and must never be committed. Keep a
tested, access-controlled escrow copy of decryption material in a separate failure domain. Key
rotation must preserve old keys for the full retention window.

Encryption/decryption variables name one executable receiving `INPUT OUTPUT`; manifest signing
and verification wrappers receive `MANIFEST SIGNATURE`. All wrappers must fail nonzero on error.
`EMG_BACKUP_KEY_REFERENCE` is a non-secret escrow identifier. The detached signature authenticates
the manifest and its evidence anchors; key material is never written to Git, logs, or manifests.

## PostgreSQL compatibility and repository contract

Physical backups require the same PostgreSQL major version recorded in the signed manifest.
Major-version upgrades require a supported logical or `pg_upgrade` migration followed by a new
physical backup. Restore hosts must supply compatible locale/collation libraries, extensions,
shared libraries, configuration includes, ownership, and permissions. Data checksums are enabled
at `initdb` time or offline with `pg_checksums`, not in `postgresql.conf`.

Tablespace archives restore only to absolute, empty destinations explicitly mapped by OID in the
signed manifest. The repository must provide same-filesystem atomic rename and durable `fsync`
semantics. Publication synchronizes artifacts, signature, manifest, staging directory, and the
parent after rename; another storage interface must guarantee equivalent durability.

## Installation and scheduled operation

1. Apply the PostgreSQL settings in `infra/backup/postgresql.conf.example`, adapting only paths.
2. Provision the environment-owned `emg-postgresql-backup-repository` PVC with the repository
   properties above. Its absence intentionally leaves the CronJob unschedulable; the checked-in
   deployment does not create colocated storage or choose a provider.
3. Synchronize `emg-postgresql-backup-secrets`. It supplies the least-privilege backup DSN,
   escrow reference, and executable encryption/sign/verify wrappers. Decryption authority is
   deliberately absent from the scheduled pod.
4. The `emg-postgresql-backup` CronJob runs daily at 01:00 UTC. It forbids concurrency, has a
   two-hour deadline, one retry, bounded history, no service-account token, and explicit resource
   limits. Treat a missing final directory, nonzero Job exit, or missing verified evidence event
   as failure. Staging directories are never recovery candidates.
5. Configure PostgreSQL's `archive_command` to call `tools/backup/archive-wal.sh "%p" "%f"`.
6. Run `tools/backup/verify-backup.sh MANIFEST` after replication to each failure domain.
7. Alert on backup age over 24 hours, WAL archive age over five minutes, checksum failure,
   repository capacity, or encryption-wrapper failure.

The full-backup script requests a fast checkpoint, streams WAL into the backup, encrypts every
artifact, generates a canonical JSON manifest with SHA-256 and byte sizes, verifies it, and only
then atomically publishes the backup directory. The scheduled wrapper then verifies the detached
signature and artifact hashes and atomically writes `recovery-evidence/BACKUP_ID.json`. It emits
the non-secret `emg.recovery.backup.verified` JSON event; failure emits
`emg.recovery.backup.failed`, exits nonzero, and leaves no success evidence.

For deterministic retention review, set an explicit clock, for example
`EMG_RETENTION_NOW=2025-01-01T00:00:00Z tools/backup/retention.sh`. Review the JSON plan, confirm a
newer verified full backup exists and required WAL is protected, then repeat with
`--apply REVIEWED_PLAN_ID`. The canonical UTC clock must be within 24 hours of system time. Apply
recomputes the plan and aborts if any valid manifest changed. RC-1B does not delete WAL, so it
cannot remove segments required by the oldest retained valid chain.

## Full restore

1. Declare the incident, freeze application writes, preserve logs, and record the desired recovery
   point. Never restore over the original data directory.
2. Select the newest manifest that predates corruption and run `verify-backup.sh` against the
   repository copy.
3. Provision an empty absolute target directory with capacity for the restored cluster.
4. Set `EMG_RECOVERY_MODE=isolated-restore`,
   `EMG_RECOVERY_CONFIRMATION=RESTORE_INTO_EMPTY_TARGET`, and a recorded
   `EMG_RECOVERY_TARGET_ID` that is not `production`. Set the decryption wrapper and run
   `tools/backup/restore-full.sh BACKUP_DIRECTORY TARGET_DATA_DIRECTORY`.
5. Start an isolated PostgreSQL instance on the restored directory with application egress and
   credentials disabled.
6. Set `EMG_RESTORE_DSN` to a secret-managed verifier connection and run
   `tools/backup/verify-recovery.sh`.
7. Record manifest ID, timestamps, operator, command results, row counts, integrity JSON, and the
   authorization approving promotion. Reconnect applications only after approval.

## Point-in-time restore

Follow the full-restore isolation steps, then run
`tools/backup/restore-pitr.sh BACKUP_DIRECTORY TARGET_DATA_DIRECTORY TARGET_TIME [ACTION]`, where
the target is an exact UTC RFC3339 second and action is `promote`, `pause`, or `shutdown`. The tool
writes `recovery.signal` and deterministic recovery settings that fetch encrypted WAL through
`restore-wal.sh`. Start PostgreSQL and monitor its logs until the recovery target is reached. A
missing WAL file, timeline mismatch, or target after the available archive is a failed recovery,
not permission to choose a different target silently.

Run recovery verification after PostgreSQL leaves recovery (or while paused for inspection). It
checks readiness, required relations, and uses the production audit-pipeline algorithms to
recompute both the audit-event and evidence-custody hash chains. Any sequence gap, broken link,
schema-invalid row, or hash mismatch fails the restore.

Signed manifests anchor each ledger's row count, terminal sequence, and terminal hash. Recovery
must match these anchors as well as recompute the authoritative production chains. This detects
empty replacement and tail truncation relative to the backup. Without an externally held signing
key, an attacker able to replace both backup and manifest could forge anchors; detached signature
custody is mandatory.

## Disaster recovery and rehearsal

The incident commander owns recovery-point selection and the final data-loss statement. Database
operators restore; security controls access to decryption keys; the evidence owner reviews ledger
integrity; the service owner approves traffic restoration. Keep the damaged system immutable for
forensics where feasible. DNS, load balancer, credential rotation, and client reconnection are
environment-specific and intentionally outside these provider-neutral scripts.

At least every 90 days, and after PostgreSQL upgrades, encryption changes, or material data-growth
events, rehearse in an isolated environment:

1. Randomly select one retained full backup and a target time requiring WAL replay.
2. Restore without access to the primary host, using escrowed keys and documented credentials.
3. Run manifest, database, audit-chain, and custody-chain verification.
4. Measure start-to-verified RTO and the last recoverable transaction's RPO.
5. Record backup ID, target, byte volume, timings, failures, evidence output, and remediation owner.
6. Destroy rehearsal credentials and data according to environment handling policy.

A rehearsal passes only when RPO is at most five minutes, RTO is at most four hours, both ledgers
are intact, and the evidence record is reviewed. A failed rehearsal opens a production-readiness
blocker; it must not be represented as successful merely because PostgreSQL started.

### Authoritative recovery order and consistency gates

1. Quiesce or isolate writes and preserve incident evidence.
2. Restore PostgreSQL and replay WAL to the authorized point. PostgreSQL contains authoritative
   graph/revision state, Audit and custody ledgers, mutation/outbox and dispatch state, and the
   ADR-042 governed-search representation. Pending work remains pending; do not edit dispatch
   status to force startup.
3. Run `verify-recovery.sh`, migration-history/checksum validation, incident-specific row
   assertions, and outbox/dispatch counts. Missing WAL, incomplete recovery, or any integrity or
   migration mismatch is an abort condition.
4. Keep Neo4j isolated. It is a derived projection: discard stale state and run the existing
   deterministic PostgreSQL-to-Neo4j reconciliation path before graph reads. Never use Neo4j to
   fill a PostgreSQL gap.
5. Governed search is PostgreSQL-backed and revision-aware. Its retained representations are in
   the physical/PITR recovery set; validate retention/cardinality and representative authorized
   queries. Do not silently fall forward to another revision.
6. Follow production provisioning order, then run health, authorization, mutation,
   pending-dispatch, evidence, projection, and governed-search smoke checks while isolated.
7. The incident commander, database operator, security/evidence owner, and service owner review
   measured RPO/RTO and evidence before traffic release. A failed gate keeps the target isolated
   and requires a newly prepared empty target or an older authorized recovery point.

### Qualification states

- **IMPLEMENTED:** physical backup, continuous WAL scripts, encryption/signing wrapper contract,
  atomic publication, signed verification, retention floor, hardened daily CronJob, restore
  target guard, ledger verification, and real PostgreSQL full/PITR CI rehearsal.
- **CONFIGURATION REQUIRED:** remote claim/failure domain, archive command, approved egress/TLS,
  External Secrets store, custody and escrow, lifecycle/capacity controls, backup/WAL-age alerts,
  restore host, and operator access.
- **LIVE QUALIFICATION REQUIRED:** observe backup/WAL delivery, independently read the remote
  copy, exercise escrowed decryption and rotation, execute isolated target-environment PITR,
  rebuild Neo4j, validate dispatch and governed search, measure RPO/RTO, and review evidence. CI
  evidence is not production certification.

## Known boundaries

RC-E installs provider-neutral Kubernetes scheduling but does not close provider deployment,
cross-region replication, PostgreSQL HA/failover, key-manager selection, target storage/custody
configuration, monitoring backend selection, or completion of the first witnessed production
rehearsal. Those remain deployment/operations readiness work and must be tracked separately.
