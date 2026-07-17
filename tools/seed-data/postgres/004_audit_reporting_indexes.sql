-- EMG™ Module 6 — Audit Query & Reporting Interface (FEAT-04-4, Sprint 8)
--
-- Additive, idempotent indexes supporting the richer reporting query surface:
-- classification-aware filtering combined with keyset (cursor) pagination and
-- report export. Runs after 001/002/003 (the whole tools/seed-data/postgres
-- directory is mounted into the Postgres container's
-- /docker-entrypoint-initdb.d and executed in filename order).
--
-- Decision B (carried forward): plain idempotent SQL, no Alembic.
--
-- BACKWARD COMPATIBILITY: this migration creates indexes ONLY. It does NOT add,
-- alter, drop, rewrite, re-hash, or delete any column or row. Every existing
-- Sprint 6 (version-1) and Sprint 7 (version-2 + custody) record is untouched,
-- so no stored event_hash changes and the golden hash-compatibility tests still
-- pass. No new grants are required; the app role's INSERT/SELECT-only
-- privileges are unchanged.
--
-- NOTE on what already exists (so this script adds only what is genuinely new):
--   001 indexes audit_events (actor), (timestamp), (correlation_id) and makes
--       sequence_number UNIQUE (its own index — the audit keyset cursor column).
--   002 indexes audit_events (classification), (module), (action), (outcome),
--       (source_system), (schema_version).
--   003 indexes evidence_custody_events (evidence_id), (custodian),
--       (transfer_timestamp), (classification) and makes chain_sequence UNIQUE
--       (the custody keyset cursor column) plus UNIQUE(evidence_id,
--       custody_sequence).
-- The single-column filter indexes therefore already exist; what FEAT-04-4 adds
-- is COMPOSITE (filter + keyset-order) indexes so a filtered report can be both
-- filtered and returned in cursor order from one index, without a separate sort.

-- Audit: classification-filtered reports paginated / ordered by sequence_number.
CREATE INDEX IF NOT EXISTS idx_audit_events_classification_seq
    ON audit_events (classification, sequence_number);

-- Audit: source-system-filtered reports paginated / ordered by sequence_number.
CREATE INDEX IF NOT EXISTS idx_audit_events_source_system_seq
    ON audit_events (source_system, sequence_number);

-- Audit: module-filtered reports paginated / ordered by sequence_number.
CREATE INDEX IF NOT EXISTS idx_audit_events_module_seq
    ON audit_events (module, sequence_number);

-- Custody: an evidence item's custody chain in global-chain (cursor) order —
-- the common "export the chain of custody for this evidence item" report.
CREATE INDEX IF NOT EXISTS idx_custody_evidence_chain_seq
    ON evidence_custody_events (evidence_id, chain_sequence);

-- Custody: a custodian's transfers in global-chain (cursor) order.
CREATE INDEX IF NOT EXISTS idx_custody_custodian_chain_seq
    ON evidence_custody_events (custodian, chain_sequence);
