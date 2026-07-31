-- EMG™ Knowledge Graph service — PostgreSQL role bootstrap
-- (Knowledge Graph Integration Closure, Group B3).
--
-- Creates separate migration-owner and runtime application roles.
-- (services/knowledge-graph/src/emg_knowledge_graph_api/config.py's
-- `postgres_dsn` default, and docker-compose.yml's `knowledge-graph`
-- service). This script is mounted into the Postgres container's
-- /docker-entrypoint-initdb.d (docker-compose.yml) alongside the audit
-- scripts and is safe to re-run (IF NOT EXISTS / idempotent GRANTs).
--
-- The one-shot migration process uses the migrator credential and owns all
-- schema objects. The serving process receives only the application
-- credential. V005 grants its exact DML privileges after transferring any
-- legacy runtime-owned objects to the migrator.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_migrator') THEN
        CREATE ROLE emg_knowledge_graph_migrator LOGIN PASSWORD 'emg_knowledge_graph_migrator_local_dev_only_do_not_use_in_prod';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_app') THEN
        CREATE ROLE emg_knowledge_graph_app LOGIN PASSWORD 'emg_knowledge_graph_local_dev_only_do_not_use_in_prod';
    END IF;
END
$$;

-- The migrator may assume the runtime role only to transfer ownership away
-- from legacy runtime-owned objects during V005. The reverse grant does not
-- exist, so the runtime credential can never assume the owner role.
GRANT emg_knowledge_graph_app TO emg_knowledge_graph_migrator;

-- Local-dev-only password placeholders above, overridden per-environment from
-- the centralized secrets store (Engineering Master Plan §5) -- never a real
-- value. Matches the default `postgres_dsn` in
-- `emg_knowledge_graph_api/config.py` and docker-compose.yml's
-- `knowledge-graph` service so local development works out of the box.

-- Required so the separate migration job can create and own schema objects.
REVOKE CREATE ON SCHEMA public FROM emg_knowledge_graph_app;
GRANT USAGE ON SCHEMA public TO emg_knowledge_graph_app;
GRANT CREATE, USAGE ON SCHEMA public TO emg_knowledge_graph_migrator;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO emg_knowledge_graph_migrator;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO emg_knowledge_graph_migrator;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO emg_knowledge_graph_migrator;

ALTER DEFAULT PRIVILEGES FOR ROLE emg_knowledge_graph_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO emg_knowledge_graph_app;
ALTER DEFAULT PRIVILEGES FOR ROLE emg_knowledge_graph_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO emg_knowledge_graph_app;
