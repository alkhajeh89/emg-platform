-- ADR-043 local-development credential bootstrap only.
-- The sole structural authority is the packaged identity_postgres migration stream.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_identity_migrator') THEN
        CREATE ROLE emg_identity_migrator LOGIN
            PASSWORD 'emg_identity_migrator_local_dev_only_do_not_use_in_prod'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_identity_app') THEN
        CREATE ROLE emg_identity_app LOGIN
            PASSWORD 'emg_identity_local_dev_only_do_not_use_in_prod'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS emg_identity AUTHORIZATION emg_identity_migrator;
REVOKE ALL ON SCHEMA emg_identity FROM PUBLIC;
