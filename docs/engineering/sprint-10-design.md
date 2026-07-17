# Sprint 10 Design — Knowledge Ingestion Pipeline (FEAT-05-2)

Reference: Engineering Backlog v1.0 §3 (FEAT-05-2 — "Knowledge Ingestion
Pipeline: System, document, API, AI, and human ingestion sources"), §6 row 8
(exit criterion: "Ingestion from at least one source type validated
end-to-end"), §9 (13 story points); Master Plan §17 (dependency order),
Technology Choice #4 (Neo4j Enterprise via the storage-independent Semantic
Layer, Module 7 §10); Architecture Baseline (Module 7 = sole system of record
for organizational memory; grounded/cited by construction; storage-technology
independence). Builds directly on FEAT-05-1 (`emg-ontology`) and the completed
EPIC-04 Audit Platform (`emg-audit-client`).

## Scope

Sprint 10 implements **FEAT-05-2 only**, delivered **library-first** as
`libs/python/emg-knowledge-pipeline`: the **storage-independent** pipeline that
converts validated `emg-ontology` models into persistent graph operations.

In scope: ingestion request models, ingestion context, ingestion validator,
entity/relationship resolvers, deterministic idempotent id generation, duplicate
detection, batch ingestion + dependency ordering, a `GraphStore`/transaction
abstraction with an in-memory adapter, an ingestion result model, typed
ingestion errors, and Module-6 audit-contract emission.

Out of scope (deferred): the **Neo4j binding** and the Semantic Layer
(FEAT-05-4), trust-score *calculation* (FEAT-05-3), lifecycle-state *management*
(FEAT-05-5), and all of retrieval, semantic search, embeddings, AI, and UI
(EPIC-06+ / Modules 8–10). `services/knowledge-graph` remains scaffolded; no new
database is introduced.

## Architecture

**Preserve library-first + storage independence.** Business logic depends only
on the `GraphStore` / `GraphTransaction` Protocols (`graph_store.py`), never on a
concrete engine. Sprint 10 ships one adapter — the append-only
`InMemoryGraphStore` — which is enough to validate "ingestion from a source type
end-to-end." A Neo4j adapter can be added later (FEAT-05-4) by implementing the
same Protocols, with **no change to ingestion logic** and no second database.
The Master Plan keeps Neo4j behind the Semantic Layer (Module 7 §10), which is a
separate later feature, so binding it now would be premature; the minimum
adapter that satisfies the feature is the in-memory one.

### Text architecture diagram

```
producer (system/document/api/ai/human)
   │  IngestionBatch (EntityIngestionRequest[], RelationshipIngestionRequest[])
   │  + IngestionContext (source_principal, source_type, owner, correlation_id)   ← server-side authority
   ▼
KnowledgePipeline.ingest()
   │
   ├─(1) validate_and_build ──────────────────────────────────────────────┐
   │      • bounds (batch/field/attr sizes)  → oversized-payload DoS guard │  NO PERSISTENCE
   │      • reject mass-assignment (extra fields / reserved attributes)    │  BEFORE VALIDATION
   │      • server-assign owner / trust_score / provenance_reference / id  │  SUCCEEDS
   │      • ontology conformance (emg-ontology), relationship validity,    │
   │        classification dominance, cardinality (intra-batch)            │
   │      • duplicate (in-batch) + dangling endpoint + cyclic DERIVED_FROM │
   │      → ValidatedBatch(new_entities, new_relationships, skipped)  OR   │
   │        raise IngestionValidationError(problems)  ─────────────────────┘
   │
   ├─(2) GraphTransaction (atomic; entities before relationships)
   │        store.begin() → add_entity* → add_relationship* → commit()
   │        on failure → rollback  → NO PARTIAL GRAPH → GraphPersistenceError
   │        InMemoryGraphStore: append-only, lock-serialized, idempotent
   │
   ├─(3) emit audit contracts (only after a durable commit)
   │        AuditSink.record(SubmittedAuditEvent)   → Module 6 (EPIC-04)
   │        actions: entity.created / relationship.created
   │        provenance_reference(node) ── points at ──► this audit event   (single system of record)
   │        correlation_id preserved on the audit event
   │
   └─► IngestionResult(created_ids, skipped_ids, emitted_audit_event_ids, correlation_id)

supersede_entity / supersede_relationship  → emit entity.superseded / relationship.superseded (+ *.created)
```

## Key decisions

- **Deterministic idempotency.** `entity_id = sha256(entity, source_principal,
  source_type, entity_type, natural_key)` and `relationship_id = sha256(...,
  from_id, to_id)`. Re-ingesting the same payload resolves to the existing node
  and is skipped (no duplicate, no new audit event). Nodes are constructed
  deterministically (no per-ingestion randomness or correlation on the node), so
  a replay is byte-identical.
- **Server-side authority.** `owner`, `provenance_reference`, `trust_score` come
  from `IngestionContext`; they are not fields on the request models, so a
  producer cannot supply them. `trust_score` is an interim source-type default
  (FEAT-05-3 supersedes). `classification` and effective dates remain producer-
  asserted (the source knows the sensitivity and validity window).
- **Provenance = reference, not copy.** The node's `provenance_reference` points
  at the Module-6 audit event recording its creation — grounded/cited by
  construction, single system of record.
- **Transactionality.** One transaction per batch; the store validates the whole
  staged set against current state before writing anything, so a conflict leaves
  the graph untouched. Append-only (no update/delete path).
- **Concurrency.** The in-memory store serializes `_apply` on a lock; concurrent
  identical ingestions collapse to one node (idempotent), never a fork.
- **Audit for all four actions.** `audit.build_mutation_event` builds any of
  `entity.created` / `relationship.created` / `entity.superseded` /
  `relationship.superseded`; `ingest()` emits the *created* actions,
  `supersede_*` emit the *superseded* pair. Full lifecycle management is
  FEAT-05-5.
- **Iterative cycle detection (review fix C1).** `_detect_cycle` uses an
  explicit-stack DFS, not recursion, so a `DERIVED_FROM` chain up to
  `MAX_BATCH_RELATIONSHIPS` cannot raise `RecursionError`; a cycle is a typed
  `CODE_CYCLIC_DEPENDENCY` rejection.

## Deferred hardening (review C2)

The `IngestionResult` created/skipped split and audit emission are computed from
the pre-commit validation snapshot rather than the authoritative commit outcome.
Under a race this can over-report "created" and re-emit a (deterministic,
Module-6-deduped) audit event; the persisted graph is always correct
(lock-serialized `_apply`). This is **not** fixed in Sprint 10 and is recorded
as deferred hardening (have the transaction report the actually-inserted ids;
base the result + audit on the commit outcome) — target phase: the future
persistent (Neo4j) adapter / live ingestion service. See
`security-limitations.md`.

## Packaging correction (documented)

Adding `emg-knowledge-pipeline` surfaced that `emg-ontology` shipped in Sprint 9
**without a `py.typed` marker** (every other shared library has one). A
zero-behavior packaging fix — an empty `py.typed` in `emg_ontology` (and in the
new package) — was added so `emg-ontology` is a properly-typed dependency and
`mypy --strict` on the consumer passes. No `emg-ontology` code, test, or the
golden descriptor is changed.

## Testing

See `testing-strategy.md` (Sprint 10 section): successful ingestion, idempotency,
invalid ontology/relationships, transaction rollback (no partial graph), audit
contract generation + provenance linkage, ownership/trust assignment, batch
ordering, cyclic-dependency rejection, concurrency, oversized-payload rejection,
mass-assignment rejection, plus the Module 6 golden audit-hash and Sprint 9
golden descriptor regressions and the full Sprint 1–9 suite.
