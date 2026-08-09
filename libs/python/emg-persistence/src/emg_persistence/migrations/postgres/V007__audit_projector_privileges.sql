-- ADR-028: bind the dedicated Audit Projector to existing ledger/dispatch state.
-- No table, column, index, constraint, or business-persistence change occurs.

DO $$
DECLARE
    schema_name text := current_schema();
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_audit_projector') THEN
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO emg_audit_projector', schema_name);
        GRANT SELECT ON mutation_ledger, mutation_dispatch TO emg_audit_projector;
        GRANT UPDATE (
            available_at,
            attempt_count,
            claim_owner,
            claim_expires_at,
            delivered_at
        ) ON mutation_dispatch TO emg_audit_projector;
    END IF;
END
$$;
