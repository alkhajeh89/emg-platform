-- SRS-2: server-assigned tenant provenance for audit confidentiality.
ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS tenant_id TEXT DEFAULT 'legacy-unscoped';
UPDATE audit_events SET tenant_id = 'legacy-unscoped' WHERE tenant_id IS NULL;
ALTER TABLE audit_events ALTER COLUMN tenant_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_sequence
    ON audit_events (tenant_id, sequence_number);

-- Legacy rows use a reserved marker that no verified tenant token may claim;
-- every runtime read is tenant-scoped, so these rows fail closed.

GRANT INSERT (tenant_id), SELECT (tenant_id) ON audit_events TO emg_audit_app;
