# emg-audit-client

The audit event contract for Module 6 (Enterprise Audit, Provenance & Digital
Evidence Platform) — FEAT-04-1 (Audit Event Pipeline, Sprint 6); extended in
Sprint 7 with FEAT-04-2 (Provenance Record Model) and FEAT-04-3 (Digital
Evidence Chain-of-Custody).

Part of the EMG™ shared libraries workspace (Module 3, ADR-012), the same
contract/implementation split as `emg-auth-client` (Module 5 contract) and
`emg-policy-engine` (its implementation). This package defines the *shape*
every service programs against; the concrete append-only stores, hashing,
sequencing, and integrity verification live in `emg-audit-pipeline`, and
`services/audit` is the thin live service over them.

## Contents

- `SubmittedAuditEvent` — the producer-supplied portion of an audit event
  (everything a service knows about a governed action before the central
  store assigns ordering/timing/hash-chain fields). `event_id` is the
  producer-supplied idempotency key.
- `AuditEvent` — the fully-persisted record (producer fields + server-assigned
  `sequence_number`, `timestamp`, `ingest_time`, `prev_hash`, `event_hash`).
  Immutable (`frozen=True`).
- `AuditSink` (Protocol) — what a producer service depends on to record a
  governed action.
- `AuditEventStore` (Protocol) — the append-only system-of-record; assigns the
  central sequence and hash chain. No `update`/`delete` method exists.
- `AuditQuery` — the minimal US-04 query surface (by actor, time range,
  correlation id). The richer reporting surface is FEAT-04-4, a later sprint.
- `IntegrityResult` (Protocol) — result of hash-chain verification.

### Sprint 7 — Provenance (FEAT-04-2)

- `ProvenanceRecord` — the origin/lineage of an audit event: source system,
  source component, originating actor, originating principal, correlation id,
  event time vs. ingestion time, classification, `transformation_history`
  (ordered `TransformationStep`s), `parent_event_refs` (ordered `EventRef`s),
  evidence origin, collection method, and a self-describing schema version.
- `ProvenanceRecord` is an **optional** field on `SubmittedAuditEvent`/
  `AuditEvent`; the store assigns the *event* `schema_version` (1 = no
  provenance, byte-for-byte Sprint 6-compatible hash; 2 = provenance included in
  the hash).
- `TransformationStep`, `EventRef` — the provenance sub-models.

### Sprint 7 — Chain-of-Custody (FEAT-04-3)

- `SubmittedCustodyEvent` / `CustodyEvent` — a digital-evidence custody transfer
  (evidence id, custody action, custodian/prior custodian, transfer reason) plus
  server-assigned `source_principal`, global `chain_sequence`, per-evidence
  `custody_sequence`, timing, and hash-chain fields.
- `CustodyEventStore` (Protocol) — the separate append-only custody ledger; no
  `update`/`delete` method.
- `CustodyQuery` — retrieval by evidence id / custodian / time range.

## What this is not

- Not an implementation — no store, no I/O, no hashing here.
- Not `emg-telemetry`. Observability logs and the durable audit store are
  distinct, per ADR-015 §Decision.
- Not FEAT-04-4 (full Query & Reporting) — deferred to the immediate next
  sprint; EPIC-04 remains incomplete until it lands.
