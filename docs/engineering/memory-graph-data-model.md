# Enterprise Memory Graph — Data Model (FEAT-05-6)

All models are immutable pydantic v2 (`frozen=True, extra="forbid"`). Collections
are normalized to sorted-unique tuples. Identifiers/labels are `SafeLabel`
(bounded, control/bidi-free); free text is `SafeText`.

## Node — `MemoryNode`

The immutable unit of enterprise memory. Every sprint-required field is present.

| Field | Type | Notes |
| --- | --- | --- |
| `node_id` | `SafeLabel` | UUID / content-addressed id |
| `node_type` | `SafeLabel` | entity type (canonical vocab: `MemoryNodeType`, extensible) |
| `label` | `SafeText` | display / canonical name |
| `created_at` / `updated_at` | `datetime` | `updated_at ≥ created_at` |
| `source` | `SafeLabel` | source principal / system |
| `confidence` | `float ∈ [0,1]` | confidence score (from `ConfidenceEngine`) |
| `classification` | `Classification` | reused from `emg-common-types` |
| `evidence` | `tuple[EvidenceRef, …]` | **≥ 1 required**; deduped/sorted |
| `aliases` | `tuple[SafeText, …]` | resolution aliases (sorted-unique) |
| `histories` | `tuple[TemporalHistory, …]` | per-attribute timelines (unique attr) |
| `ontology_entity_id` | `SafeLabel \| None` | link back to the ontology entity |
| `metadata` | `Metadata` | immutable key/value map |

Adapter: `MemoryNode.from_entity(entity, label=…, evidence=…)` builds a node from
an ontology `Entity`, reusing its id/type/classification/trust-score/provenance.

Canonical node types (`MemoryNodeType`): entity, person, department, project,
meeting, decision, risk, action, policy, document, evidence, observation,
version, requirement, discussion, approval, implementation. Node `type` is a
free-form string, so this list can grow without breaking compatibility.

## Edge — `MemoryEdge`

| Field | Type | Notes |
| --- | --- | --- |
| `edge_id` | `SafeLabel` | content-addressed |
| `edge_type` | `SafeLabel` | relationship type (canonical vocab: `EdgeType`) |
| `source_id` / `target_id` | `SafeLabel` | endpoints; self-loops rejected |
| `direction` | `EdgeDirection` | `DIRECTED` \| `UNDIRECTED` |
| `evidence` | `tuple[EvidenceRef, …]` | **≥ 1 required** |
| `confidence` | `float ∈ [0,1]` | from `ConfidenceEngine` |
| `validity` | `TemporalValidity` | **valid_from / valid_until** |
| `created_at` / `updated_at` | `datetime` | |
| `classification` | `Classification` | |
| `metadata` | `Metadata` | |

Adapter: `MemoryEdge.from_relationship(rel, evidence=…, confidence=…)` builds an
edge from an ontology `Relationship`, reusing its endpoints and effective window.

## Evidence — `EvidenceRef`

Immutable, content-addressed pointer to a real artifact. **No graph assertion may
exist without one.**

| Field | Type |
| --- | --- |
| `evidence_id` | `SafeLabel` (content-addressed) |
| `source` | `EvidenceSource` — email, meeting_minutes, pdf, word_document, sharepoint, teams, jira, manual_entry |
| `locator` | `SafeLabel` — stable, source-scoped pointer |
| `source_principal` | `SafeLabel` |
| `captured_at` | `datetime` |
| `description` | `SafeText \| None` |
| `event_id` / `correlation_id` | `SafeLabel \| None` — links the pipeline's audit trail |
| `metadata` | `Metadata` |

`EvidenceRef.from_provenance(provenance, …)` bridges an ontology
`ProvenanceReference` into evidence, preserving the audit/correlation trail.

## Temporal — `TemporalValidity`, `TemporalFact`, `TemporalHistory`

- `TemporalValidity(valid_from, valid_until?)` — half-open `[from, until)`;
  `until=None` means open (currently valid). `contains(moment)`, `overlaps(other)`.
- `TemporalFact(value, validity, evidence≥1, recorded_at, metadata)` — an
  evidence-backed value over one interval.
- `TemporalHistory(attribute, facts)` — an ordered, **non-overlapping** timeline;
  only the last interval may be open. `as_of(moment)` reconstructs the value that
  held then; `with_change(value, effective_from, evidence, recorded_at)` returns a
  **new** history that closes the open interval and appends the new value (facts
  are never overwritten).

## Graph — `MemoryGraph`

Immutable snapshot of `nodes` + `edges` with derived adjacency indices built once
(O(N+E)). Edges must reference existing nodes; ids are unique. Provides O(1)
lookups, O(deg) adjacency, `neighbors`, `nodes_of_type`, and `content_hash()` (a
deterministic digest of the whole graph — the basis of revision identity).

## Versioning — `GraphRevision`, `GraphHistory`, `GraphDiff`

- `GraphRevision(revision_id, revision_number, parent_id, created_at, content_hash, graph)`
  — one immutable, content-addressed revision.
- `GraphHistory(revisions)` — append-only chain (validated: numbers increase by 1,
  parent links match). `commit(graph, at)` (idempotent), `reconstruct(id)`,
  `diff(a, b)`.
- `GraphDiff` — added/removed/modified node & edge ids; `is_empty`.

## Resolution — `EntityMention`, `ResolutionConfig`, `ResolvedEntity`, `ResolutionResult`

See the developer guide and `memory-graph-api.md`. Deterministic, union-find
based; canonical ids are content-addressed so they are stable across runs.

## Confidence — `ConfidencePolicy`, `ConfidenceAssessment`

`ConfidenceAssessment(score, band, evidence_count, distinct_source_count,
conflict_count, explanation, trust)` — `band ∈ {high, medium, low, conflicted}`;
`trust` is the underlying `emg-trust-scoring` `TrustScoreResult`.
