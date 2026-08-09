-- ADR-041: canonical production Audit Service schema migration.
-- This forward-only migration safely adopts the existing local seed schema
-- without rewriting, re-hashing, truncating, or deleting authoritative data.
-- It is applied as emg_audit_migrator through audit_schema_migrations.

CREATE TABLE IF NOT EXISTS audit_events (
    event_id          TEXT        NOT NULL,
    source_principal  TEXT        NOT NULL,
    sequence_number   BIGINT      NOT NULL UNIQUE,
    timestamp         TIMESTAMPTZ NOT NULL,
    ingest_time       TIMESTAMPTZ NOT NULL,
    prev_hash         TEXT        NOT NULL,
    event_hash        TEXT        NOT NULL,
    actor             TEXT        NOT NULL,
    actor_type        TEXT        NOT NULL CHECK (actor_type IN ('human', 'service')),
    module            TEXT        NOT NULL,
    action            TEXT        NOT NULL,
    outcome           TEXT        NOT NULL CHECK (outcome IN ('success', 'denied', 'error')),
    correlation_id    TEXT,
    resource_type     TEXT,
    resource_id       TEXT,
    classification    TEXT        NOT NULL DEFAULT 'INTERNAL',
    source_system     TEXT        NOT NULL,
    source_component  TEXT,
    reason            TEXT        NOT NULL DEFAULT '',
    metadata          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    schema_version    INTEGER     NOT NULL DEFAULT 1,
    provenance        JSONB,
    tenant_id         TEXT        NOT NULL DEFAULT 'legacy-unscoped',
    PRIMARY KEY (source_principal, event_id)
);

-- Adopt databases initialized by the local seed sequence. These additions are
-- metadata-only/defaulted and preserve every existing event hash.
ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS provenance JSONB;
ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS tenant_id TEXT DEFAULT 'legacy-unscoped';
UPDATE audit_events SET tenant_id = 'legacy-unscoped' WHERE tenant_id IS NULL;
ALTER TABLE audit_events ALTER COLUMN tenant_id SET NOT NULL;

CREATE TABLE IF NOT EXISTS evidence_custody_events (
    custody_event_id   TEXT        NOT NULL,
    source_principal   TEXT        NOT NULL,
    chain_sequence     BIGINT      NOT NULL UNIQUE,
    custody_sequence   BIGINT      NOT NULL,
    transfer_timestamp TIMESTAMPTZ NOT NULL,
    ingest_time        TIMESTAMPTZ NOT NULL,
    prev_hash          TEXT        NOT NULL,
    event_hash         TEXT        NOT NULL,
    evidence_id        TEXT        NOT NULL,
    custody_action     TEXT        NOT NULL
        CHECK (custody_action IN ('acquire', 'transfer', 'hold', 'release')),
    custodian          TEXT        NOT NULL,
    prior_custodian    TEXT,
    transfer_reason    TEXT        NOT NULL DEFAULT '',
    classification     TEXT        NOT NULL DEFAULT 'INTERNAL',
    correlation_id     TEXT,
    metadata           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (source_principal, custody_event_id),
    UNIQUE (evidence_id, custody_sequence)
);

CREATE INDEX IF NOT EXISTS idx_audit_events_actor
    ON audit_events (actor);
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp
    ON audit_events (timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_events_correlation_id
    ON audit_events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_classification
    ON audit_events (classification);
CREATE INDEX IF NOT EXISTS idx_audit_events_module
    ON audit_events (module);
CREATE INDEX IF NOT EXISTS idx_audit_events_action
    ON audit_events (action);
CREATE INDEX IF NOT EXISTS idx_audit_events_outcome
    ON audit_events (outcome);
CREATE INDEX IF NOT EXISTS idx_audit_events_source_system
    ON audit_events (source_system);
CREATE INDEX IF NOT EXISTS idx_audit_events_schema_version
    ON audit_events (schema_version);
CREATE INDEX IF NOT EXISTS idx_audit_events_classification_seq
    ON audit_events (classification, sequence_number);
CREATE INDEX IF NOT EXISTS idx_audit_events_source_system_seq
    ON audit_events (source_system, sequence_number);
CREATE INDEX IF NOT EXISTS idx_audit_events_module_seq
    ON audit_events (module, sequence_number);
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_sequence
    ON audit_events (tenant_id, sequence_number);

CREATE INDEX IF NOT EXISTS idx_custody_evidence_id
    ON evidence_custody_events (evidence_id);
CREATE INDEX IF NOT EXISTS idx_custody_custodian
    ON evidence_custody_events (custodian);
CREATE INDEX IF NOT EXISTS idx_custody_transfer_time
    ON evidence_custody_events (transfer_timestamp);
CREATE INDEX IF NOT EXISTS idx_custody_classification
    ON evidence_custody_events (classification);
CREATE INDEX IF NOT EXISTS idx_custody_evidence_chain_seq
    ON evidence_custody_events (evidence_id, chain_sequence);
CREATE INDEX IF NOT EXISTS idx_custody_custodian_chain_seq
    ON evidence_custody_events (custodian, chain_sequence);

-- Existing objects are adoptable only when the migration identity already
-- owns them (or an operator has completed an explicit ownership handoff).
-- PostgreSQL fails closed otherwise; this migration never escalates itself.
ALTER TABLE audit_events OWNER TO emg_audit_migrator;
ALTER TABLE evidence_custody_events OWNER TO emg_audit_migrator;

REVOKE ALL ON audit_events, evidence_custody_events FROM PUBLIC;
REVOKE ALL ON audit_events, evidence_custody_events FROM emg_audit_app;
REVOKE CREATE ON SCHEMA public FROM emg_audit_app;
GRANT USAGE ON SCHEMA public TO emg_audit_app;
GRANT INSERT, SELECT ON audit_events, evidence_custody_events TO emg_audit_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events, evidence_custody_events
    FROM emg_audit_app;
