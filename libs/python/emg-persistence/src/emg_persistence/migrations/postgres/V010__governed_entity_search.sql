-- ADR-042 governed entity search: PostgreSQL-authoritative, revision-bound.
CREATE TABLE entity_search_representations (
    tenant_id text NOT NULL,
    revision_number integer NOT NULL,
    content_hash char(64) NOT NULL,
    node_count integer NOT NULL CHECK (node_count >= 0),
    normalizer_version integer NOT NULL,
    representation_expires_at timestamptz,
    PRIMARY KEY (tenant_id, revision_number),
    FOREIGN KEY (tenant_id, revision_number)
      REFERENCES graph_revisions (tenant_id, revision_number) ON DELETE CASCADE
);

CREATE TABLE entity_search_documents (
    tenant_id text NOT NULL,
    revision_number integer NOT NULL,
    node_id text COLLATE "C" NOT NULL,
    node_type text NOT NULL,
    label text NOT NULL,
    confidence double precision NOT NULL,
    classification text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    normalizer_version integer NOT NULL,
    PRIMARY KEY (tenant_id, revision_number, node_id),
    FOREIGN KEY (tenant_id, revision_number)
      REFERENCES entity_search_representations (tenant_id, revision_number) ON DELETE CASCADE
);

CREATE TABLE entity_search_terms (
    tenant_id text NOT NULL,
    revision_number integer NOT NULL,
    node_id text COLLATE "C" NOT NULL,
    field_kind text NOT NULL CHECK (field_kind IN ('id', 'label', 'alias')),
    normalized_term text COLLATE "C" NOT NULL,
    PRIMARY KEY (tenant_id, revision_number, node_id, field_kind, normalized_term),
    FOREIGN KEY (tenant_id, revision_number, node_id)
      REFERENCES entity_search_documents (tenant_id, revision_number, node_id) ON DELETE CASCADE
);

CREATE INDEX ix_entity_search_terms_prefix
  ON entity_search_terms (tenant_id, revision_number, normalized_term text_pattern_ops, field_kind, node_id);
CREATE INDEX ix_entity_search_representations_retention
  ON entity_search_representations (representation_expires_at)
  WHERE representation_expires_at IS NOT NULL;
CREATE INDEX ix_entity_search_representations_unscheduled
  ON entity_search_representations (tenant_id, revision_number)
  WHERE representation_expires_at IS NULL;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emg_knowledge_graph_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON entity_search_representations
      TO emg_knowledge_graph_app;
    GRANT SELECT, INSERT ON entity_search_documents, entity_search_terms
      TO emg_knowledge_graph_app;
  END IF;
END $$;
