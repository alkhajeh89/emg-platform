# emg-memory-graph

**Enterprise Memory Graph Core Engine** — Knowledge Graph module (EPIC-05,
**FEAT-05-6**, added Sprint 15).

Transforms the structured knowledge objects produced by earlier sprints
(ingestion + lifecycle) into a **persistent, temporal, evidence-linked, versioned
graph** of entities, relationships, evidence, observations and decisions — the
"connected memory" that differentiates EMG from document stores, knowledge bases
and RAG pipelines.

It is **deterministic, immutable, and storage-independent**. It **composes** the
existing libraries rather than duplicating them:

- `emg-ontology` — entity/relationship vocabulary, provenance, classification.
- `emg-knowledge-pipeline` — the `GraphStore` / ontology objects it consumes.
- `emg-knowledge-lifecycle` — version chains / temporal lineage patterns.
- `emg-trust-scoring` — the confidence scoring engine (wrapped, not reimplemented).
- `emg-semantic-layer` — the generic graph query/traversal model (projected into).

**No** machine learning, networking, persistence engine, or UI.

## What it provides

| Capability | Entry point |
| --- | --- |
| Immutable graph model | `MemoryNode`, `MemoryEdge`, `MemoryGraph`, `EvidenceRef` |
| Deterministic construction | `MemoryGraphBuilder` |
| Deterministic entity resolution (exact / normalized / alias / rule) | `EntityResolver` |
| Temporal memory (never overwrite) | `TemporalHistory`, `as_of`, `TemporalMemory` |
| Decision lineage (bidirectional) | `DecisionLineage` |
| Evidence linking (mandatory, immutable) | `EvidenceRef` on every node/edge |
| Confidence scoring (multi-source ↑, conflict ↓) | `ConfidenceEngine` |
| Query engine (who/why/evidence/history/paths) | `MemoryQueryEngine` |
| Immutable graph versioning + diff | `GraphRevision`, `GraphHistory`, `diff_graphs` |
| Semantic-layer bridge | `to_semantic_graph`, `MemoryGraphExecutor` |

See `docs/engineering/memory-graph-architecture.md` and the other
`memory-graph-*.md` docs for the full design, data model, developer guide, API
reference and integration guide.

## Determinism & complexity

Graph construction is a pure function of its inputs (content-addressed ids, no
clocks, no counters). Major operations document their complexity in the module
docstrings; hot paths are O(N + E) or better, and no operation is O(n²) over the
whole graph.
