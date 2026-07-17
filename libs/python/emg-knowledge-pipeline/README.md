# emg-knowledge-pipeline

The **Knowledge Ingestion Pipeline** for Module 7 (Enterprise Knowledge Graph
Platform) — EPIC-05, **FEAT-05-2**, added Sprint 10.

Part of the EMG™ shared-libraries workspace (Module 3, ADR-012), delivered
**library-first** and **storage-independent**: it converts validated
`emg-ontology` models into persistent graph operations through a `GraphStore`
abstraction. It reuses the completed EPIC-04 Audit Platform (`emg-audit-client`)
to emit graph-mutation audit contracts. It has **no Neo4j binding, no retrieval,
no search, no embeddings, no AI, and no UI** — those are FEAT-05-4 / EPIC-06+.

## What this is

- **Ingestion requests** (`requests.py`): `EntityIngestionRequest`,
  `RelationshipIngestionRequest`, `IngestionBatch` — frozen, `extra="forbid"`,
  length-bounded, and **without any server-assigned field** (a producer cannot
  supply `entity_id`, `owner`, `provenance_reference`, or `trust_score`).
- **Ingestion context** (`context.py`): the server-side authority —
  authenticated `source_principal`, `source_type` (system/document/api/ai/human),
  `owner`, correlation id, ingest time, and the interim trust policy.
- **Deterministic idempotency** (`idempotency.py`): entity/relationship ids are
  deterministic digests of their identity inputs, so re-ingesting the same
  payload never creates a duplicate.
- **Resolvers** (`resolver.py`): natural-key → canonical id, relationship
  endpoint resolution, and in-batch duplicate detection.
- **Validator** (`validation.py`): bounds, ontology conformance, uniqueness,
  relationship validity (endpoint types, classification dominance, cardinality),
  dangling endpoints, and cyclic-dependency rejection. **No persistence occurs
  before validation succeeds.**
- **Graph store + transactions** (`graph_store.py`): a storage-independent
  `GraphStore` / `GraphTransaction` Protocol and an append-only
  `InMemoryGraphStore` (no update/delete). Commits are atomic — a failure rolls
  back with **no partial graph**.
- **Pipeline** (`pipeline.py`) + **result** (`result.py`) + **errors**
  (`errors.py`): validate → order → persist (one transaction) → emit audit →
  typed `IngestionResult`.
- **Audit integration** (`audit.py`): each mutation emits a `SubmittedAuditEvent`
  (`entity.created` / `relationship.created` / `entity.superseded` /
  `relationship.superseded`, module `knowledge-graph`); the persisted record's
  `provenance_reference` points at that audit event (single system of record —
  no audit content copied); correlation ids are preserved.

## What this is not

- **Not a graph database.** Neo4j Enterprise remains the approved future store
  (Master Plan Technology Choice #4); the Neo4j adapter + Semantic Layer are
  FEAT-05-4. This library ships only an in-memory adapter and introduces **no
  new database**.
- **Not a trust-scoring engine** (`trust_score` is server-assigned as an interim
  source-type default; scoring is FEAT-05-3).
- **Not lifecycle management** — `supersede_entity`/`supersede_relationship` are
  minimal primitives that emit the `*.superseded` contracts; the managed
  proposed→active→retired workflow and current-version resolution are FEAT-05-5.
- **Not retrieval/search/AI/UI**, and **not a live service** —
  `services/knowledge-graph` remains scaffolded.

## Usage

```python
from datetime import datetime, timezone
from emg_knowledge_pipeline import (
    KnowledgePipeline, InMemoryGraphStore, IngestionContext,
    IngestionBatch, EntityIngestionRequest, RelationshipIngestionRequest,
)

store = InMemoryGraphStore()
pipeline = KnowledgePipeline(store)
ctx = IngestionContext(source_principal="emg-svc-ingest", source_type="system", owner="bu-1")

batch = IngestionBatch(
    entities=(
        EntityIngestionRequest(entity_type="Person", natural_key="alice",
                               effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        EntityIngestionRequest(entity_type="Role", natural_key="investigator",
                               effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ),
    relationships=(
        RelationshipIngestionRequest(
            relationship_type="HOLDS",
            from_entity_type="Person", from_natural_key="alice",
            to_entity_type="Role", to_natural_key="investigator",
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ),
)

result = pipeline.ingest(batch, ctx)          # validate → persist → emit audit
assert result.created_count == 3
second = pipeline.ingest(batch, ctx)          # idempotent: nothing new created
assert second.created_count == 0 and second.skipped_count == 3
```
