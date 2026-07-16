# Sprint 7 Design — EPIC-04 Audit Completion: FEAT-04-2 + FEAT-04-3

Scope: **FEAT-04-2 (Provenance Record Model)** and **FEAT-04-3 (Digital
Evidence Chain-of-Custody)** only, per the approved controlled split of the
Backlog's Sprint 6 row ("Complete audit and provenance"). **FEAT-04-4 (Audit
Query & Reporting Interface) is explicitly deferred** to the immediate next
sprint and must land before EPIC-05 / Module 7 begins. **EPIC-04 remains
incomplete until FEAT-04-4 is delivered.**

This is an engineering-sequencing decision only: it does **not** modify the
frozen Architecture Baseline, does **not** redesign Module 6, and does **not**
require a new ADR. Module 6 is formally "Audit, Provenance & Digital Evidence"
(ADR-015; ADR-016 §1 row 3), so provenance and chain-of-custody are already
inside the frozen module scope.

Build order (approved): **FEAT-04-2 first** (freeze and verify the provenance
schema and the version-aware hashing), **then FEAT-04-3**. FEAT-04-4 was not
started.

## Traceability

| Requirement source | Where implemented |
| --- | --- |
| Backlog §3 FEAT-04-2 "Source/actor/timestamp/method tracking" | `emg_audit_client.provenance.ProvenanceRecord` (+ `TransformationStep`, `EventRef`); persisted on `AuditEvent`; hashed for version-2 events |
| Backlog §3 FEAT-04-3 "Evidence integrity and custody tracking" | `emg_audit_client.custody` models; `emg_audit_pipeline.custody_store` (in-memory + Postgres); `services/audit` custody router |
| Module 6 "Audit, Provenance & Digital Evidence"; ADR-016 §1 (CISO/CDO owner, Audit Platform Team steward) | Extends the Sprint 6 hybrid (contract lib + pipeline lib + thin service); no new service, no new ADR |
| Master Plan §15 / Backlog §14 DoD (security-reviewer sign-off for audit/provenance/classification changes) | Flagged for security-reviewer sign-off (this sprint touches provenance and audit behavior) |

## FEAT-04-2 — Provenance Record Model

`ProvenanceRecord` (all fields the approval enumerated): source system, source
component, originating actor, originating service principal, correlation id,
event timestamp vs. ingestion timestamp, classification, transformation history
(ordered `TransformationStep`s), parent/source event references (`EventRef` =
`(source_principal, event_id[, event_hash])`), evidence origin, collection
method, and a self-describing schema version.

It is an **optional, additive** field on `SubmittedAuditEvent` / `AuditEvent`.
The audit store assigns an **event** `schema_version` centrally from the
presence of provenance — version 1 (no provenance, Sprint 6-compatible) or
version 2 (provenance present). A producer never sets the version.

Provenance is validated and redacted before persistence, identical posture to
metadata: bounded transformation/parent counts and free-text lengths
(`AUDIT_PROVENANCE_*` error codes), and secret-shaped-substring redaction of
free-text fields.

### Version-aware canonical hashing (the backward-compatibility linchpin)

`emg_audit_pipeline.hashing.canonical_payload` is now version-aware:

- **Version 1** produces a payload **byte-for-byte identical to Sprint 6** — the
  `schema_version` and `provenance` keys are simply absent. Every existing
  Sprint 6 record therefore recomputes to its stored `event_hash` unchanged.
- **Version 2** additionally includes `schema_version` and the canonical
  `provenance` record, so provenance is tamper-evident.

`recompute_event_hash` dispatches on the event's **stored** `schema_version`, so
mixed version-1/version-2 stores verify intact. This invariant is pinned by a
**merge-blocking golden test** (`test_backward_compat_hashing.py`), including a
literal golden version-1 hash. No published record is rewritten, re-hashed,
migrated, or mutated.

## FEAT-04-3 — Digital Evidence Chain-of-Custody

A **separate append-only ledger** (`evidence_custody_events`) with its own hash
chain — it does not touch, migrate, or re-hash the `audit_events` table. Each
`CustodyEvent` carries: evidence identifier, custody event identifier, current
and prior custodian, custody action (`acquire`/`transfer`/`hold`/`release`),
server-assigned UTC transfer timestamp, transfer reason, source principal,
per-evidence custody sequence, global chain sequence, previous hash and event
hash, classification, and correlation id.

**Integrity** (hash-chain, no PKI): mutation (hash mismatch), deletion / broken
chain link, global-chain sequence not strictly increasing, per-evidence
custody-sequence gap, and schema-violating stored rows are all reported as an
explicit `IntegrityReport` (`intact=false` + detail) — **never a raised 500**
(mirrors the Sprint 6 P4 defensive verifier).

**Idempotency** is scoped to `(source_principal, custody_event_id)`;
`source_principal` is assigned from the authenticated caller, never producer
content. The producer-facing `SubmittedCustodyEvent` has **no** chain-sequence /
timestamp / hash / source-principal fields, so those cannot be forged.

**Concurrency**: `PostgresCustodyEventStore` serializes appends with a
dedicated transaction-level advisory lock (key `0x43555354` "CUST", distinct
from the audit chain's `0x41554449` "AUDI"), `UNIQUE(chain_sequence)` as
defense-in-depth, and a bounded retry — the same proven pattern as FEAT-04-1.

## Database (idempotent SQL, no Alembic — Decision B carried forward)

- **`002_audit_provenance.sql`**: `ADD COLUMN IF NOT EXISTS schema_version
  INTEGER NOT NULL DEFAULT 1` and `ADD COLUMN IF NOT EXISTS provenance JSONB` on
  `audit_events`, plus supporting indexes. Only additive; existing rows get
  `schema_version = 1`, `provenance = NULL`, and their stored hashes are
  untouched.
- **`003_evidence_custody.sql`**: `CREATE TABLE IF NOT EXISTS
  evidence_custody_events` with `PRIMARY KEY (source_principal,
  custody_event_id)`, `UNIQUE(chain_sequence)`, `UNIQUE(evidence_id,
  custody_sequence)`, a `custody_action` CHECK, indexes, `REVOKE ALL … FROM
  PUBLIC`, `GRANT INSERT, SELECT … TO emg_audit_app`, and `REVOKE UPDATE,
  DELETE, TRUNCATE`. No application UPDATE/DELETE/TRUNCATE path.

Both scripts are mounted (with 001) into the Postgres init directory and run in
filename order. Immutability remains an application/role guarantee; it is **not**
claimed against a PostgreSQL superuser — the hash chain *detects* out-of-band
mutation.

## Authorization (no new roles)

All custody endpoints are least-privilege and service-authenticated, restricted
to the **existing** `svc-audit` role (custody writes via `require_audit_custodian`,
reads/integrity via the Sprint 6 `svc-audit` reader). Audit-event ingest
(including provenance) is unchanged — any recognized service principal.
**Classification-aware reporting and human/UI access are FEAT-04-4** and are not
built here.

## Service surface (additive)

- `POST /audit/events` — now accepts optional `provenance` (version stamped
  server-side). Unchanged for existing callers.
- `POST /audit/custody/events`, `GET /audit/custody/events`,
  `GET /audit/custody/integrity` — new, `svc-audit`-only.
- The FEAT-04-1 ingest/query/integrity surface is unchanged.

## Technical debt (carried forward — not introduced or resolved in Sprint 7)

Per the approval, **no `emg-service-auth` package** and **no connection pooling**
were introduced (no proven Sprint-7 defect required them). Both remain
documented production-hardening items in `security-limitations.md`, to be
resolved with FEAT-04-4 or before production load:

- Duplicated service-token validator (`services/audit` vs. `services/identity`).
- PostgreSQL connection pooling / async-safe DB access.

## Explicit exclusions (this sprint)

- **FEAT-04-4** (Audit Query & Reporting Interface), classification-aware read
  controls, export/reporting, and any human/UI surface.
- PKI / asymmetric digital signatures for custody (hash chain is used; PKI would
  need a new ADR).
- Any new role, any new ADR, any Module 7–10 work, any EPIC-05 work, Sprint 8.
- Alembic / migration framework; message-queue ingestion; partitioning;
  retention; HA/DR.
