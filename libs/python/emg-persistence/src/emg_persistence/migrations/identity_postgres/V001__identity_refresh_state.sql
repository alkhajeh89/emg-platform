-- ADR-043: authoritative durable Identity refresh-token state.
CREATE TABLE IF NOT EXISTS emg_identity.identity_refresh_token_families (
    family_hash TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS emg_identity.identity_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    family_hash TEXT NOT NULL
        REFERENCES emg_identity.identity_refresh_token_families(family_hash),
    status TEXT NOT NULL CHECK (status IN ('active', 'rotated', 'revoked')),
    expires_at TIMESTAMPTZ NOT NULL,
    rotated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_identity_refresh_tokens_family
    ON emg_identity.identity_refresh_tokens (family_hash);

ALTER TABLE emg_identity.identity_refresh_token_families
    OWNER TO emg_identity_migrator;
ALTER TABLE emg_identity.identity_refresh_tokens
    OWNER TO emg_identity_migrator;
ALTER TABLE emg_identity.identity_schema_migrations
    OWNER TO emg_identity_migrator;

REVOKE ALL ON SCHEMA emg_identity FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA emg_identity FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA emg_identity FROM emg_identity_app;
GRANT USAGE ON SCHEMA emg_identity TO emg_identity_app;
GRANT SELECT, INSERT ON
    emg_identity.identity_refresh_token_families,
    emg_identity.identity_refresh_tokens
    TO emg_identity_app;
GRANT UPDATE (revoked_at)
    ON emg_identity.identity_refresh_token_families
    TO emg_identity_app;
GRANT UPDATE (status, rotated_at)
    ON emg_identity.identity_refresh_tokens
    TO emg_identity_app;
REVOKE CREATE ON SCHEMA emg_identity FROM emg_identity_app;
REVOKE DELETE, TRUNCATE ON
    emg_identity.identity_refresh_token_families,
    emg_identity.identity_refresh_tokens
    FROM emg_identity_app;
REVOKE ALL ON emg_identity.identity_schema_migrations FROM emg_identity_app;
