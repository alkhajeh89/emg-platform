-- P-03: narrow Knowledge Graph runtime UPDATE access to repository columns.
-- Role changes remain conditional for deployments that manage roles outside
-- this database. V005 continues to own the complete baseline privilege model.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_migrator')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_app') THEN
        REVOKE UPDATE ON TABLE
            graph_head,
            outbox,
            projection_checkpoints,
            mutation_idempotency,
            mutation_dispatch
            FROM emg_knowledge_graph_app;

        GRANT UPDATE (
            head_revision_number,
            head_content_hash,
            updated_at
        ) ON TABLE graph_head TO emg_knowledge_graph_app;

        GRANT UPDATE (
            state,
            mutation_id,
            revision_number,
            content_hash,
            receipt_json,
            mutation_result_json,
            expires_at
        ) ON TABLE mutation_idempotency TO emg_knowledge_graph_app;

        GRANT UPDATE (
            claim_owner,
            claim_expires_at,
            attempt_count,
            source_system_id,
            source_timeline,
            source_commit_lsn,
            source_tx_index,
            delivered_at
        ) ON TABLE mutation_dispatch TO emg_knowledge_graph_app;
    END IF;
END
$$;
