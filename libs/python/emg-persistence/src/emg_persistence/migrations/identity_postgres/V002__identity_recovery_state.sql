-- ADR-043 Amendment 1: recovery-freshness reconciliation record (A4).
-- Reconciliation record only, never a freshness authority (A4). The
-- external Approved Recovery Authority remains the sole source of the
-- current (generation, authority_revision) pair (A3).
CREATE TABLE IF NOT EXISTS emg_identity.identity_recovery_state (
    singleton_id SMALLINT PRIMARY KEY CHECK (singleton_id = 1),
    reconciled_generation UUID NOT NULL,
    reconciled_authority_revision TEXT NOT NULL,
    reconciled_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE emg_identity.identity_recovery_state
    OWNER TO emg_identity_migrator;

REVOKE ALL ON emg_identity.identity_recovery_state FROM PUBLIC;
REVOKE ALL ON emg_identity.identity_recovery_state FROM emg_identity_app;
GRANT SELECT ON emg_identity.identity_recovery_state TO emg_identity_app;
