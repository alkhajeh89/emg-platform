-- SRS-2: separate migration ownership from Knowledge Graph runtime access.
-- Role changes are conditional so portable migration tests and deployments
-- that manage roles outside this database can still apply the schema.

DO $$
DECLARE
    object_name text;
    function_name text;
    schema_name text := current_schema();
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_migrator')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_app') THEN
        FOREACH object_name IN ARRAY ARRAY[
            'schema_migrations', 'tenants', 'graph_revisions', 'graph_head',
            'outbox', 'evidence_ledger', 'projection_checkpoints',
            'mutation_idempotency', 'mutation_ledger',
            'mutation_ledger_resource', 'mutation_dispatch'
        ] LOOP
            IF to_regclass(schema_name || '.' || object_name) IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE %I.%I OWNER TO emg_knowledge_graph_migrator',
                    schema_name, object_name
                );
            END IF;
        END LOOP;

        FOREACH function_name IN ARRAY ARRAY[
            'reject_mutation_ledger_change',
            'validate_mutation_ledger_json',
            'validate_mutation_idempotency_ledger',
            'validate_mutation_resource_count'
        ] LOOP
            IF to_regprocedure(
                schema_name || '.' || function_name || '()'
            ) IS NOT NULL THEN
                EXECUTE format(
                    'ALTER FUNCTION %I.%I() OWNER TO emg_knowledge_graph_migrator',
                    schema_name, function_name
                );
            END IF;
        END LOOP;

        EXECUTE format(
            'REVOKE CREATE ON SCHEMA %I FROM emg_knowledge_graph_app',
            schema_name
        );
        EXECUTE format(
            'GRANT USAGE ON SCHEMA %I TO emg_knowledge_graph_app',
            schema_name
        );
        EXECUTE format(
            'REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM emg_knowledge_graph_app',
            schema_name
        );
        EXECUTE format(
            'REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM emg_knowledge_graph_app',
            schema_name
        );
        EXECUTE format(
            'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I FROM emg_knowledge_graph_app',
            schema_name
        );

        IF to_regclass(schema_name || '.tenants') IS NOT NULL THEN
            GRANT SELECT, INSERT ON tenants, graph_revisions, evidence_ledger,
                mutation_ledger, mutation_ledger_resource
                TO emg_knowledge_graph_app;
            GRANT SELECT, INSERT, UPDATE ON graph_head, outbox,
                projection_checkpoints, mutation_dispatch
                TO emg_knowledge_graph_app;
            -- Expired claim replacement deletes only the matching
            -- tenant/principal/idempotency-key row under a row lock.
            GRANT SELECT, INSERT, UPDATE, DELETE ON mutation_idempotency
                TO emg_knowledge_graph_app;
            GRANT SELECT ON schema_migrations TO emg_knowledge_graph_app;
        END IF;
        EXECUTE format(
            'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I '
            'TO emg_knowledge_graph_app',
            schema_name
        );
    END IF;
END
$$;
