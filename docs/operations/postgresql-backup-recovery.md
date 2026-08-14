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
3. Supply the environment-owned `EMG_IDENTITY_RECOVERY_DSN` authenticating as
   `emg_identity_migrator`, then run `verify-recovery.sh`. Verification requires the Identity
   schema and history and invokes `invalidate-identity-refresh-state.sh` transactionally before
   Identity may become ready. The operation revokes every restored family and token, is
   idempotent, uses an auditable PostgreSQL application name, and exposes no token hashes or row
   counts. Migration-history/checksum validation, incident-specific row assertions, and
   outbox/dispatch counts follow. Missing WAL, incomplete recovery, invalid Identity authority,
   or any integrity or migration mismatch is an abort condition. This step is only reachable
   inside the ADR-043 Amendment 1 fence -- see the procedure immediately below, which governs
   everything from before restore begins through the point Identity is permitted to serve traffic
   again.

#### ADR-043 Amendment 1 recovery network/workload fence (A9)

This procedure governs Identity specifically; it does not change, precede, or substitute for
steps 1-7 above for Audit/PostgreSQL/Neo4j/governed-search recovery, and it runs concurrently with
them (restore in step 7 is the same physical restore both procedures depend on). The **recovery
coordinator** (A9.1) is the single accountable actor for every step below; every action is
auditable (actor identity, action, target, timestamp).

Round-2 remediation replaced three previously non-executable steps with real, checkable tooling:
the CNI-enforcement prerequisite (step 2) is now a schema-validated attestation, never a bare
comment; the database-session fence (step 4) runs a real termination-and-proof operation against
the governed database-bootstrap-administrator credential, never a prose instruction; and Stage-50
recovery qualification (step 10) is a distinct Job/command that requires and validates all three
A9 evidence records, never the ordinary `validate-database` path silently substituted for it.

Round-3 remediation closed a narrower gap in step 10: Stage-50 previously only checked that each
evidence file's `verified_by` was *present*, not that it matched the actual fence owner identified
in step 1 (A11 requires evidence to be "attributable to the fence owner for the recovery being
validated," not merely accompanied by some non-empty actor string). Step 10 now requires an
explicit `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER` input -- the same identity recorded in step 1
-- and compares it, by exact string match, against every evidence file's `verified_by`; a mismatch
(including a differently-cased identity) denies recovery qualification exactly like a missing or
stale evidence file would. This value is a validation input and audit-trail comparison target, not
a credential. Step 10 also now compares each network-fence evidence file's recorded `namespace`
against the namespace the Stage-50 recovery Job is itself running in (via the Kubernetes downward
API, never a manually supplied value), closing the same non-attribution-but-unchecked gap for
namespace binding.

1. Identify and record the recovery coordinator/fence owner for this event. This identity is used
   verbatim, later, as `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER` in step 10 -- record it exactly
   as it will be supplied to every fence-writing script's `EMG_RECOVERY_FENCE_ACTOR`/
   `EMG_IDENTITY_RECOVERY_FENCE_ACTOR` input in steps 2, 3b, 5, and 12, since Stage-50 now requires
   an exact (case-sensitive, unnormalized) match against all three A9 evidence records.
2. Prove CNI/NetworkPolicy egress-enforcement qualification: run
   `tools/backup/identity-cni-qualification-attest.sh` with `EMG_CNI_QUALIFICATION_CLUSTER`
   identifying the target cluster and `EMG_CNI_QUALIFICATION_METHOD` describing how enforcement was
   confirmed out of band (for example, `gcloud container clusters describe --format
   "value(networkConfig.datapathProvider)"` reporting `ADVANCED_DATAPATH` for GKE Dataplane V2, or
   an equivalent Calico/Cilium verification). This records
   `REPOSITORY_CNI_QUALIFICATION_CONTRACT` evidence; it is not, and cannot be,
   `LIVE_CNI_ENFORCEMENT_WITNESS` proof of actual packet-level enforcement -- no automated
   packet-level test can run from this repository. A qualification record remains valid for 90
   days (matching this document's own rehearsal cadence); re-attest if it has expired.
3. Establish State 1 (`RECOVERY_RECONCILIATION_FENCE`, A9.2-A9.4 Phase 1):
   a. Withdraw `emg-identity` from client traffic and scale it to zero replicas
      (`kubectl scale deployment/emg-identity --replicas=0`); confirm zero routable endpoints
      (`kubectl get endpoints emg-identity`).
   b. Copy `identity-db-egress.phase1.example.yaml` to a real manifest with the environment-resolved
      PostgreSQL `ipBlock`/port filled in, then run
      `tools/backup/identity-recovery-fence.sh` with `EMG_RECOVERY_FENCE_PHASE=phase1`. The script
      applies the policy, reads back both the object itself and every other NetworkPolicy in the
      namespace, and refuses to write evidence unless the live `podSelector` exactly matches
      `{emg-identity-migration, emg-identity-recovery-reconcile}` AND no other policy in the
      namespace grants Identity-labeled pods overlapping reachability to the same PostgreSQL target
      (the additive-policy-bypass check -- see `external-egress.example.yaml`'s comment for why
      this exists).
4. Capture positive evidence for step 3: confirm the Phase 1 evidence file exists and passes
   `python -m emg_persistence.provisioning validate-recovery-fence` with
   `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_PHASE=phase1`. Do not proceed on a script exit code alone.
5. Establish the database-session fence (A9.3) with positive evidence: run
   `tools/backup/identity-session-fence.sh` using the governed
   `EMG_DATABASE_BOOTSTRAP_ADMIN_DSN` credential (never `emg_identity_app`, never
   `emg_identity_migrator` either -- see `recovery_evidence.py` for why). It identifies every
   PostgreSQL session authenticated as `emg_identity_app` against the recovery target, terminates
   each one, polls until the server-side count is genuinely zero, and writes evidence only after
   that re-query succeeds. The coordinator's own connection is excluded structurally (it never
   authenticates as `emg_identity_app`), not by an exception list.
6. Rotate/revalidate the external Approved Recovery Authority generation per A3.2 (outside this
   repository's scope to select a provider; use the environment's qualified authority).
7. Restore/PITR PostgreSQL per the Full restore / Point-in-time restore sections above, with the
   Phase 1 network fence (step 3b) still in force.
8. Confirm Identity non-readiness: an attempted readiness or refresh-token check against the
   restored target observes the pair mismatch (A4/A8) and is denied. This step is only reachable if
   some fence were bypassed -- it is defense in depth, not the primary control, and its expected
   result is failure.
9. Reconcile: run `identity-reconcile` (A6) with the rotated `(generation, authority_revision)`
   pair.
10. Run Stage-50 RECOVERY QUALIFICATION (A11) -- not ordinary Stage-50: invoke
    `python -m emg_persistence.provisioning validate-recovery-qualification` (or apply
    `infra/kubernetes/base/provisioning-validation-recovery.yaml` after populating the
    `emg-provisioning-validate-recovery-input` Secret with the step 2, 4, and this step's own
    target-environment/phase/cluster/expected-owner values plus the three evidence files from steps
    2, 4, and 5). `expected-owner` must be exactly the fence-owner identity recorded in step 1 --
    Stage-50 compares it verbatim against every evidence file's `verified_by`. The expected
    namespace is not a coordinator-supplied value: it is read from the Job's own live Kubernetes
    namespace via the downward API and compared against the network-fence evidence's recorded
    `namespace`. This runs full database validation AND requires and validates all three A9
    evidence records (network fence, database-session fence, CNI qualification) for the exact
    environment, phase, fence owner, and namespace being recovered; it must PASS before continuing.
    It never silently falls back to ordinary `validate-database` mode, and ordinary deployment's
    Stage-50 Job never requires or consults any of this evidence.
11. Independently reconfirm, directly against the Approved Recovery Authority and against the
    controller-materialized file, that both still report the exact pair recorded in step 9
    (A9.6 steps 3-4) -- never inferred from steps 9-10 alone.
12. Establish State 2 (`RECOVERY_READINESS_QUALIFICATION_FENCE`, A9.4 Phase 2): copy
    `identity-db-egress.phase2.example.yaml` to a real manifest with the same PostgreSQL
    `ipBlock`/port, then run `identity-recovery-fence.sh` with `EMG_RECOVERY_FENCE_PHASE=phase2`.
    The script refuses to write evidence unless the live `podSelector` exactly matches
    `{emg-identity-recovery-qualify}` -- in particular, excludes `emg-identity` -- and unless no
    other policy in the namespace grants overlapping reachability (the same additive-bypass check
    as step 3b).
13. Capture positive evidence for step 12: confirm the Phase 2 evidence file passes
    `validate-recovery-fence` with `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_PHASE=phase2`.
14. Start the fresh qualification workload: `kubectl scale deployment/emg-identity-recovery-qualify
    --replicas=1`. This is a gated step performed only after step 13, never a byproduct of an
    earlier one.
15. Prove Ready: `kubectl wait --for=condition=Ready pod -l
    app.kubernetes.io/name=emg-identity-recovery-qualify`. This exercises the workload's own
    `emg_identity_app` database session over the Phase 2 network path (A8 item 2), not an assumption
    carried over from steps 11-13.
16. Prove not client-routable: confirm `kubectl get endpoints emg-identity` still shows zero
    addresses (the qualification workload is never selected by that Service --
    `infra/kubernetes/base/identity-recovery.yaml`) and that `emg-identity` itself remains at zero
    replicas.
17. Record recovery-witness approval of the evidence from steps 2-16, per the recovery governance
    contract.
18. Explicit transition of the network fence to normal policy, performed only now: run
    `identity-recovery-fence.sh` with `EMG_RECOVERY_FENCE_PHASE=normal` (excludes every
    recovery-only identity, restores the ordinary `{emg-identity, emg-identity-migration}` egress
    contract) and confirm its evidence passes `validate-recovery-fence` with
    `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_PHASE=normal`.
19. Stop the qualification workload: `kubectl scale deployment/emg-identity-recovery-qualify
    --replicas=0`.
20. Start the normal Identity workload: `kubectl scale deployment/emg-identity --replicas=1`.
21. Prove normal readiness: `kubectl wait --for=condition=Ready pod -l
    app.kubernetes.io/name=emg-identity`, then restore `emg-identity` to its client-traffic path
    and confirm `emg-identity` Service endpoints are non-empty and a live `/readyz` check against
    the restored client path succeeds. No earlier step performs any part of this -- reconciliation
    success (step 9), Stage-50 recovery qualification PASS (step 10), the Phase 2 transition (step
    12), or Ready (step 15) alone never releases traffic; only completing steps 17-21 in order does.
22. Archive the recovery evidence (the CNI qualification, session-fence, and fence-evidence files
    from steps 2/4/5/11/13/18, Stage-50 recovery-qualification output, witness record, timings) with
    the rest of the incident's recovery-evidence record.

**Fail-closed branches.** Any of the following halts the procedure at its current state and
requires re-verification of every fence from the beginning of the affected state, not a resume from
an assumed midpoint:

- Step 2's CNI qualification evidence is missing, malformed, wrong-target/cluster, or older than 90
  days: halt before step 3; no fence in this procedure may be treated as enforceable.
- Step 3's network-fence evidence is missing, malformed, wrong-phase, wrong-target, older than
  `EMG_IDENTITY_RECOVERY_FENCE_MAX_AGE_SECONDS` (default 900s), or the additive-policy-bypass check
  finds another policy granting overlapping reachability: reconciliation (step 9) must not begin;
  re-run steps 3-4.
- Step 5 cannot positively confirm zero surviving `emg_identity_app` sessions (inspection failure,
  termination failure, or a survivor after the poll window): halt before restore; do not proceed to
  step 7. No evidence file is written for a failed attempt.
- Step 10 (Stage-50 recovery qualification) fails after step 9 commits: fences remain closed
  notwithstanding the committed reconciliation; do not attempt step 12. Distinguish which of the
  three required evidence records (network, session, CNI) caused the failure from the command's
  error output before retrying. A failure naming an attribution or namespace mismatch means either
  step 1's recorded fence owner and the `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER` input diverged,
  or one of steps 2/3b/5/12 was actually run by a different actor than step 1 identified (or against
  the wrong namespace) -- treat this as a process integrity failure, not merely a retry: confirm who
  actually performed each fence step before re-running any of them.
- Step 12's evidence cannot be positively verified, or the additive-bypass check trips: treat the
  transition as not having occurred; do not run step 14 (do not start the qualification workload).
- Step 12's read-back podSelector includes `emg-identity` or excludes
  `emg-identity-recovery-qualify`: treat as a Phase 2 establishment failure; revert to and
  re-verify State 1 (steps 3-4) before re-attempting.
- Step 15's readiness check fails or times out: no client-service restoration follows; do not run
  step 18. Diagnose and retry from step 14, or from step 3 if network evidence cannot be
  re-confirmed.
- Step 16 finds a non-empty `emg-identity` endpoint list, or `emg-identity` at nonzero replicas, at
  any point before step 20: treat as a client-traffic fence failure; immediately re-confirm
  `emg-identity` is scaled to zero and halt before step 17.
- Step 17 (witness approval) is withheld: do not run step 18 regardless of how many earlier steps
  passed.
- The coordinator crashes or is replaced at any point: the resumed coordinator re-verifies every
  prior step's evidence -- including re-running step 4, step 5, or step 13 against the live target
  -- before proceeding; no step is assumed still valid from before the crash.
- A retry of the whole procedure restarts from step 3 with the network fence reset to Phase 1, not
  from an assumed Phase 2 state; only step 9 (A6) is idempotent in the narrow sense of being safely
  repeatable with the same pair, and the database-session fence (step 5) is safe to re-run
  unconditionally (a zero-session re-run is a valid, evidenced no-op).

**Normal restart/rollout.** Neither this procedure nor any of its steps runs during an ordinary pod
restart or rollout with a matching authority pair -- `identity-recovery-fence.sh`,
`identity-session-fence.sh`, and `identity-reconcile` are invoked only by an explicit recovery
event, never by routine deployment tooling (see the `recovery-only` bootstrap-stage annotation on
`emg-identity-recovery-reconcile`, `emg-identity-recovery-qualify`, and
`emg-provisioning-validate-recovery`). Ordinary Stage-50 (`emg-provisioning-validate`,
`validate-database`) never requires or consults any A9 evidence.

**Environment prerequisite.** Enforcement of every `Egress` NetworkPolicy in this procedure requires
a CNI that implements Kubernetes `NetworkPolicy` egress (GKE Dataplane V2, Calico, Cilium, etc.).
Step 2's CNI qualification evidence is the governed, checkable record of this precondition -- it
gates Stage-50 recovery qualification (step 10) and therefore blocks the entire procedure if
missing or stale, but it remains a repository-owned *contract* (schema and freshness only), never a
live packet-level enforcement witness. On a CNI that only enforces ingress, the network-layer fence
is advisory only regardless of how fresh the qualification record is, and the recovery coordinator
must substitute an equivalent environment-owned control (firewall rule, security group, private
connectivity scope) before treating State 1/State 2 as established.
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
