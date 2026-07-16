-- EMG™ Module 6 — Digital Evidence Chain-of-Custody (FEAT-04-3, Sprint 7)
--
-- Idempotent creation of a SEPARATE append-only custody ledger. This is its
-- own table with its own hash chain; it does NOT touch, migrate, or re-hash the
-- audit_events table in any way. Runs after 001/002 (filename order).
--
-- Decision B (carried forward): plain idempotent SQL, no Alembic.
--
-- Append-only is enforced at the database-role layer exactly like the audit
-- store: the application role can INSERT and SELECT but has no UPDATE, DELETE,
-- or TRUNCATE privilege. This is an application- and role-level guarantee, NOT
-- an absolute claim that a superuser (or direct storage access) can never alter
-- bytes; the emg-audit-pipeline custody hash-chain integrity verification is the
-- compensating control that *detects* any such out-of-band mutation, deletion,
-- or sequence gap.

CREATE TABLE IF NOT EXISTS evidence_custody_events (
    custody_event_id   TEXT        NOT NULL,                -- producer-supplied idempotency key
    source_principal   TEXT        NOT NULL,                -- server-assigned authenticated producer identity
    chain_sequence     BIGINT      NOT NULL UNIQUE,         -- server-assigned, global monotonic single chain
    custody_sequence   BIGINT      NOT NULL,                -- server-assigned, per-evidence monotonic
    transfer_timestamp TIMESTAMPTZ NOT NULL,                -- server-assigned UTC transfer time
    ingest_time        TIMESTAMPTZ NOT NULL,                -- when the store accepted the event
    prev_hash          TEXT        NOT NULL,                -- hash-chain link to the previous custody event
    event_hash         TEXT        NOT NULL,                -- SHA-256 over canonical(event || prev_hash)
    evidence_id        TEXT        NOT NULL,
    custody_action     TEXT        NOT NULL CHECK (custody_action IN ('acquire', 'transfer', 'hold', 'release')),
    custodian          TEXT        NOT NULL,
    prior_custodian    TEXT,
    transfer_reason    TEXT        NOT NULL DEFAULT '',
    classification     TEXT        NOT NULL DEFAULT 'INTERNAL',
    correlation_id     TEXT,
    metadata           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- Idempotency is scoped to (source_principal, custody_event_id): one
    -- producer retrying its own custody_event_id is a no-op, but two different
    -- producers using the same custody_event_id create distinct events, so no
    -- producer can suppress another's custody record (P5 posture).
    PRIMARY KEY (source_principal, custody_event_id),
    -- Defense-in-depth for per-evidence gap integrity: an evidence item's
    -- custody_sequence values are unique, so no two transfers can claim the
    -- same position in that item's custody history.
    UNIQUE (evidence_id, custody_sequence)
);

-- Query support for the custody retrieval surface: by evidence item, by
-- custodian, by transfer time.
CREATE INDEX IF NOT EXISTS idx_custody_evidence_id     ON evidence_custody_events (evidence_id);
CREATE INDEX IF NOT EXISTS idx_custody_custodian       ON evidence_custody_events (custodian);
CREATE INDEX IF NOT EXISTS idx_custody_transfer_time   ON evidence_custody_events (transfer_timestamp);
CREATE INDEX IF NOT EXISTS idx_custody_classification  ON evidence_custody_events (classification);

-- Strip any default/public privileges first, then grant append-only access
-- (mirrors 001_audit_events.sql).
REVOKE ALL ON evidence_custody_events FROM PUBLIC;

-- Append-only grants: INSERT + SELECT only. No UPDATE, no DELETE, no TRUNCATE.
GRANT INSERT, SELECT ON evidence_custody_events TO emg_audit_app;

-- Serialization of the monotonic chain_sequence / hash chain is handled in
-- application code by a transaction-level advisory lock (distinct from the
-- audit chain's), with UNIQUE(chain_sequence) as defense-in-depth; no sequence
-- object is granted. Explicitly ensure the app role cannot mutate history.
REVOKE UPDATE, DELETE, TRUNCATE ON evidence_custody_events FROM emg_audit_app;
