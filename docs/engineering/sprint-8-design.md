# Sprint 8 Design — Audit Query & Reporting Interface (FEAT-04-4)

Reference: Engineering Backlog v1.0 §3 (FEAT-04-4 — "Audit Query & Reporting
Interface: Backend query surface for audit records"), §6 row 6 (EPIC-04
completion), US-04; ADR-015 (audit distinct from telemetry); ADR-016 (Module 6
ownership). Module 6 — Audit, Provenance & Digital Evidence.

## Scope

Sprint 8 implements **FEAT-04-4 only**, the last EPIC-04 feature. It is a
**backend** query + reporting surface over the existing audit and custody
stores. With it delivered, EPIC-04 (Audit Platform) is functionally complete
(FEAT-04-1 → FEAT-04-4).

Explicitly in scope:

- Richer, classification-aware **query filters** on the audit surface (actor,
  correlation id, module, action, outcome, source system, classification,
  provenance-presence, time range) and the custody surface (evidence id,
  custodian, classification, time range).
- **Stable cursor (keyset) pagination**: deterministic ordering, no duplicates,
  no skipped records.
- **Backend report export** in **JSON and CSV** (no HTML, no UI).
- Custody querying by evidence id / custodian / date, plus the existing
  **chain-integrity** endpoint (unchanged, reused).
- **Additive performance indexes** (`004`).

Explicitly **out** of scope (deliberate boundaries):

- **No clearance-based classification-aware read authorization.** Classification
  is a *filter* dimension; it does not restrict which classifications a principal
  may read. That enforcement needs a human reader role (none exists) and an
  authorization-model decision — a documented follow-up (see
  `security-limitations.md`).
- No new role, no new ADR, no new service, no UI, no policy-engine wiring into
  `services/audit`.
- No EPIC-05 / Module 7–10 work. No change to the frozen Architecture Baseline
  and no redesign of Module 6.

## Pre-condition correction (test-only, separate from FEAT-04-4)

An independent repository review at the start of Sprint 8 found the merged
mainline test suite **red**: two stale assertions in
`libs/python/emg-audit-client/tests/test_import.py` (`__version__` expected the
Sprint 6 value `0.1.0`; an `AuditEvent` constructed without the now-required
`source_principal`). These were corrected so the regression gate is genuinely
green. No production code changed for this fix; it is documented here and in
`SPRINT-8-STATUS.md` as distinct from FEAT-04-4.

## Approach

### 1. Query models (emg-audit-client, additive)

`AuditQuery` gains optional `module`, `action`, `outcome`, `source_system`,
`classification`, `has_provenance`, and an opaque `cursor`. `CustodyQuery` gains
`classification` and `cursor`. Every new field defaults to `None`, so the Sprint
6/7 query shapes are unchanged and existing callers behave identically. Both
models stay `frozen` + `extra="forbid"`.

### 2. Cursor pagination (emg-audit-pipeline)

`pagination.py` provides `encode_cursor` / `decode_cursor` — a **versioned,
opaque** base64url token over the store's server-assigned monotonic sequence
(`sequence_number` for audit, `chain_sequence` for custody). Keyset semantics:
the next page returns rows strictly after the cursor position, ordered
ascending. Because the sequence is unique and monotonic, this gives a stable
order with **no duplicates and no skips** even as new rows are appended between
pages. A malformed token is rejected as `CURSOR_INVALID` (HTTP 400) rather than
silently ignored (which would risk re-scanning and duplicates).

Both in-memory and PostgreSQL audit + custody stores apply the new filters and
the cursor in their `query` paths. The SQL path adds equality/`IS NULL` clauses
and a `sequence_number > :after` / `chain_sequence > :after` clause; ordering is
`ASC` with the existing unique-sequence index as the keyset index.

### 3. Reporting endpoints (services/audit, additive)

- `GET /audit/events/page` and `GET /audit/custody/events/page` — the same
  filters, cursor-paginated, returning `{items, next_cursor, count}`.
  `next_cursor` is present when a full page is returned and null at the end.
- `GET /audit/events/export` and `GET /audit/custody/export` —
  `format=json|csv`. JSON returns an array of view models; CSV emits a fixed,
  documented column order. Export walks the full filtered set via keyset
  pagination — **one store query per page, never per row (no N+1)** — bounded by
  `EXPORT_MAX_ROWS`.
- The Sprint 6 `GET /audit/events` and Sprint 7 `GET /audit/custody/events`
  retain their list response shape (backward compatible) and gain the new
  optional filters.
- The existing `GET /audit/custody/integrity` (chain integrity) is unchanged and
  reused; FEAT-04-4 does not reimplement integrity.

All read endpoints remain least-privilege and restricted to the existing
`svc-audit` reader (`AuditReaderDep`). No new role; ingestion is unchanged.

Report serialization lives in `services/audit/.../reporting.py`. There is no
redaction step there: records were validated and secret-redacted before storage
(emg-audit-pipeline), so a report reflects only safe stored fields; the module
has no access to raw tokens or secrets.

### 4. Database (idempotent SQL, no Alembic)

`004_audit_reporting_indexes.sql` is **index-only and additive**: composite
`(filter, sequence)` indexes for classification-/source-system-/module-filtered
cursor pagination on `audit_events`, and `(evidence_id, chain_sequence)` /
`(custodian, chain_sequence)` for custody export. Single-column filter indexes
already exist (001/002/003), so `004` adds only the new filter+order composites.
It creates indexes only — no column or row is added, altered, dropped,
rewritten, re-hashed, or deleted — so **no stored `event_hash` changes** and the
golden hash-compatibility gate stays green. It runs automatically after 001–003
via the existing `docker-entrypoint-initdb.d` directory mount.

## Backward compatibility

- Existing Sprint 6 (v1) and Sprint 7 (v2 + custody) records are read and
  verified unchanged; the version-aware canonical hashing is untouched.
- `004` invalidates no hash (index-only). The merge-blocking golden hash test
  still passes.
- The Sprint 6/7 query endpoints keep their list response shape; new fields are
  optional; new endpoints are additive.

## Authorization

Reuses the existing `svc-audit` role for every read/query/export/integrity
endpoint (`require_audit_reader`). No new role, no policy-engine enforcement in
`services/audit` this sprint. Classification-aware *filtering* is available;
classification-aware *enforcement* is the documented follow-up.

## Testing

See `testing-strategy.md` (Sprint 8 section): the cursor codec and keyset
pagination (no-dup/no-skip, mid-walk stability), the new filters, HTTP
query/page/export (JSON + CSV, 400/422 boundaries, least-privilege negatives,
backward-compat list shape), a not-N+1 report-walk performance test, and an
opt-in live-Postgres suite (SQL filters + cursor, `004` indexes present, rows/
hashes intact after `004`). The golden hash gate is unchanged and green.
