# EMG ADR-039 — Backup, PITR and Recovery Governance

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-09
**Baseline:** `develop` at `e7a7ef4`.
**Resolves:** D-A-005 (`EMG_ARCHITECTURE_DECISION_REGISTER.md` — "Backup, PITR, and Recovery
Metadata Governance"); the dangling "ADR-031" citation in `EMG_ADR-032_…md` §Future
Compatibility (no ADR-031 document has ever existed; the citation was replaced with the
D-A-005 tracking reference on 2026-08-03 pending this ADR).
**Related:** ADR-017 (disaster-recovery *strategy* — recovery-point prioritization only, not
mechanics), ADR-032 (Knowledge Graph Schema Versioning — cites this ADR for backup
schema-version metadata), ADR-034 (Security State and Service Trust — precedent this ADR
follows for externally-supplied, non-committed credential/wrapper handling).

> **This ADR ratifies an already-implemented system.** It documents the backup, PITR,
> retention, manifest, evidence-anchor, and encryption-wrapper mechanics already present at
> `infra/backup/` and `tools/backup/` at the stated baseline. It authorizes no new code,
> introduces no new mechanism, and changes no existing file or behavior. It is a governance
> record, not a design document.

---

## 1. Context

**FACT.** `docs/architecture/EMG_ARCHITECTURE_DECISION_REGISTER.md` records **D-A-005**
("Backup, PITR, and Recovery Metadata Governance") as **Open** since 2026-08-03, with the
explicit blocking question: *"Which decision governs backup content, PITR procedure,
retention, and schema-version metadata in backups? Does it extend ADR-017 or require a new
ADR?"*

**FACT.** `docs/architecture/EMG_ADR-032_KNOWLEDGE_GRAPH_SCHEMA_VERSIONING_AND_EVOLUTION.md`
§Future Compatibility previously cited a non-existent "ADR-031" for the same requirement
(backup schema-version metadata for PITR to the correct ontology version). A repository-wide
search on 2026-08-03 confirmed no ADR-031 document exists under any identifier or filename;
the citation was replaced with the D-A-005 tracking reference pending this ADR.

**FACT.** `docs/architecture/EMG_PRODUCTION_READINESS_ROADMAP.md` lists "Backup, restore,
PITR, and disaster-recovery procedure" among unspecified production-readiness gaps.

**FACT.** ADR-017 §5 governs disaster-recovery *strategy* only (recovery-point
prioritization); it does not specify backup mechanics, PITR procedure, retention policy, or
manifest/schema-version metadata. No previously accepted ADR governed any of these.

**FACT.** Since D-A-005 was recorded, a complete implementation has been added:
`infra/backup/` (`backup.example.yaml`, `restore.example.yaml`, `postgresql.conf.example`,
`manifest.schema.json`, `sample-manifest.json`, `README.md`); `tools/backup/` (`full-backup.sh`,
`archive-wal.sh`, `restore-full.sh`, `restore-pitr.sh`, `restore-wal.sh`, `retention.sh`,
`verify-backup.sh`, `verify-recovery.sh`, `verify-evidence-ledger.py`, `backup_manifest.py`,
`build_manifest.py`, `common.sh`); the authoritative runbook
`docs/operations/postgresql-backup-recovery.md`; and conformance/integration tests
`tests/infrastructure/test_backup_recovery.py` and `test_backup_recovery_integration.py`.

**FACT.** The implementation has been independently, adversarially verified, including
against a real, local PostgreSQL 16.14 cluster: a real physical backup, continued WAL
archiving, a real full restore, a real point-in-time restore to an exact target timestamp
(confirmed to include exactly the transactions before the target and none after), and a
deliberate evidence-ledger tamper (an audit row was deleted from the restored database) that
`verify-recovery.sh` correctly detected and failed on. Independently, two manifest-validation
gaps between the JSON Schema and the canonical Python validator were found by the same
verification and have since been closed in the schema (duplicate-tablespace-mapping and
evidence-anchor-consistency checks were already canonical in the Python validator; a
non-UTC `createdAt` gap was found and closed in the same pass). One narrow, structurally
unclosable gap remains and is documented in §6 below.

## 2. Problem Statement

EMG PostgreSQL is authoritative for EMG relational state, including the audit-event and
evidence-custody ledgers. Without a governed decision: (a) the retention window, RPO/RTO
objectives, and manifest contract existed only as implementation detail with no ratified
architectural authority; (b) D-A-005 remained formally open while a complete, tested
implementation already existed — an inconsistency between this repository's own governance
record and its own code; (c) future changes to backup mechanics had no accepted baseline to
be evaluated against, and ADR-032's schema-versioning-in-backups requirement remained an
acknowledged but ungoverned dependency.

## 3. Decision

EMG adopts the backup, PITR, retention, manifest, evidence-anchor, and encryption-wrapper
architecture already implemented at `infra/backup/` and `tools/backup/`, as described in
§4–§13 below, as the governing decision for D-A-005. Sections §4–§13 are the operative
decision; each restates existing, already-implemented behavior and cites the files that
define it. This ADR introduces no new mechanism and changes no existing file.

## 4. Operational Model

Physical backup, not logical (`pg_dump`) backup, is the governed mechanism:
`pg_basebackup --format=tar --gzip --wal-method=stream --checkpoint=fast
--manifest-checksums=SHA256` (`tools/backup/full-backup.sh`). A full backup runs daily at
01:00 UTC. Every artifact (base archive, WAL archive, PostgreSQL's own internal manifest, and
any tablespace archive) is encrypted before it enters the repository; the backup is staged
under `.staging-<id>`, `fsync`'d file-by-file and directory-wide, then published via a
same-filesystem atomic `rename(2)` to `full/<id>` — a staging directory is never a recovery
candidate, and a crash mid-backup leaves no partially-visible published backup. PostgreSQL
archives WAL continuously and independently of the daily full-backup cadence (§6).

## 5. Backup Repository

The repository is a **provider-neutral, mounted POSIX filesystem contract**
(`EMG_BACKUP_REPOSITORY`), not a specific storage product. Local disk, an object-storage
gateway mount, or offline media all satisfy the contract without changing any tool. This ADR
does not select a storage product or provider; that remains a deployment decision. Backups
must be replicated to at least one administratively separate failure domain — the repository
interface being a filesystem mount is what makes that an operator/deployment concern rather
than something these tools implement directly.

## 6. PITR (Point-in-Time Recovery)

PostgreSQL's `postgresql.conf` (`infra/backup/postgresql.conf.example`) enables continuous
WAL archiving with `archive_timeout = 300`, invoking `tools/backup/archive-wal.sh "%p" "%f"`
as `archive_command`. Archiving is idempotent (a re-invocation for an already-archived
filename verifies the existing artifact's hash rather than silently overwriting or silently
skipping) and filename-validated (WAL segment / timeline-history filename patterns only,
rejecting anything else before it can be used to construct a repository path).

`tools/backup/restore-pitr.sh BACKUP_DIRECTORY TARGET_DATA_DIRECTORY TARGET_TIME [ACTION]`
performs a full restore (§ below) and then writes `recovery.signal` plus deterministic
recovery settings (`backup_manifest.py::pitr_config`): `restore_command` invoking
`restore-wal.sh`, `recovery_target_time` (the operator-supplied target, which must be an
exact UTC RFC3339 second — no relative or ambiguous targets), `recovery_target_timeline =
'latest'`, `recovery_target_inclusive = true`, and `recovery_target_action` (`promote`,
`pause`, or `shutdown`). A missing WAL file, a timeline mismatch, or a target beyond the
available archive is a failed recovery, not an implicit alternate target.

## 7. Manifest Governance

Every backup carries a signed, schema-versioned JSON manifest (`schemaVersion: 2`,
`infra/backup/manifest.schema.json`, JSON Schema Draft 2020-12) recording: PostgreSQL major
version, start/stop LSN and WAL boundaries, database identity, per-artifact role/path/
size/SHA-256/encrypted flag, tablespace OID→path mappings, and evidence-ledger anchors (§8).

**The canonical, authoritative validator is `tools/backup/backup_manifest.py::validate_manifest`.**
The JSON Schema is a secondary, machine-readable expression of the same contract, used for
schema-level tooling and CI (`.github/workflows/ci.yml` "Validate backup and recovery
artifacts"). Every operational script (`full-backup.sh`, `restore-full.sh`, `verify-backup.sh`,
`retention.sh`) calls the Python validator; none relies on `schema-validate` alone. One
constraint the Python validator enforces is not, and cannot be, fully expressed in JSON
Schema without changing the manifest's data shape: two `tablespaces` entries sharing the same
`oid` with *different* `restorePath` values are rejected by the Python validator but accepted
by the schema, because JSON Schema (any draft) has no mechanism to compare one array item's
field against a sibling item's field without either a non-standard extension or restructuring
the array into an object keyed by `oid` — a manifest-format change this ADR does not make.
This is a documented, tested (`tests/infrastructure/test_backup_recovery.py::test_duplicate_tablespace_oid_with_differing_restore_path_is_python_only`),
and intentionally accepted residual: the canonical validator is the enforcement point, and it
is the only one every operational script actually calls.

## 8. Evidence Anchors

Each manifest embeds `evidenceAnchors.audit` and `.custody`: row count, terminal sequence, and
terminal hash for the `audit_events` and `evidence_custody_events` tables at backup time
(`tools/backup/build_manifest.py::anchor`). These anchors are not a new evidence mechanism —
the audit-event and evidence-custody ledger schemas and their hash-chain semantics are
established by their own existing implementation (e.g.
`tools/seed-data/postgres/001_audit_events.sql`, `003_evidence_custody.sql`) and are
unmodified by this ADR. At recovery time, `tools/backup/verify-evidence-ledger.py` recomputes
both chains using the **production** `PostgresAuditEventStore`/`PostgresCustodyEventStore`
classes from `emg_audit_pipeline` — not a parallel reimplementation — and compares the
recomputed row count/terminal sequence/terminal hash against the manifest's anchors. A
mismatch (empty-table replacement or tail truncation relative to the backup) fails recovery
verification. Because the manifest's own integrity depends on its detached signature (§10),
an anchor cannot be forged without also forging a valid signature.

## 9. Retention

`tools/backup/retention.sh` and `backup_manifest.py::retention_plan` keep every full backup
younger than `EMG_RETENTION_MINIMUM_DAYS` (default 35) plus, regardless of age, at least the
`EMG_RETENTION_MINIMUM_COUNT` (default 2) most recent **valid** backups — a backup that fails
validation is never counted toward the retained minimum. Retention is plan-then-apply: a plan
is a deterministic JSON document identified by a SHA-256 hash of its own content; `--apply`
recomputes the plan fresh and refuses to proceed unless the recomputed hash matches the
operator-reviewed plan ID, so repository state changing between review and apply aborts the
apply rather than deleting under a stale plan. Retention deletes only full-backup directories;
it never deletes WAL, because safe WAL pruning requires PostgreSQL-aware boundary information
this tool does not compute — WAL retention remains an explicit operator responsibility.

## 10. Encryption Wrapper Model

Every base-backup file, tablespace archive, and archived WAL segment is encrypted before
entering the repository. The runtime supplies four executable wrappers via environment
variables, never via committed code or configuration:
`EMG_BACKUP_ENCRYPT_COMMAND`/`EMG_BACKUP_DECRYPT_COMMAND` (each an `INPUT OUTPUT`
executable) and `EMG_MANIFEST_SIGN_COMMAND`/`EMG_MANIFEST_VERIFY_COMMAND` (each a
`MANIFEST SIGNATURE` executable), plus `EMG_BACKUP_KEY_REFERENCE`, a non-secret escrow
identifier. This ADR does not select an encryption product, KMS, or signing scheme — it
governs only the wrapper contract's shape. Wrappers must fail non-zero on error; key material
is never written to Git, logs, or manifests; key rotation must preserve prior keys for the
full retention window; a tested, access-controlled escrow copy of decryption material must
exist in a separate failure domain.

## 11. Scheduler Assumptions

This ADR assumes, but does not select, an operator-provided scheduler (cron, a systemd timer,
or an equivalent) invoking `tools/backup/full-backup.sh` daily and `tools/backup/retention.sh`
periodically. WAL archiving is not a separately scheduled job — it is PostgreSQL's own
`archive_command` invoking `archive-wal.sh` per segment. Scheduler product selection is
explicitly out of scope (§14).

## 12. Recovery Verification

`tools/backup/verify-recovery.sh` checks, against the freshly restored instance: PostgreSQL
major-version match and database-identity match against the manifest, presence of the
`audit_events`/`evidence_custody_events` tables and the `public` schema, that the instance has
left recovery (`NOT pg_is_in_recovery()`), and — when the corresponding environment variables
are supplied — required extensions, the expected recovery timeline, that PITR replay did not
proceed past the requested target time, and an operator-supplied SQL assertion. It then
invokes evidence-ledger verification (§8). Any failure is a failed recovery; there is no
partial-pass state.

## 13. RPO/RTO

**RPO: 5 minutes**, bounded by `archive_timeout = 300` (continuous WAL archiving). An
incident that also destroys the live database host may lose up to five minutes of
transactions after the most recently durably archived WAL segment. **RTO: 4 hours**, covering
incident declaration through controlled service re-entry. Both are documented as operational
targets, not guarantees — `docs/operations/postgresql-backup-recovery.md` states explicitly
that a successful quarterly rehearsal is the evidence the current data volume and
infrastructure can meet them, and `tests/infrastructure/test_backup_recovery.py::test_config_contracts_parse`
asserts these exact values (`rpoMinutes: 5`, `rtoMinutes: 240`) are what
`infra/backup/backup.example.yaml` actually declares.

## 14. Security

Encryption at rest is mandatory for every artifact (§10); manifests are detached-signed, and
the signature — not the manifest's own SHA-256 fields alone — is what authenticates restore
roles, LSN/WAL boundaries, tablespace mappings, and evidence anchors: without externally held
signing-key custody, an attacker able to replace both a backup and its manifest could forge
anchors, which is why detached-signature custody is a mandatory requirement, not an
optional hardening. Path-traversal defenses are structural: manifest artifact paths are
basename-only (`Path(name).name != name` is rejected by `backup_manifest.py`), tablespace
restore destinations must be absolute and outside the target data directory
(`restore-full.sh`), an existing `pg_tblspc` entry is only ever replaced if it is already a
symlink, backup IDs and WAL filenames are validated against strict allowlist patterns before
being used to construct filesystem paths, and every script sets `umask 077`. Authorization
Authority / IdP signing-key custody (a separate concern, tracked continuously since the prior
architecture review and the ADR-038 capability verification) remains unaddressed and is not
in scope here.

## 15. Future HA Considerations

Explicitly out of scope, and not decided by this ADR: cross-region replication, PostgreSQL
high-availability/failover topology, selection of a specific encryption/KMS or signing
product, selection of a specific scheduler product, selection of a monitoring/alerting
backend, and completion of the first witnessed production disaster-recovery rehearsal. These
remain deployment/operations readiness work, to be tracked separately from this architectural
ratification.

## 16. Alternatives Considered

These reconstruct the rationale already visible in the implementation's own structure and
documentation; they are not a new deliberation.

- **Logical backup (`pg_dump`/`pg_dumpall`) instead of physical.** Rejected: logical backup
  cannot support point-in-time recovery via WAL replay, and cannot preserve exact LSN/WAL
  boundaries the manifest anchors against. Physical backup (`pg_basebackup`) is the only
  mechanism consistent with the PITR requirement in §6.
- **A specific managed cloud backup/snapshot service as the repository.** Rejected as the
  *only* supported model: `infra/backup/README.md` frames the repository as "provider-neutral"
  and a "POSIX filesystem mount," so that a specific storage product can be selected per
  deployment without changing any tool. A managed service is not excluded — it can be mounted
  or gatewayed to satisfy the same filesystem contract.
- **Vendor-specific encryption/KMS integration built into the scripts.** Rejected in favor of
  the external-wrapper model (§10), consistent with how ADR-034 already treats credential
  material as externally supplied rather than embedded — this keeps the tooling free of any
  specific encryption or key-management product dependency.
- **JSON Schema as the sole manifest validator.** Rejected: JSON Schema cannot express every
  constraint the manifest requires (§7) without a data-format change. The canonical, sole
  source of truth is the Python validator; the schema is a secondary, intentionally narrower
  check.
- **Automatic WAL pruning as part of retention.** Rejected: safe WAL pruning requires
  PostgreSQL-aware boundary information (the earliest WAL segment required by the oldest
  retained valid backup's own start boundary) that the retention tool does not compute; an
  incorrect automatic prune could destroy WAL still required for a retained backup. Retention
  therefore governs only full-backup directories (§9), and WAL pruning is left to the
  operator.

## 17. Consequences

**Positive.** D-A-005 is resolved; ADR-032's schema-versioning-in-backups dependency now has
a governing decision. Backup/PITR/retention/manifest/encryption behavior has a ratified
architectural baseline against which future changes can be evaluated. The gap between this
repository's governance record and its own code is closed.

**Negative — accepted.** None of the items in §15 are decided by this ADR; a full production
disaster-recovery posture still requires those follow-on decisions. The manifest-schema
residual documented in §7 remains a permanent property of using JSON Schema for this contract,
not a temporary gap expected to close later without a format change.

**Neutral.** No code, configuration, or test behavior changes as a result of this ADR. No
existing ADR is amended or reopened.

## 18. Non-Goals

This ADR does not: select a storage provider, encryption product, KMS, signing scheme,
scheduler product, or monitoring backend; define PostgreSQL HA/failover or cross-region
replication; change the manifest format, schema version, or backup mechanics from what is
already implemented; alter `emg-policy-engine`, persistence semantics, or any mutation route;
or govern Authorization Authority / IdP key custody.

## 19. Acceptance Criteria

- **AC-1.** D-A-005 is recorded as resolved by this ADR in
  `EMG_ARCHITECTURE_DECISION_REGISTER.md`.
- **AC-2.** Every governed area (§4–§14) matches the implementation at the stated baseline
  exactly, with no behavioral change introduced by this ADR.
- **AC-3.** The one documented manifest-validation residual (§7) is explicitly acknowledged as
  intentional and permanent, not silently omitted.
- **AC-4.** `EMG_PRODUCTION_READINESS_ROADMAP.md` references this ADR as the governing
  decision for backup/PITR/retention.

---

## Ratification

This ADR was reviewed against the current implementation and its own test/verification
evidence. It ratifies existing, already-verified behavior; it does not introduce new
architectural risk.

**Review Outcome: Accepted.** No blocking architectural issues were identified.
