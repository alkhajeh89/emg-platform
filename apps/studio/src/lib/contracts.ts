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
  recorded_at: string;
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
