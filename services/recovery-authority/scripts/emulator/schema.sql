-- ADR-043 emulator-tier conformance schema. Emulator-only, never applied to
-- a real Spanner instance. Mirrors the approved authority model: one
-- authority_head row per (environment, resource incarnation) that every
-- rotation attempt CAS-updates via its expected predecessor revision, plus
-- an append-only authority_transition_history for observability.

CREATE TABLE authority_head (
  environment_id                 STRING(64) NOT NULL,
  resource_incarnation_id        STRING(64) NOT NULL,
  authority_epoch                STRING(64) NOT NULL,
  revision_number                INT64 NOT NULL,
  operation_id                   STRING(64) NOT NULL,
  state_digest                   BYTES(32) NOT NULL,
  candidate_digest                BYTES(32) NOT NULL,
  predecessor_checkpoint_digest   BYTES(32) NOT NULL,
  commit_timestamp                TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY (environment_id, resource_incarnation_id);

CREATE TABLE authority_transition_history (
  environment_id                 STRING(64) NOT NULL,
  resource_incarnation_id        STRING(64) NOT NULL,
  revision_number                INT64 NOT NULL,
  operation_id                   STRING(64) NOT NULL,
  predecessor_revision            INT64 NOT NULL,
  authority_epoch                STRING(64) NOT NULL,
  state_digest                   BYTES(32) NOT NULL,
  candidate_digest                BYTES(32) NOT NULL,
  commit_timestamp                TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY (environment_id, resource_incarnation_id, revision_number);
