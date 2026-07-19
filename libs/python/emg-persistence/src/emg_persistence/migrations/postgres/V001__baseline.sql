-- EMG Persistence — PostgreSQL baseline schema (Phase 2, V001).
-- Authoritative revision log + head + outbox + tenants + evidence ledger,
-- per PHASE2_ARCHITECTURE.md Revision 3 §11. Declarative structure only — no
-- application logic. The schema_migrations history table is created by the
-- migration runner itself (not by a versioned migration).
--
-- IF NOT EXISTS is used defensively; the framework already applies each
-- migration exactly once.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   text        PRIMARY KEY,
    status      text        NOT NULL DEFAULT 'active',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS graph_revisions (
    tenant_id       text        NOT NULL,
    revision_number integer     NOT NULL,
    content_hash    text        NOT NULL,
    parent_hash     text,
    principal_id    text        NOT NULL,
    principal_kind  text        NOT NULL,
    node_count      integer     NOT NULL,
    edge_count      integer     NOT NULL,
    graph_json      jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, revision_number)
);

-- content_hash is GRAPH identity and is intentionally NON-UNIQUE: a rollback
-- legitimately creates a new revision that reproduces a prior content_hash
-- (ADR-3). This must remain a plain index, never a UNIQUE constraint.
CREATE INDEX IF NOT EXISTS ix_graph_revisions_tenant_content_hash
    ON graph_revisions (tenant_id, content_hash);

CREATE TABLE IF NOT EXISTS graph_head (
    tenant_id            text        PRIMARY KEY,
    head_revision_number integer     NOT NULL,
    head_content_hash    text        NOT NULL,
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outbox (
    event_id        uuid        PRIMARY KEY,
    tenant_id       text        NOT NULL,
    revision_number integer     NOT NULL,
    content_hash    text        NOT NULL,
    event_type      text        NOT NULL,
    schema_version  integer     NOT NULL,
    idempotency_key text        NOT NULL UNIQUE,
    payload         jsonb       NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    published_at    timestamptz
);

-- Independent evidence-ledger capability (ADR-4): defined here, NOT written by
-- the GraphStore write path. Append-only, hash-chained.
CREATE TABLE IF NOT EXISTS evidence_ledger (
    tenant_id        text        NOT NULL,
    seq              bigint      NOT NULL,
    evidence_id      text        NOT NULL,
    prev_hash        text,
    entry_hash       text        NOT NULL,
    source           text        NOT NULL,
    locator          text        NOT NULL,
    source_principal text        NOT NULL,
    captured_at      timestamptz NOT NULL,
    payload          jsonb       NOT NULL,
    PRIMARY KEY (tenant_id, seq)
);

CREATE INDEX IF NOT EXISTS ix_evidence_ledger_tenant_evidence
    ON evidence_ledger (tenant_id, evidence_id);
