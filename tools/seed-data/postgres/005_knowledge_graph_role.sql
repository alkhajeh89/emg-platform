-- EMG™ Knowledge Graph service — PostgreSQL role bootstrap
-- (Knowledge Graph Integration Closure, Group B3).
--
-- Creates the application role the Knowledge Graph service connects as
-- (services/knowledge-graph/src/emg_knowledge_graph_api/config.py's
-- `postgres_dsn` default, and docker-compose.yml's `knowledge-graph`
-- service). This script is mounted into the Postgres container's
-- /docker-entrypoint-initdb.d (docker-compose.yml) alongside the audit
-- scripts and is safe to re-run (IF NOT EXISTS / idempotent GRANTs).
--
-- Deliberate deviation from the audit role's least-privilege shape
-- (001_audit_events.sql): audit's schema (audit_events) is created by that
-- seed script itself, so its application role only ever needs narrow
-- INSERT/SELECT grants on tables that already exist by the time it
-- connects. The Knowledge Graph service is different: it owns no
-- pre-created schema here. Its tables (tenants, graph_revisions,
-- graph_head, outbox, evidence_ledger, projection_checkpoints,
-- schema_migrations) are created at container startup by
-- `emg_knowledge_graph_api.migrate` (Group B4), which applies
-- `emg-persistence`'s existing V001/V002 PostgreSQL migrations *as this
-- same role*. PostgreSQL 15+ does not grant `CREATE` on the `public`
-- schema to non-owner roles by default, so this role needs an explicit
-- `CREATE ON SCHEMA public` grant to run those migrations; it then owns
-- every table it creates and therefore already has full privileges on
-- them (no separate per-table GRANT is needed or issued here).
--
-- Architectural note (recorded, not resolved, here): this makes
-- `emg_knowledge_graph_app` a broader-privileged role than audit's
-- append-only role -- it can create and alter schema objects in `public`,
-- not just read/write specific rows. This is a direct consequence of this
-- service being the first (and, as of this sprint, only) consumer of
-- `emg-persistence`'s migration runner in this repository; no other
-- service currently owns or migrates these tables. See the Knowledge Graph
-- Integration Closure implementation specification and
-- `EMG_ARCHITECTURE_DECISION_REGISTER.md` for follow-up if a narrower,
-- migration-role-vs-app-role split is later deemed necessary.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_app') THEN
        CREATE ROLE emg_knowledge_graph_app LOGIN PASSWORD 'emg_knowledge_graph_local_dev_only_do_not_use_in_prod';
    END IF;
END
$$;

-- Local-dev-only password placeholder above, overridden per-environment from
-- the centralized secrets store (Engineering Master Plan §5) -- never a real
-- value. Matches the default `postgres_dsn` in
-- `emg_knowledge_graph_api/config.py` and docker-compose.yml's
-- `knowledge-graph` service so local development works out of the box.

-- Required so the migration runner (connecting as this role) can create the
-- baseline tables on first startup. Ownership of created objects then
-- carries the role's full privileges on them -- no further per-table GRANT
-- is required.
GRANT CREATE ON SCHEMA public TO emg_knowledge_graph_app;
