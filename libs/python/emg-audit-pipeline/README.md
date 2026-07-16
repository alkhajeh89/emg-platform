# emg-audit-pipeline

The audit pipeline core for Module 6 (Enterprise Audit, Provenance & Digital
Evidence Platform) — FEAT-04-1 (Audit Event Pipeline). Added Sprint 6.

Part of the EMG™ shared libraries workspace (Module 3, ADR-012), the concrete
implementation of the `emg-audit-client` contract — the same
contract/implementation split as `emg-auth-client` / `emg-policy-engine`.
`services/audit` is the thin live service over this package.

## What this is

- **Canonical hashing** (`hashing.py`): deterministic serialization + SHA-256;
  `event_hash = sha256(canonical(immutable_fields ‖ prev_hash))`.
- **Centralized hash chain + sequencing** (`stores.py`): every store assigns
  `sequence_number`, `timestamp`, `ingest_time`, `prev_hash`, and `event_hash`
  itself, single-writer per store — producers never build competing chains.
- **Append-only stores**: `InMemoryAuditEventStore` (tests/dev) and
  `PostgresAuditEventStore` (tier-1). Neither exposes update/delete. Postgres
  additionally relies on INSERT/SELECT-only role grants
  (`tools/seed-data/postgres/001_audit_events.sql`).
- **Integrity verification** (`integrity.py`): recomputes the chain and
  reports the first break — detects out-of-band mutation, reordering, or gaps.
- **Idempotency**: `append` is idempotent by `event_id`.
- **Pre-persistence validation** (`validation.py`): bounds metadata size,
  rejects sensitive-looking metadata keys, and redacts secret-shaped
  substrings / bearer tokens from `reason` and metadata values.

## What this is not

- Not a network service (that is `services/audit`).
- Not `emg-telemetry`. Observability logs and the durable audit store are
  distinct, per ADR-015 §Decision.
- **Not an absolute immutability claim.** "No mutation or deletion" is an
  application-code and database-role guarantee; a PostgreSQL superuser (or
  direct storage access) can still alter bytes. That residual risk is exactly
  what the hash-chain integrity verification exists to *detect*.
- Not FEAT-04-2/04-3/04-4 (Provenance Record Model, Chain-of-Custody, full
  Query & Reporting) — later Audit sprints.

## Postgres extra

The PostgreSQL store needs the `postgres` optional dependency
(`psycopg[binary]`). Unit tests use `InMemoryAuditEventStore` and need no
database.
