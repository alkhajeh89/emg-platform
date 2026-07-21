-- Sprint 6 projection idempotency checkpoint

CREATE TABLE IF NOT EXISTS projection_checkpoints (
    tenant_id text NOT NULL,
    revision_number integer NOT NULL,
    event_id uuid NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (
        tenant_id,
        revision_number
    )
);

CREATE INDEX IF NOT EXISTS ix_projection_checkpoint_event
ON projection_checkpoints(event_id);
