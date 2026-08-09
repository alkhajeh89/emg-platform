-- P-02 EL-10: make PostgreSQL an active evidence-ledger integrity boundary.
-- Existing evidentiary history is never repaired or normalized. The migration
-- fails atomically with a bounded diagnostic when a pre-existing row violates
-- the accepted EL-3/EL-4 contract.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM evidence_ledger WHERE seq < 1) THEN
        RAISE EXCEPTION 'EL-10 migration refused: evidence_ledger contains seq < 1';
    END IF;
    IF EXISTS (SELECT 1 FROM evidence_ledger WHERE prev_hash IS NULL) THEN
        RAISE EXCEPTION 'EL-10 migration refused: evidence_ledger contains NULL prev_hash';
    END IF;
    IF EXISTS (
        SELECT 1 FROM evidence_ledger
        WHERE prev_hash !~ '^[0-9a-f]{64}$'
    ) THEN
        RAISE EXCEPTION 'EL-10 migration refused: evidence_ledger contains malformed prev_hash';
    END IF;
    IF EXISTS (
        SELECT 1 FROM evidence_ledger
        WHERE entry_hash !~ '^[0-9a-f]{64}$'
    ) THEN
        RAISE EXCEPTION 'EL-10 migration refused: evidence_ledger contains malformed entry_hash';
    END IF;
    IF EXISTS (
        SELECT 1 FROM evidence_ledger
        WHERE seq = 1 AND prev_hash <> repeat('0', 64)
    ) THEN
        RAISE EXCEPTION 'EL-10 migration refused: evidence_ledger genesis sentinel is invalid';
    END IF;
END
$$;

ALTER TABLE evidence_ledger
    ALTER COLUMN prev_hash SET NOT NULL,
    ADD CONSTRAINT ck_evidence_ledger_seq_positive CHECK (seq >= 1),
    ADD CONSTRAINT ck_evidence_ledger_prev_hash_format
        CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_evidence_ledger_entry_hash_format
        CHECK (entry_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_evidence_ledger_genesis_prev_hash
        CHECK (seq <> 1 OR prev_hash = repeat('0', 64));

CREATE FUNCTION reject_evidence_ledger_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

REVOKE ALL ON FUNCTION reject_evidence_ledger_change() FROM PUBLIC;

CREATE TRIGGER evidence_ledger_append_only
    BEFORE UPDATE OR DELETE ON evidence_ledger
    FOR EACH ROW EXECUTE FUNCTION reject_evidence_ledger_change();
