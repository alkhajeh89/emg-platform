# Enterprise Memory Graph — API Reference (FEAT-05-6)

Public surface exported from `emg_memory_graph` (`__all__`, 75 names). All models
are immutable pydantic v2.

## Core models

- `MemoryNode` — `from_entity(entity, *, label, evidence, …)`, `history_for(attr)`.
- `MemoryEdge` — `from_relationship(rel, *, evidence, confidence, …)`,
  `is_active_at(moment)`, `endpoints()`.
- `MemoryGraph(nodes=(), edges=())` — `node(id)`, `edge(id)`, `has_node/has_edge`,
  `node_count`, `edge_count`, `out_edges/in_edges/incident_edges(id)`,
  `neighbors(id)`, `nodes_of_type(t)`, `content_hash()`. `EMPTY_GRAPH`.
- `EvidenceRef` — `create(...)`, `from_provenance(provenance, ...)`.
- `TemporalValidity(valid_from, valid_until=None)` — `contains`, `overlaps`, `is_open`.
- `TemporalFact`, `TemporalHistory(attribute, facts=())` — `as_of`, `current`,
  `timeline`, `with_change(...)`.
- `Metadata` / `MetadataItem` — `from_mapping`, `as_dict`, `get`. `EMPTY_METADATA`.

## Enums

`MemoryNodeType`, `EdgeType`, `EvidenceSource`, `MatchType`, `EdgeDirection`,
`ConfidenceBand`.

## Resolution (Deliverable 3)

- `ResolutionConfig(strategies={EXACT,NORMALIZED,ALIAS}, aliases=())`.
- `EntityMention(mention_id, entity_type, label)`.
- `EntityResolver(config).resolve(mentions) -> ResolutionResult`.
- `ResolutionResult.canonical_id_for(mention_id)`, `.entities`, `.assignments`.
- `ResolvedEntity(canonical_id, entity_type, canonical_label, member_mention_ids, match_types)`.
- `Resolver` (Protocol), `normalize_label(str)`.

## Confidence (Deliverable 7)

- `ConfidenceEngine(policy=None).assess(evidence, *, as_of, conflict_count=0) -> ConfidenceAssessment`.
- `ConfidencePolicy(scoring_policy=DEFAULT_POLICY, high_band=0.75, medium_band=0.5)`.
- `ConfidenceAssessment(score, band, evidence_count, distinct_source_count, conflict_count, explanation, trust)`.

## Builder (Deliverable 2)

- `MemoryGraphBuilder(confidence_engine=None)`.
  - `build(*, nodes=(), edges=(), as_of) -> BuildResult`.
  - `extend(base, *, nodes=(), edges=(), as_of) -> BuildResult`.
  - `from_ontology(*, entities=(), relationships=(), evidence_source=MANUAL_ENTRY, labels=None, as_of, base=None) -> BuildResult`.
- `NodeInput`, `EdgeInput` (`relationship_id` optional; `.edge_id()` prefers that
  canonical assertion/version id and otherwise uses the deterministic
  type/endpoints fallback), `BuildResult(graph, nodes_created, edges_created,
  node_inputs_merged, edge_inputs_merged)`.

## Temporal traversal (Deliverable 4)

- `subgraph_as_of(graph, moment) -> MemoryGraph`.
- `active_edges_at(graph, moment)`, `neighbors_at(graph, id, moment)`,
  `node_exists_at(graph, id, moment)`, `attribute_at(graph, id, attr, moment)`.

## Decision lineage (Deliverable 5)

- `DecisionLineage(graph, *, edge_types=None, max_depth=…)`.
  - `forward(id) -> LineageTrace`, `backward(id) -> LineageTrace`,
    `between(a, b) -> tuple[LineagePath, …]`.
- `LineageTrace(origin, direction, nodes, edges)`, `LineageNode(node_id, node_type, depth)`,
  `LineageEdgeRef`, `LineagePath(node_ids)`.

## Query engine (Deliverable 8)

- `MemoryQueryEngine(graph, *, lineage_edge_types=None)`:
  `who_approved`, `why_decided`, `supporting_evidence`, `meetings_discussing`,
  `participants`, `affected_projects`, `risks_from_policy`, `historical_owners`,
  `changed_between(history, a, b)`, `shortest_path(a, b)`.
- `RelatedNode(node, via_edge_id, edge_type, confidence)`, `PathResult(node_ids, edge_ids, length)`.

## Versioning (Deliverable 9)

- `GraphHistory(revisions=())` — `commit(graph, *, at)`, `latest()`, `get(id)`,
  `at(n)`, `reconstruct(id)`, `diff(a, b)`. `EMPTY_HISTORY`.
- `GraphRevision(...)` — `diff_from(other)`.
- `diff_graphs(before, after) -> GraphDiff`; `GraphDiff(...).is_empty`.

## Semantic bridge (Deliverable 8/10)

- `to_semantic_graph(graph)`, `to_semantic_node(node)`, `to_semantic_relationship(edge)`.
- `MemoryGraphExecutor(graph).execute(SemanticQuery) -> SemanticResult` (selection,
  filter, ordering, pagination; traversals delegated to `MemoryQueryEngine`).

## Errors

`MemoryGraphError` (base) → `NodeNotFoundError`, `EdgeNotFoundError`,
`EvidenceRequiredError`, `MergeConflictError`, `TemporalConsistencyError`,
`ResolutionError`, `TraversalLimitError`, `RevisionError`. All derive from
`emg_errors.EMGError`.

## Helpers / limits

`SafeLabel`, `SafeText`, `ensure_safe_label`; `node_id_for`, `edge_id_for`,
`evidence_id_for`, `revision_id_for`; `MAX_EVIDENCE_REFS`, `MAX_METADATA_ENTRIES`,
`MAX_TRAVERSAL_DEPTH`, `MAX_LINEAGE_DEPTH`, `MAX_PATH_RESULTS`; `__version__`.
