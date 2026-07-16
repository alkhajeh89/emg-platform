# emg-audit-pipeline

The audit pipeline core for Module 6 (Enterprise Audit, Provenance & Digital
Evidence Platform) — FEAT-04-1 (Audit Event Pipeline, Sprint 6); extended in
Sprint 7 with FEAT-04-2 (Provenance Record Model) and FEAT-04-3 (Digital
Evidence Chain-of-Custody).

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

### Sprint 7 — version-aware hashing + provenance (FEAT-04-2)

- **Version-aware canonicalization** (`hashing.py`): a schema-version-1 event
  hashes byte-for-byte as in Sprint 6 (no `schema_version`/`provenance` keys),
  so every existing record re-verifies unchanged; a schema-version-2 event adds
  the provenance record to the hashed payload. `recompute_event_hash` dispatches
  on the event's stored version, so mixed v1/v2 stores verify intact. This is
  guarded by a merge-blocking golden test.
- **Provenance persistence** (`stores.py`): stores derive the event
  `schema_version` from the presence of provenance and persist provenance
  (JSONB in Postgres, via `002_audit_provenance.sql`'s additive columns).
- **Provenance validation** (`validation.py`,
  `validate_and_sanitize_provenance`): bounds transformation/parent counts and
  free-text lengths, redacts secret-shaped free text.

### Sprint 7 — chain-of-custody (FEAT-04-3)

- **Custody hashing** (`custody_hashing.py`): a separate SHA-256 hash chain for
  custody events — no PKI / asymmetric signatures.
- **Append-only custody stores** (`custody_store.py`):
  `InMemoryCustodyEventStore` and `PostgresCustodyEventStore` over the separate
  `evidence_custody_events` table (`003_evidence_custody.sql`, INSERT/SELECT-only
  role). A global `chain_sequence` (single-writer, serialized by a dedicated
  advisory lock) plus a per-evidence `custody_sequence`; idempotent by
  `(source_principal, custody_event_id)`.
- **Custody integrity** (`verify_custody_chain`): detects mutation, deletion,
  global-chain sequence breaks, per-evidence sequence gaps, and schema-violating
  rows — always as an explicit failure result, never a raised exception.

## What this is not

- Not a network service (that is `services/audit`).
- Not `emg-telemetry`. Observability logs and the durable audit store are
  distinct, per ADR-015 §Decision.
- **Not an absolute immutability claim.** "No mutation or deletion" is an
  application-code and database-role guarantee; a PostgreSQL superuser (or
  direct storage access) can still alter bytes. That residual risk is exactly
  what the hash-chain integrity verification exists to *detect*.
- Not FEAT-04-4 (full Query & Reporting) — deferred to the immediate next
  sprint; EPIC-04 remains incomplete until it lands.

## Postgres extra

The PostgreSQL store needs the `postgres` optional dependency
(`psycopg[binary]`). Unit tests use `InMemoryAuditEventStore` and need no
database.
