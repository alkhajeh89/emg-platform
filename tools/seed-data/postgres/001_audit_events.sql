-- EMG™ Module 6 — Audit Event Pipeline (FEAT-04-1, Sprint 6)
--
-- Idempotent initialization of the append-only audit store and a
-- least-privilege application role whose grants are INSERT + SELECT ONLY.
--
-- Decision B (Sprint 6): plain idempotent SQL, no Alembic. Schema-migration
-- tooling is a documented later production-hardening item
-- (docs/engineering/security-limitations.md). This script is mounted into the
-- Postgres container's /docker-entrypoint-initdb.d (docker-compose.yml) and is
-- safe to re-run (IF NOT EXISTS / idempotent GRANTs).
--
-- Append-only is enforced here at the database-role layer: the application
-- role can INSERT and SELECT but has no UPDATE or DELETE privilege. This is an
-- application/role guarantee, NOT an absolute claim that a superuser (or
-- direct storage access) can never alter bytes; the emg-audit-pipeline
-- hash-chain integrity verification is the compensating control that *detects*
-- any such out-of-band mutation.

CREATE TABLE IF NOT EXISTS audit_events (
    event_id          TEXT        NOT NULL,                -- producer-supplied idempotency key
    source_principal  TEXT        NOT NULL,                -- server-assigned authenticated producer identity
    sequence_number   BIGINT      NOT NULL UNIQUE,         -- server-assigned, monotonic, single global chain
    timestamp         TIMESTAMPTZ NOT NULL,                -- server-assigned UTC capture time
    ingest_time       TIMESTAMPTZ NOT NULL,                -- when the store accepted the event
    prev_hash         TEXT        NOT NULL,                -- hash-chain link to the previous event
    event_hash        TEXT        NOT NULL,                -- SHA-256 over canonical(event || prev_hash)
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
    -- Idempotency is scoped to (source_principal, event_id): one producer
    -- retrying its own event_id is a no-op, but two different producers using
    -- the same event_id create distinct events, so no producer can suppress
    -- another's audit record by reusing its event_id (Sprint 6 security-review
    -- fix, Priority 5).
    PRIMARY KEY (source_principal, event_id)
);

-- Query support for the minimal US-04 surface: by actor, by time range, by
-- correlation identifier. (The richer reporting interface is FEAT-04-4, a
-- later sprint.)
CREATE INDEX IF NOT EXISTS idx_audit_events_actor           ON audit_events (actor);
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp       ON audit_events (timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_events_correlation_id  ON audit_events (correlation_id);

-- Least-privilege application role for the audit service. Password is a
-- local-development-only placeholder, overridden per-environment from the
-- centralized secrets store (Engineering Master Plan §5) — never a real value.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_audit_app') THEN
        CREATE ROLE emg_audit_app LOGIN PASSWORD 'emg_audit_local_dev_only_do_not_use_in_prod';
    END IF;
END
$$;

-- Strip any default/public privileges first, then grant append-only access.
-- (New tables grant nothing to PUBLIC by default; this REVOKE is defensive and
-- idempotent — Sprint 6 security-review fix, Priority 6.)
REVOKE ALL ON audit_events FROM PUBLIC;

-- Append-only grants: INSERT + SELECT only. No UPDATE, no DELETE, no TRUNCATE.
GRANT INSERT, SELECT ON audit_events TO emg_audit_app;

-- Serialization of the monotonic sequence_number / hash chain is handled in
-- application code by a transaction-level advisory lock (single global chain),
-- with the UNIQUE(sequence_number) constraint as defense-in-depth; no sequence
-- object is granted. Explicitly ensure the app role cannot mutate history.
-- NOTE: this is an application- and role-level append-only guarantee; it does
-- NOT protect against a PostgreSQL superuser or direct storage access, which
-- the hash-chain integrity verification is designed to *detect*.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM emg_audit_app;
