-- EMG™ Module 6 — Provenance Record Model (FEAT-04-2, Sprint 7)
--
-- Additive, idempotent migration of the append-only audit store to carry an
-- optional, versioned provenance record. Runs after 001_audit_events.sql (the
-- whole tools/seed-data/postgres directory is mounted into the Postgres
-- container's /docker-entrypoint-initdb.d and executed in filename order).
--
-- Decision B (carried forward from Sprint 6): plain idempotent SQL, no Alembic.
--
-- BACKWARD COMPATIBILITY (the critical property): this migration only ADDS
-- nullable/defaulted columns. It NEVER rewrites, re-hashes, mutates, or deletes
-- an existing row. Existing Sprint 6 records get schema_version = 1 and
-- provenance = NULL, so they reconstruct as version-1 events whose stored
-- event_hash still verifies byte-for-byte (the canonical hash for a version-1
-- event excludes the schema_version/provenance keys entirely — see
-- emg_audit_pipeline.hashing, version-aware canonicalization).

-- schema_version discriminates version-1 (no provenance, Sprint 6-compatible
-- hash) from version-2 (provenance included in the hash). DEFAULT 1 backfills
-- existing rows without touching their hashed content.
ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;

-- Optional provenance record (FEAT-04-2), stored as JSONB. NULL for every
-- version-1 event; populated only for version-2 events.
ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS provenance JSONB;

-- Indexes supporting provenance-aware and richer filtering. (The full human
-- reporting/query surface is FEAT-04-4, a later sprint; these indexes are the
-- additive, forward-compatible support for it and for provenance lookups.)
CREATE INDEX IF NOT EXISTS idx_audit_events_classification  ON audit_events (classification);
CREATE INDEX IF NOT EXISTS idx_audit_events_module          ON audit_events (module);
CREATE INDEX IF NOT EXISTS idx_audit_events_action          ON audit_events (action);
CREATE INDEX IF NOT EXISTS idx_audit_events_outcome         ON audit_events (outcome);
CREATE INDEX IF NOT EXISTS idx_audit_events_source_system   ON audit_events (source_system);
CREATE INDEX IF NOT EXISTS idx_audit_events_schema_version  ON audit_events (schema_version);

-- No new grants are required: the new columns inherit the table-level
-- INSERT/SELECT-only grants already held by emg_audit_app (001). Append-only
-- remains an application- and role-level guarantee; it does NOT protect against
-- a PostgreSQL superuser or direct storage access — the hash-chain integrity
-- verification is the compensating control that *detects* such out-of-band
-- mutation.
