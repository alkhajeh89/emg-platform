# emg-audit-client

The audit event contract for Module 6 (Enterprise Audit, Provenance & Digital
Evidence Platform) — FEAT-04-1 (Audit Event Pipeline). Added Sprint 6.

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

## What this is not

- Not an implementation — no store, no I/O, no hashing here.
- Not `emg-telemetry`. Observability logs and the durable audit store are
  distinct, per ADR-015 §Decision.
- Not FEAT-04-2 (Provenance Record Model), FEAT-04-3 (Chain-of-Custody), or
  FEAT-04-4 (full Query & Reporting) — all later Audit sprints.
