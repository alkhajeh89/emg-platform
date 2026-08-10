export interface SessionResponse {
  authenticated: true;
}

export interface EntitySummary {
  node_id: string;
  node_type: string;
  label: string;
  confidence: number;
  classification: string;
  created_at: string;
  updated_at: string;
}

export interface EvidenceReference {
  evidence_id: string;
  source: string;
  locator: string;
  source_principal: string;
  captured_at: string;
  description?: string | null;
}

export interface TemporalFact {
  value: string;
  validity: { valid_from: string; valid_until?: string | null };
  evidence: EvidenceReference[];
  recorded_at: string;
  metadata: Record<string, string>;
}

export interface NeighborResponse {
  items: Array<{
    entity: EntitySummary;
    via_edge_id: string;
    edge_type: string;
    confidence: number;
    direction: string;
  }>;
  page_info: { limit: number; returned_count: number; next_cursor: string | null; has_more: boolean };
  revision_context: EntityResponse["revision_context"];
}

export interface EntityDetails {
  summary: EntitySummary;
  source: string;
  aliases: string[];
  evidence: EvidenceReference[];
  histories: Array<{ attribute: string; facts: TemporalFact[] }>;
  metadata: Record<string, string>;
}

export interface EntityResponse {
  item: EntityDetails;
  revision_context: {
    revision_number: number;
    committed_at: string;
    is_current_head: boolean;
  };
}

export type SearchMatchKind =
  | "ID_EXACT"
  | "LABEL_EXACT"
  | "ALIAS_EXACT"
  | "ID_PREFIX"
  | "LABEL_PREFIX"
  | "ALIAS_PREFIX";

export interface GovernedSearchRequest {
  q: string;
  limit?: number;
  cursor?: string;
}

export interface GovernedSearchResponse {
  items: Array<{
    entity: EntitySummary;
    match_kind: SearchMatchKind;
  }>;
  page_info: {
    limit: number;
    returned_count: number;
    next_cursor: string | null;
    has_more: boolean;
  };
  revision_context: EntityResponse["revision_context"];
}
