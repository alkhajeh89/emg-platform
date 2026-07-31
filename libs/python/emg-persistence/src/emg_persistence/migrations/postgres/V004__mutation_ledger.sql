-- ADR-030 Revision 3: immutable mutation ledger and atomic idempotency.
-- Forward-only. Existing V003 records remain legacy_succeeded and are never
-- treated as fingerprint-verified replay records during rolling deployment.

ALTER TABLE graph_revisions
    ADD CONSTRAINT uq_graph_revision_identity
    UNIQUE (tenant_id, revision_number, content_hash);

ALTER TABLE mutation_idempotency
    ALTER COLUMN revision_number DROP NOT NULL,
    ALTER COLUMN content_hash DROP NOT NULL,
    ALTER COLUMN receipt_json DROP NOT NULL,
    ADD COLUMN state text NOT NULL DEFAULT 'legacy_succeeded',
    ADD COLUMN command_fingerprint char(64),
    ADD COLUMN fingerprint_version smallint,
    ADD COLUMN command_schema_version smallint,
    ADD COLUMN mutation_id uuid,
    ADD COLUMN mutation_result_json jsonb;

ALTER TABLE mutation_idempotency
    ADD CONSTRAINT ck_mutation_idempotency_state
    CHECK (
        (
            state = 'legacy_succeeded'
            AND command_fingerprint IS NULL
            AND fingerprint_version IS NULL
            AND command_schema_version IS NULL
            AND mutation_id IS NULL
            AND mutation_result_json IS NULL
            AND revision_number IS NOT NULL
            AND content_hash IS NOT NULL
            AND receipt_json IS NOT NULL
            AND expires_at IS NOT NULL
        )
        OR (
            state = 'pending'
            AND command_fingerprint ~ '^[0-9a-f]{64}$'
            AND fingerprint_version IS NOT NULL
            AND command_schema_version IS NOT NULL
            AND mutation_id IS NULL
            AND mutation_result_json IS NULL
            AND revision_number IS NULL
            AND content_hash IS NULL
            AND receipt_json IS NULL
            AND expires_at IS NOT NULL
        )
        OR (
            state = 'succeeded'
            AND command_fingerprint ~ '^[0-9a-f]{64}$'
            AND fingerprint_version IS NOT NULL
            AND command_schema_version IS NOT NULL
            AND mutation_id IS NOT NULL
            AND mutation_result_json IS NOT NULL
            AND revision_number IS NOT NULL
            AND content_hash IS NOT NULL
            AND receipt_json IS NOT NULL
            AND expires_at IS NOT NULL
        )
    ) NOT VALID;

ALTER TABLE mutation_idempotency
    VALIDATE CONSTRAINT ck_mutation_idempotency_state;

CREATE TABLE mutation_ledger (
    mutation_id            uuid        PRIMARY KEY,
    tenant_id              text        NOT NULL,
    principal_id           text        NOT NULL,
    principal_kind         text        NOT NULL,
    idempotency_key        text        NOT NULL,
    command_fingerprint    char(64)    NOT NULL
        CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    fingerprint_version    smallint    NOT NULL CHECK (fingerprint_version > 0),
    command_schema_version smallint    NOT NULL CHECK (command_schema_version > 0),
    operation              text        NOT NULL,
    status                 text        NOT NULL CHECK (status IN ('succeeded', 'no_op')),
    graph_revision         integer     NOT NULL,
    graph_content_hash     text        NOT NULL,
    write_receipt          jsonb       NOT NULL,
    mutation_result        jsonb       NOT NULL,
    audit_intents          jsonb       NOT NULL,
    resource_count         integer     NOT NULL CHECK (resource_count > 0),
    requested_at           timestamptz NOT NULL,
    ledger_completed_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    graph_revision_at      timestamptz NOT NULL,
    replay_expires_at      timestamptz NOT NULL,
    CONSTRAINT uq_mutation_ledger_scope
        UNIQUE (tenant_id, principal_id, mutation_id),
    CONSTRAINT fk_mutation_ledger_graph_revision
        FOREIGN KEY (tenant_id, graph_revision, graph_content_hash)
        REFERENCES graph_revisions (tenant_id, revision_number, content_hash),
    CONSTRAINT ck_mutation_ledger_times
        CHECK (
            requested_at <= ledger_completed_at
            AND graph_revision_at <= ledger_completed_at
            AND ledger_completed_at < replay_expires_at
        )
);

CREATE TABLE mutation_ledger_resource (
    mutation_id    uuid        NOT NULL
        REFERENCES mutation_ledger (mutation_id),
    ordinal        integer     NOT NULL CHECK (ordinal >= 0),
    resource_type  text        NOT NULL,
    resource_id    text        NOT NULL,
    action         text        NOT NULL,
    classification text        NOT NULL,
    reason         text,
    PRIMARY KEY (mutation_id, ordinal)
);

CREATE INDEX ix_mutation_ledger_tenant_completed
    ON mutation_ledger (tenant_id, ledger_completed_at, mutation_id);

CREATE INDEX ix_mutation_ledger_graph_revision
    ON mutation_ledger (tenant_id, graph_revision);

CREATE INDEX ix_mutation_ledger_principal
    ON mutation_ledger (tenant_id, principal_id, ledger_completed_at);

-- Mutable operational work state. It is not mutation history and does not
-- determine commit order. A CDC consumer may attach the authoritative WAL
-- source position after decoding the committed transaction.
CREATE TABLE mutation_dispatch (
    mutation_id       uuid        NOT NULL
        REFERENCES mutation_ledger (mutation_id),
    tenant_id         text        NOT NULL,
    channel           text        NOT NULL CHECK (channel IN ('audit', 'event')),
    available_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    attempt_count     integer     NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    claim_owner       text,
    claim_expires_at  timestamptz,
    delivered_at      timestamptz,
    source_system_id  text,
    source_timeline   bigint,
    source_commit_lsn pg_lsn,
    source_tx_index   integer,
    PRIMARY KEY (channel, mutation_id),
    CONSTRAINT ck_mutation_dispatch_claim
        CHECK ((claim_owner IS NULL) = (claim_expires_at IS NULL)),
    CONSTRAINT ck_mutation_dispatch_source_position
        CHECK (
            (source_system_id IS NULL
             AND source_timeline IS NULL
             AND source_commit_lsn IS NULL
             AND source_tx_index IS NULL)
            OR
            (source_system_id IS NOT NULL
             AND source_timeline IS NOT NULL
             AND source_commit_lsn IS NOT NULL
             AND source_tx_index IS NOT NULL
             AND source_tx_index >= 0)
        )
);

CREATE INDEX ix_mutation_dispatch_work
    ON mutation_dispatch (channel, available_at, mutation_id)
    WHERE delivered_at IS NULL;

CREATE INDEX ix_mutation_dispatch_source_position
    ON mutation_dispatch (
        source_system_id,
        source_timeline,
        source_commit_lsn,
        source_tx_index
    )
    WHERE source_commit_lsn IS NOT NULL;

CREATE FUNCTION reject_mutation_ledger_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER mutation_ledger_append_only
    BEFORE UPDATE OR DELETE ON mutation_ledger
    FOR EACH ROW EXECUTE FUNCTION reject_mutation_ledger_change();

CREATE TRIGGER mutation_ledger_resource_append_only
    BEFORE UPDATE OR DELETE ON mutation_ledger_resource
    FOR EACH ROW EXECUTE FUNCTION reject_mutation_ledger_change();

-- Scalar columns are authoritative. Stored JSON is an immutable replay
-- representation and must mirror those scalars and the committed receipt.
CREATE FUNCTION validate_mutation_ledger_json() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.write_receipt->>'schema_version')::integer <> 1
       OR NEW.write_receipt->'receipt'->>'tenant' IS NULL
       OR NEW.write_receipt->'receipt'->'tenant'->>'value' <> NEW.tenant_id
       OR NEW.write_receipt->'receipt'->'principal'->>'principal_id' <> NEW.principal_id
       OR NEW.write_receipt->'receipt'->'principal'->>'kind' <> NEW.principal_kind
       OR (NEW.write_receipt->'receipt'->>'revision_number')::integer <> NEW.graph_revision
       OR NEW.write_receipt->'receipt'->>'content_hash' <> NEW.graph_content_hash
       OR (NEW.write_receipt->'receipt'->>'committed_at')::timestamptz
          <> NEW.graph_revision_at
       OR (
           (NEW.write_receipt->'receipt'->>'revision_created')::boolean
           <> (NEW.status = 'succeeded')
       )
       OR (NEW.mutation_result->>'schema_version')::integer <> 1
       OR NEW.mutation_result->'result'->>'tenant_id' <> NEW.tenant_id
       OR NEW.mutation_result->'result'->'principal'->>'principal_id' <> NEW.principal_id
       OR NEW.mutation_result->'result'->'principal'->>'kind' <> NEW.principal_kind
       OR (NEW.mutation_result->'result'->>'revision_number')::integer
          <> NEW.graph_revision
       OR NEW.mutation_result->'result'->>'content_hash' <> NEW.graph_content_hash
       OR jsonb_array_length(NEW.mutation_result->'result'->'audit_intents')
          <> NEW.resource_count
       OR (NEW.audit_intents->>'schema_version')::integer <> 1
       OR jsonb_array_length(NEW.audit_intents->'intents') <> NEW.resource_count
       OR NEW.audit_intents->'intents'
          <> NEW.mutation_result->'result'->'audit_intents'
    THEN
        RAISE EXCEPTION 'mutation ledger scalar/JSON integrity violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER mutation_ledger_json_integrity
    BEFORE INSERT ON mutation_ledger
    FOR EACH ROW EXECUTE FUNCTION validate_mutation_ledger_json();

CREATE FUNCTION validate_mutation_idempotency_ledger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state = 'succeeded' AND NOT EXISTS (
        SELECT 1
        FROM mutation_ledger ledger
        WHERE ledger.mutation_id = NEW.mutation_id
          AND ledger.tenant_id = NEW.tenant_id
          AND ledger.principal_id = NEW.principal_id
          AND ledger.operation = NEW.operation_type
          AND ledger.command_fingerprint = NEW.command_fingerprint
          AND ledger.fingerprint_version = NEW.fingerprint_version
          AND ledger.command_schema_version = NEW.command_schema_version
          AND ledger.graph_revision = NEW.revision_number
          AND ledger.graph_content_hash = NEW.content_hash
          AND ledger.write_receipt = NEW.receipt_json
          AND ledger.mutation_result = NEW.mutation_result_json
    )
    THEN
        RAISE EXCEPTION 'mutation idempotency/ledger integrity violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER mutation_idempotency_ledger_integrity
    BEFORE INSERT OR UPDATE ON mutation_idempotency
    FOR EACH ROW EXECUTE FUNCTION validate_mutation_idempotency_ledger();

CREATE FUNCTION validate_mutation_resource_count() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (
        SELECT count(*) FROM mutation_ledger_resource
        WHERE mutation_id = NEW.mutation_id
    ) <> NEW.resource_count
    THEN
        RAISE EXCEPTION 'mutation ledger resource_count mismatch';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(NEW.audit_intents->'intents')
             WITH ORDINALITY AS intent(value, ordinal)
        LEFT JOIN mutation_ledger_resource resource
          ON resource.mutation_id = NEW.mutation_id
         AND resource.ordinal = intent.ordinal - 1
        WHERE resource.mutation_id IS NULL
           OR resource.resource_type <> intent.value->>'resource_type'
           OR resource.resource_id <> intent.value->>'resource_id'
           OR resource.action <> intent.value->>'action'
           OR resource.classification <> intent.value->>'classification'
           OR resource.reason IS DISTINCT FROM intent.value->>'reason'
    )
    THEN
        RAISE EXCEPTION 'mutation ledger resource/audit integrity violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER mutation_ledger_resource_count
    AFTER INSERT ON mutation_ledger
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_mutation_resource_count();

ALTER TABLE mutation_idempotency
    ADD CONSTRAINT fk_mutation_idempotency_ledger
    FOREIGN KEY (tenant_id, principal_id, mutation_id)
    REFERENCES mutation_ledger (tenant_id, principal_id, mutation_id);
