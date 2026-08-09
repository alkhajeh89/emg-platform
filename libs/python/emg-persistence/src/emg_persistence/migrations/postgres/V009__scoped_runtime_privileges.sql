-- ADR-041: converge Knowledge Graph runtime privileges without crossing
-- migration-stream ownership boundaries. Historical V005 remains immutable;
-- this forward migration supersedes its schema-wide privilege operations.

DO $$
DECLARE
    function_name text;
    schema_name text := current_schema();
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_migrator')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_app') THEN
        EXECUTE format(
            'REVOKE CREATE ON SCHEMA %I FROM emg_knowledge_graph_app', schema_name
        );
        EXECUTE format(
            'GRANT USAGE ON SCHEMA %I TO emg_knowledge_graph_app', schema_name
        );

        REVOKE ALL ON TABLE
            schema_migrations, tenants, graph_revisions, graph_head, outbox,
            evidence_ledger, projection_checkpoints, mutation_idempotency,
            mutation_ledger, mutation_ledger_resource, mutation_dispatch
            FROM emg_knowledge_graph_app;

        FOREACH function_name IN ARRAY ARRAY[
            'reject_mutation_ledger_change',
            'validate_mutation_ledger_json',
            'validate_mutation_idempotency_ledger',
            'validate_mutation_resource_count',
            'reject_evidence_ledger_change'
        ] LOOP
            IF to_regprocedure(schema_name || '.' || function_name || '()') IS NOT NULL THEN
                EXECUTE format(
                    'REVOKE ALL ON FUNCTION %I.%I() FROM emg_knowledge_graph_app',
                    schema_name, function_name
                );
            END IF;
        END LOOP;

        GRANT SELECT, INSERT ON
            tenants, graph_revisions, evidence_ledger, mutation_ledger,
            mutation_ledger_resource
            TO emg_knowledge_graph_app;
        GRANT SELECT, INSERT ON
            graph_head, outbox, projection_checkpoints, mutation_dispatch
            TO emg_knowledge_graph_app;
        GRANT SELECT, INSERT, DELETE ON mutation_idempotency
            TO emg_knowledge_graph_app;
        GRANT SELECT ON schema_migrations TO emg_knowledge_graph_app;

        GRANT UPDATE (
            head_revision_number, head_content_hash, updated_at
        ) ON graph_head TO emg_knowledge_graph_app;
        GRANT UPDATE (
            state, mutation_id, revision_number, content_hash, receipt_json,
            mutation_result_json, expires_at
        ) ON mutation_idempotency TO emg_knowledge_graph_app;
        GRANT UPDATE (
            claim_owner, claim_expires_at, attempt_count, source_system_id,
            source_timeline, source_commit_lsn, source_tx_index, delivered_at
        ) ON mutation_dispatch TO emg_knowledge_graph_app;
    END IF;
END
$$;
