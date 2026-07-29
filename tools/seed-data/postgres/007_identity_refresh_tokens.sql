-- SRS-2: durable, hashed refresh-token rotation state.
CREATE TABLE IF NOT EXISTS identity_refresh_token_families (
    family_hash TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS identity_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    family_hash TEXT NOT NULL REFERENCES identity_refresh_token_families(family_hash),
    status TEXT NOT NULL CHECK (status IN ('active', 'rotated', 'revoked')),
    expires_at TIMESTAMPTZ NOT NULL,
    rotated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_identity_refresh_tokens_family
    ON identity_refresh_tokens (family_hash);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_identity_app') THEN
        CREATE ROLE emg_identity_app LOGIN PASSWORD 'emg_identity_local_dev_only_do_not_use_in_prod';
    END IF;
END
$$;

REVOKE ALL ON identity_refresh_token_families, identity_refresh_tokens FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
    ON identity_refresh_token_families, identity_refresh_tokens
    TO emg_identity_app;
REVOKE DELETE, TRUNCATE
    ON identity_refresh_token_families, identity_refresh_tokens
    FROM emg_identity_app;
