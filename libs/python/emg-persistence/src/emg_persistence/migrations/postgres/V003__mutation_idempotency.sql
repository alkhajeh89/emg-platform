-- ADR-027 (Revision 2) Stage 0.3: mutation idempotency storage (§8.2).
--
-- Additive, schema-only migration. No application wiring: no command,
-- route, or repository reads/writes this table yet (ADR-027 Stage 0 forbids
-- application/command/route work; this table is a prerequisite for Stage 2+
-- only). Declarative structure only, following this file's own established
-- convention (composite tenant-scoped primary key, no surrogate id — the
-- same shape as graph_revisions/graph_head/projection_checkpoints).
--
-- A row is written if, and only if, the mutation's GraphStore.transaction()
-- commits successfully (§8.6) — never for a failed/denied attempt. Scoped by
-- (tenant_id, principal_id, idempotency_key), deliberately including
-- principal_id (not tenant_id alone), so a cross-principal key collision can
-- never replay another principal's receipt (§8.8).

CREATE TABLE IF NOT EXISTS mutation_idempotency (
    tenant_id       text        NOT NULL,
    principal_id    text        NOT NULL,
    idempotency_key text        NOT NULL,
    operation_type  text        NOT NULL,
    revision_number integer     NOT NULL,
    content_hash    text        NOT NULL,
    receipt_json    jsonb       NOT NULL,
    requested_at    timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, principal_id, idempotency_key)
);

-- Supports the TTL reclamation path (§8.3): a lazy "WHERE expires_at < now()"
-- deletion or a periodic reaper, either way keyed off this index rather than
-- a full-table scan.
CREATE INDEX IF NOT EXISTS ix_mutation_idempotency_expires_at
    ON mutation_idempotency (expires_at);
