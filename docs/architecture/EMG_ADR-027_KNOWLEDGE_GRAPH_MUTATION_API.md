# ADR-027 (Revision 4) — Knowledge Graph Mutation API

**This revision supersedes ADR-027 Revision 3 in full.**

## 1. Title

Knowledge Graph Mutation API — Fine-Grained Entity/Relationship Write Path,
Reusing the Existing GraphStore Transaction Substrate and the ADR-025/026
Authorization/Classification Pipeline

## 2. Status

**Accepted — Revision 4 (ADR-029 integration, Stage 4 Preflight), Stage 0 complete
(2026-07-28).**
Architecture-only design, produced under
`docs/architecture/PROMPT_TEMPLATE_POST_ADR026.md`. Revision 4 incorporates the Architecture Board’s ratified Stage 4 requirements without reopening the previously accepted ADR-027 decisions. **Stage 0 status:** the `svc-knowledge-graph-writer`
role-catalog entry (§5) and the `mutation_idempotency` table migration
(§8.2) are **complete**. GraphStore Protocol unification (§4.5) remains
**deferred out of this ADR's mandatory implementation gate** — see §4.7
(Deferred Architecture Decision) for the reasoning and the separate analysis
document that governs it. Stage 1 has not begun and is gated on implementation
of approved ADR-029's memory-graph contract.

**Date:** 2026-07-28
**Deciders:** Principal Software Architect / Architecture Board (EMG
Platform); Chief Data Officer (Accountable Owner, Module 7 — ADR-016 §1)
**Baseline:** `adr-026-complete` (commit `5028aa5`)
**Related:** ADR-022 (Revision Build Workflow), ADR-023 (Revision History &
Navigation), ADR-024 (Query Engine), ADR-025 (Tenant & Authorization Model),
ADR-026 Revision 2 (Classification Enforcement Model),
ADR-029 (Canonical Entity and Relationship Identity, Lifecycle, and
Supersession Model), ADR-030 Revision 4 (Mutation Ledger & Atomic Idempotency), ADR-032 (Knowledge Graph Schema Versioning & Evolution),
`EMG_ARCHITECTURE_DECISION_REGISTER.md`, `EMG_PRODUCTION_READINESS_ROADMAP.md`
**Explicitly does not supersede or reopen:** ADR-022/023/024 (revision
model, pagination, temporal semantics), ADR-025 (authorization decision, PEP
wiring, evaluation order), or ADR-026 Revision 2 (classification gate,
evaluation order, uniform-denial principle), or ADR-029 (identity,
lifecycle, supersession, relationship-validity closure, and Merge). All
remain repository fact, unchanged by this ADR.

---

## 3. Problem Statement

### 3.1 Why the current read-only Knowledge Graph is insufficient

`services/knowledge-graph` exposes seven authorization- and
classification-enforced read routes (ADR-024/025/026) over a
PostgreSQL-authoritative, Neo4j-projected graph store. It has **no route
that accepts a write**. Every object currently in the graph got there
through a test fixture or an internal, unauthenticated, non-HTTP call to
`KnowledgeGraphApplication.build_revision()` — there is no path by which an
authenticated human or service caller can add, change, or remove a fact
through the live service. A platform whose only living interaction with its
knowledge substrate is read-only cannot be the system of record the frozen
architecture (`EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9–§11, "Memory Graph —
the core") describes; it is a read replica of nothing, since nothing writes
to it in production. This blocks:

- Any future Knowledge Ingestion Layer (ADR-020, still Proposed) from having
  a concrete, authorized target to write into.
- Modules 8–10 (Search/GraphRAG, AI Orchestration, Decision Intelligence),
  which the Engineering Backlog defines as consumers of a Knowledge Graph
  that is assumed to contain caller-contributed, not just fixture-seeded,
  data.
- A first production-ready release, per
  `EMG_PRODUCTION_READINESS_ROADMAP.md` §7 Phase 2, which names this exact
  decision as "the single highest-leverage undecided item" blocking release
  planning.

### 3.2 Current repository state (verified from source, not documentation claims)

- `emg_knowledge_graph_api/routers/knowledge_graph.py` declares **zero**
  `POST`/`PUT`/`PATCH`/`DELETE` routes — confirmed by direct search; every
  route is a `GET`.
- `KnowledgeGraphApplication` (`emg_knowledge_graph/service.py`) already has
  **two** write-shaped orchestration methods: `build_revision(command:
  BuildRevisionCommand)` and `restore_revision(command:
  RestoreRevisionCommand)`. Neither is called from any HTTP router — both
  are reachable only from test code today.
- `build_revision` takes a **whole-tenant** `entities: tuple[Entity, ...]`
  and `relationships: tuple[Relationship, ...]` and calls
  `MemoryGraphBuilder.from_ontology(entities, relationships, as_of,
  base=current)` inside a `GraphStore.transaction()`, replacing the tenant's
  entire next-revision content by merge/diff against the current head. This
  is a **bulk revision-build** shape, not fine-grained "create one entity" /
  "update one relationship" semantics.
- `libs/python/emg-platform-core/src/emg_platform_core/ports/graph_store.py`
  already defines the durable write substrate: `GraphStore.write()` /
  `GraphStore.transaction()` returning an atomic `GraphTransaction`
  (`read()` the current snapshot, `stage()` a replacement, commit on
  context exit), and an immutable `WriteReceipt` (content hash, node/edge
  counts, principal, tenant, revision number, `revision_created` flag).
  `libs/python/emg-persistence` implements this port with PostgreSQL as the
  authoritative revision log, compare-and-set concurrency, a transactional
  outbox, and a rebuildable Neo4j serving projection.
- **A second, distinct `GraphStore`/`GraphTransaction` Protocol** is defined
  in `libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/graph_store.py`,
  with its own `InMemoryGraphStore`/`InMemoryGraphTransaction` adapter. It
  was built in Sprint 10 (FEAT-05-2) deliberately independent of
  `emg-platform-core`/`emg-memory-graph` — confirmed from
  `emg-knowledge-pipeline`'s own `pyproject.toml`, which declares
  dependencies on only `emg-common-types`, `emg-errors`, `emg-ontology`,
  and `emg-audit-client`; it has never depended on `emg-memory-graph` or
  `emg-platform-core`. The two `GraphStore` Protocols have never been
  reconciled. **§4 resolves this definitively.**
- A **separate library**, `libs/python/emg-knowledge-pipeline`, already
  implements ingestion request models (`EntityIngestionRequest`,
  `RelationshipIngestionRequest`, `IngestionBatch`), an ingestion validator
  (`ValidatedBatch`), a `KnowledgePipeline` orchestrator, deterministic
  idempotent id generation, batch dependency ordering, typed errors
  (`IngestionValidationError`/`IngestionConflictError`/`GraphPersistenceError`),
  and Module-6 audit-contract emission (`entity.created`,
  `relationship.created`, `entity.superseded`, `relationship.superseded`).
- `libs/python/emg-trust-scoring` (Sprint 11) computes an immutable,
  explainable composite trust score from observable signals, but is not
  wired into any ingestion path.
- Approved ADR-029 defines the canonical persisted entity and relationship
  identity, lifecycle, supersession, relationship-validity closure, and
  graph-level Merge contracts that this Mutation API consumes. This ADR
  neither repeats nor modifies those contracts.
- `emg-ontology`'s `Entity`/`Relationship` types already carry
  `classification`, `trust_score`, and `provenance_reference` **by
  construction**.
- `emg-memory-graph` contains ingestion-oriented entity resolution, but
  ADR-029 expressly excludes `EntityResolver` from graph-level Merge
  execution. Merge in this ADR consumes ADR-029 §12 exclusively.
- `libs/python/emg-persistence`'s baseline schema
  (`migrations/postgres/V001__baseline.sql`) already has a working,
  precedent-setting idempotency-key pattern: the `outbox` table's
  `idempotency_key text NOT NULL UNIQUE` column, populated today as
  `f"{tenant}:{revision_number}"` — an **internal**, revision-scoped key
  that deduplicates outbox *publication*, not a caller-facing mutation
  idempotency key. **§8 defines the additive, caller-facing mechanism this
  ADR needs, following the same precedent, not reusing this column
  directly** (its purpose is different: outbox delivery dedup vs. client
  request dedup).
- `graph_revisions`' primary key is `(tenant_id, revision_number)`
  (verified from the same migration file) — the actual, storage-enforced
  compare-and-set mechanism `RevisionRepository.append_revision`/
  `revalidate_head` rely on. **§10 makes this the sole authoritative
  concurrency mechanism.**
- `libs/python/emg-policy-engine/src/emg_policy_engine/roles.py`'s
  `ROLE_CATALOG` has exactly eight entries today: `platform-user`,
  `investigator`, `decision-maker`, `knowledge-steward` (human);
  `service-account`, `svc-identity`, `svc-authorization`, `svc-audit`
  (service). **No service role for a Knowledge Graph writer exists yet —
  §5 requires adding one, as vocabulary data, per the exact precedent
  `svc-audit`/`svc-identity`/`svc-authorization` already set.**
- ADR-025/026 already prove a complete, working, auditable
  authorization/classification pipeline
  (`PolicyEnforcementPoint.authorize()` → `PolicyEngine.evaluate()` →
  `Decision`) for **reads**. §5 extends it, unmodified in kind, to writes.

### 3.3 Existing capabilities this ADR reuses without modification

1. The durable, transactional write substrate (`GraphStore`/
   `GraphTransaction`/`WriteReceipt`, `emg-persistence`'s compare-and-set +
   outbox + Neo4j projection).
2. The revision/versioning model (ADR-022/023).
3. The authorization/classification decision pipeline (ADR-025/026).
4. The audit event contract (`emg-audit-client.SubmittedAuditEvent`) and
   `emg-knowledge-pipeline`'s already-designed event-type vocabulary.
5. The ontology's classification/trust/provenance-bearing types and
   `emg-trust-scoring`'s scoring engine.
6. ADR-029's canonical identity, lifecycle, supersession, relationship
   closure, and graph-level Merge contract.
8. The `ON CONFLICT ... DO NOTHING` / unique-constraint idempotency pattern
   already proven twice in this exact schema
   (`checkpoint_repository.py`, `revision_repository.py`'s `graph_head`
   upsert, and the `outbox.idempotency_key` column).

### 3.4 Existing limitations resolved by this revision

1. Two non-unified `GraphStore` Protocols — **decided, §4; elimination
   deferred, §4.7** (this ADR's own mutation surface uses the correct,
   unified contract regardless — §4.4).
2. No fine-grained mutation command — **resolved, §7.**
3. No mutation authorization or classification-propagation design —
   **resolved, §5.**
4. No idempotency mechanism specified — **resolved, §8.**
5. No single authoritative concurrency mechanism specified — **resolved, §10.**
6. No batch-mutation semantics — **resolved, §11.**
7. Soft delete previously duplicated identity/lifecycle decisions —
   **resolved by consuming ADR-029, §9.**
8. No operational constraints — **resolved, §12.**
9. `emg-entity-resolution` ownership remains unresolved (D-A-002, still
   open, a separate registered decision) — this ADR does not depend on
   `emg-entity-resolution`; graph-level Merge is defined by ADR-029 and
   does not use either entity-resolution package as its executor.

---

## 4. GraphStore Architecture — Definitive Decision

### 4.1 The problem, stated precisely

Two Protocols named `GraphStore` exist in this repository:

| | `emg_platform_core.ports.graph_store.GraphStore` | `emg_knowledge_pipeline.graph_store.GraphStore` |
| --- | --- | --- |
| Introduced | Phase 1 (Platform Foundation) | Sprint 10 (FEAT-05-2) |
| Typed against | `emg_memory_graph.MemoryGraph` | Its own ingestion-shaped types only |
| Adapters | `InMemoryGraphStore`; `emg-persistence`'s `PostgresNeo4jGraphStore` (production-shaped: compare-and-set, outbox, Neo4j projection) | `InMemoryGraphStore` only — no durable adapter exists |
| Consumers today | `services/knowledge-graph` (`KnowledgeGraphApplication`) | `emg-knowledge-pipeline` internals only |
| Governing Freeze reference | §11 ("one writer per store"), §32 (names this exact port) | None — not a Freeze-named concept |

Both are structurally similar (read/stage/commit-shaped), but they are
**not the same type**, were never proven interchangeable, and nothing in
the repository bridges them. This is the textbook definition of
architectural drift: one concept, two independent, silently diverging
definitions.

### 4.2 Options considered

**Option 1 — Merge into a new, third Protocol.** Rejected. Neither existing
Protocol is deficient relative to the other in a way that requires new
capability; a third type would be pure churn, and every existing consumer
of `emg_platform_core.ports.graph_store` (`services/knowledge-graph`,
`emg-persistence`) would still need updating regardless — merging invents
work without eliminating a maintainer's need to update call sites.

**Option 2 — Adapter/bridge pattern (keep both, translate between them).**
Rejected. An adapter perpetuates the drift it is meant to solve: every
future change to either Protocol's shape (e.g., a new `WriteReceipt` field,
already this platform's own history — ADR-023 added `revision_number`/
`committed_at`/`revision_created` to `WriteReceipt` after it first shipped)
requires the bridge to be updated in lockstep or it silently degrades.
An adapter also means `emg-knowledge-pipeline` still has no durable
(non-in-memory) storage adapter of its own and would need one written
*for the bridge specifically* — duplicating `emg-persistence`'s already-built,
already-tested `PostgresNeo4jGraphStore` for no reason. This does not
satisfy "this decision must eliminate architectural drift" — it manages
drift, it does not eliminate it.

**Option 3 — Replace `emg_knowledge_pipeline.graph_store` with
`emg_platform_core.ports.graph_store`; retire the pipeline's own Protocol
and `InMemoryGraphStore`/`InMemoryGraphTransaction` adapter entirely.**
**Selected.**

### 4.3 Decision

`emg_platform_core.ports.graph_store.GraphStore`/`GraphTransaction`/
`WriteReceipt` becomes the **single, platform-wide write-substrate
contract**. `emg-knowledge-pipeline` gains `emg-memory-graph` and
`emg-platform-core` as declared dependencies (an additive, non-circular
edge — `emg-platform-core` depends one-directionally on `emg-memory-graph`,
per the already-accepted OBS-A-001 direction, and neither depends back on
`emg-knowledge-pipeline`), converts its `EntityIngestionRequest`/
`RelationshipIngestionRequest`/ontology objects into `MemoryNode`/
`MemoryEdge` via the existing `MemoryNode.from_entity` adapter and
`MemoryGraphBuilder` (both already built, already used by
`build_revision`), and its own `graph_store.py` module — the Protocol
definitions and the `InMemoryGraphStore`/`InMemoryGraphTransaction`
adapter — is deleted outright, not deprecated-in-place.

### 4.4 Rationale

- `emg_platform_core.ports.graph_store` is the Freeze-named seam (§32:
  "Introduce a `GraphStore` port ... with a Neo4j adapter for durability
  and an in-memory adapter for tests") — it is the platform's authoritative
  concept, not a peer of the pipeline's Protocol.
- It is strictly the more mature contract: it already has a real,
  production-shaped durable adapter (`emg-persistence`'s
  `PostgresNeo4jGraphStore`, with compare-and-set, transactional outbox,
  and Neo4j projection) that `emg-knowledge-pipeline`'s own Protocol has
  never had and would otherwise need to grow independently.
- Standardizing on one Protocol is what "one writer per store" (Freeze §11)
  means at the abstraction level, not only at the running-process level —
  two Protocols for the same concept is exactly the condition that
  principle argues against.
- This ADR's own fine-grained mutation commands (§7) already commit
  through `emg_platform_core.ports.graph_store` — standardizing
  `emg-knowledge-pipeline` on the same contract means a future ADR-020
  batch-ingestion path built on `emg-knowledge-pipeline` writes through the
  *exact same* storage substrate this ADR's synchronous path uses, with no
  reconciliation ever required again.

### 4.5 Migration strategy

**Deferred — see §4.7.** The steps below remain the designed mechanism for
eventually eliminating the two-`GraphStore`-Protocol duplication, but they
are no longer a mandatory Stage 0 gate for this ADR's own implementation
(§14). They are retained here as the reference design for whichever future
change ultimately carries them out.

1. Add `emg-memory-graph` and `emg-platform-core` to
   `emg-knowledge-pipeline`'s `pyproject.toml` dependencies (and
   `docker/dependencies.yaml` manifest entry, per existing governance
   convention).
2. Replace every internal use of
   `emg_knowledge_pipeline.graph_store.GraphStore`/`GraphTransaction` with
   `emg_platform_core.ports.graph_store.GraphStore`/`GraphTransaction`.
3. Replace `emg_knowledge_pipeline`'s internal graph-content construction
   (whatever it builds today in place of `MemoryGraph`) with
   `MemoryGraphBuilder`/`MemoryNode.from_entity`/`MemoryEdge`-shaped
   construction, reusing the exact conversion `build_revision` already
   performs — not a new conversion path.
4. Delete `emg_knowledge_pipeline/graph_store.py` and its
   `InMemoryGraphStore`/`InMemoryGraphTransaction` classes outright.
5. Update `emg-knowledge-pipeline`'s existing test suite to construct
   against `emg_platform_core.ports.graph_store.InMemoryGraphStore`
   (already built, already used by `services/knowledge-graph`'s own tests)
   instead of its own now-deleted in-memory adapter.
6. Add a new repository-governance/architecture-fitness test —
   `test_only_one_graphstore_protocol_exists` (an `ast`-based scan, in the
   same style as the existing dependency-boundary tests in
   `services/knowledge-graph/tests/test_dependency_boundary.py` and
   `libs/python/emg-policy-engine/tests/test_no_scripting_capability.py`)
   — asserting no second `Protocol` class named `GraphStore` (or
   structurally equivalent: a `Protocol` declaring `read`/`write`/
   `transaction` methods) is declared anywhere in the repository outside
   `emg_platform_core.ports.graph_store`. This is the long-term
   maintenance mechanism (§4.6) that makes recurrence of this exact drift
   a CI failure, not a future architecture review's rediscovery.

This migration was originally scoped as **Stage 0** of this ADR's overall
migration sequence (§14). It has since been **removed from that mandatory
gate and deferred** — see §4.7. Stage 1 (fine-grained commands) does **not**
require this migration to proceed: §4.4's fourth rationale bullet already
establishes that Stage 1's commands commit through
`emg_platform_core.ports.graph_store` directly, with no dependency on
`emg-knowledge-pipeline`'s internal storage code either way.

### 4.6 Ownership and long-term maintenance plan

- **Ownership:** `emg_platform_core.ports.graph_store` remains owned by the
  Platform Foundation package — the single storage-independence seam for
  the whole platform (Freeze §32). `services/knowledge-graph` and
  `emg-knowledge-pipeline` are both **consumers**, not co-owners; neither
  may fork or redeclare the contract.
- **Change control:** any future change to `GraphStore`/`GraphTransaction`/
  `WriteReceipt`'s shape is made exactly once, in
  `emg_platform_core.ports.graph_store`, and every consumer picks it up
  structurally (a `Protocol`, so no explicit inheritance chain to update) —
  exactly how ADR-023 already extended `WriteReceipt` once and every
  consumer (`services/knowledge-graph`, `emg-persistence`) received the new
  fields without a parallel update elsewhere.
- **Drift prevention:** the new architecture-fitness test (§4.5, item 6)
  is the standing, automated guarantee that no third `GraphStore`-shaped
  Protocol is ever introduced without deliberately failing CI first —
  eliminating drift, not merely documenting a rule against it.
- **Future consumers:** any future service or library needing durable graph
  write access (a future ADR-020 ingestion service, a future Search
  indexer needing write-side hooks) depends on
  `emg_platform_core.ports.graph_store` directly, never on
  `services/knowledge-graph`-internal or `emg-knowledge-pipeline`-internal
  storage code.

### 4.7 Deferred Architecture Decision: GraphStore Protocol Unification

**Status: Deferred. Treated as a separate architectural concern, outside
the scope of this ADR's implementation gate.**

During Stage 0 implementation, carrying out §4.5's migration strategy
against `emg-knowledge-pipeline` was found to require a larger refactor and
a genuine, reviewable architectural decision of its own — not the mechanical
Protocol swap §4.5 describes. The full analysis is recorded separately in
`docs/architecture/EMG_ADR-027_STAGE_0_1_GRAPHSTORE_UNIFICATION_ANALYSIS.md`
and is incorporated here by reference. Summary of the finding:

- The two `GraphStore` Protocols differ in write grain (per-object vs.
  whole-graph-snapshot), tenancy (untenanted vs. tenant-scoped), and
  conflict semantics (per-object `Entity`/`Relationship` equality vs. no
  per-node comparison at all in the platform-core Protocol).
- `emg-knowledge-pipeline`'s existing idempotent-skip/conflict detection
  (`validation.py`, comparing `existing.model_dump() == built.model_dump()`
  on full `Entity`/`Relationship` objects) cannot be reproduced against the
  unified store without a semantic change: `MemoryNode.from_entity()` is a
  lossy conversion that does not retain enough of the original `Entity`
  (`owner`, `lifecycle_status`, `version`, `effective_to`,
  `supersedes`/`superseded_by`, domain attributes) to redo a faithful
  equality check.
- `IngestionContext` has no `tenant` concept today, which the unified,
  tenant-scoped `GraphStore` requires.

**Decision: defer the unification (Strategy B of the referenced analysis).**
`emg-knowledge-pipeline` is left untouched — its existing `GraphStore`
Protocol, `InMemoryGraphStore`, and `validation.py` idempotency/conflict
logic continue to operate exactly as they do today, unmodified by this ADR.
The eventual unification is tracked as its own future architectural change,
to be designed and reviewed on its own terms (per the referenced analysis'
§3, Strategy A), never folded into a "no feature work" implementation stage
again.

**Why deferral preserves behavioral correctness and avoids semantic
regression:**

1. **No code path this ADR introduces depends on it.** §4.4's fourth
   rationale bullet already establishes that this ADR's own mutation
   commands (Stage 1 onward) commit through
   `emg_platform_core.ports.graph_store` directly — the same substrate
   `build_revision` already uses — regardless of whether
   `emg-knowledge-pipeline`'s separate ingestion path is ever unified with
   it. Deferring the unification blocks nothing this ADR needs to build.
2. **Attempting it now would have forced an unreviewed behavior change.**
   Under Stage 0's explicit "no feature work" constraint, the only way to
   make `validation.py`'s idempotency logic compile against the unified
   store was to narrow its conflict-detection semantics (comparing fewer
   fields than it does today) — a real, observable behavior change to
   FEAT-05-2's ingestion contract that had never been proposed, reviewed, or
   approved on its own merits. Deferring keeps `emg-knowledge-pipeline`'s
   current, correct, already-tested behavior fully intact.
3. **The drift this decision (§4) identifies is a maintainability/CI-fitness
   concern, not a correctness or security defect.** Two differently-shaped
   `GraphStore` Protocols coexisting is undesirable long-term hygiene, but
   neither Protocol is wrong for the code that uses it today, and nothing
   about ADR-025/026's authorization or classification guarantees depends
   on the two being merged. Deferring the merge does not reopen or weaken
   any preserved security guarantee.
4. **The deferral is tracked, not silent.** This section, the referenced
   analysis document, and task-tracking metadata all record the deferral
   explicitly, with a recommended follow-up strategy already drafted (the
   analysis document's §3, Strategy A) — this is a disclosed, deliberate
   scope boundary, not a dropped requirement.

---

## 5. Authorization Matrix — Definitive, Not Deferred

Every mutation operation's authorization is expressed as `PolicyRule` data
(`resource_type`, `action`, `required_roles`, `required_attributes` for the
principal side, `required_resource_attributes` for the object-classification
side) evaluated by the **unchanged** `PolicyEngine`/`PolicyEnforcementPoint`
— no new authorization mechanism, exactly per ADR-025/026's own precedent
and Appendix ADR-026A's standing rule.

### 5.4 Authorization Preflight and Resource Metadata

Authorization preflight occurs before opening `GraphStore.transaction()`. Ownership and classification metadata are retrieved through a read-only application-layer interface named `IResourceMetadataReader`. Routers must not access `GraphStore` directly. Mutation execution uses `AtomicMutationExecutionPort` under ADR-030. Schema negotiation follows ADR-032 before command construction. The public response follows ADR-030 Revision 4.

**One new role-catalog vocabulary entry is required** (data only, per the
exact precedent `svc-identity`/`svc-authorization`/`svc-audit` already set
in `ROLE_CATALOG` — no catalog mechanism change):

| `role_id` | category | description |
| --- | --- | --- |
| `svc-knowledge-graph-writer` | service | Least-privilege role for a service principal authorized to mutate the Knowledge Graph (e.g. a future ADR-020 ingestion service). |

No other catalog change is required; human mutation authority uses the
existing `knowledge-steward` role, already catalogued for "Knowledge Graph
steward — Knowledge Authoring UI (Module 7)."

### 5.1 The matrix

`resource_type` for every row is `knowledge-graph.entity` or
`knowledge-graph.relationship` as named. "Clearance rule" always means: the
caller's resolved `classification_clearance` (ADR-026 §8.4, including this
session's `normalize_classification_clearance` fix ensuring an unrecognized
value never survives as a literal string) must **dominate** every
classification value the rule names, using the same enumerated
`required_resource_attributes` dominance-table mechanism ADR-026 Amendment
1 already established — never a new ordinal comparator.

| Operation | `action` | Required permission (`required_roles`) | Clearance rule | Human identity rule | Service identity rule |
| --- | --- | --- | --- | --- | --- |
| Create Entity | `create` | `knowledge-steward` (human) or `svc-knowledge-graph-writer` (service) | Dominate the new entity's `classification` | `knowledge-steward` only | `svc-knowledge-graph-writer` only; bare `service-account` insufficient |
| Update Entity | `update` | `knowledge-steward` or `svc-knowledge-graph-writer` | Dominate **both** the entity's current classification and the new classification being written | Must be the recorded owner, or hold an owner-override condition (§5.2); `knowledge-steward` may override | Owner-override does not apply to service callers — a service principal may only update an entity it itself created (owner match only, no override) |
| Delete Entity (soft delete) | `retire` | `knowledge-steward` or `svc-knowledge-graph-writer` | Dominate the entity's current classification | Same ownership rule as Update; requires non-blank `reason` (§9.4) | Same as Update; requires non-blank `reason` |
| Restore Entity | `restore` | `knowledge-steward` **only** | Dominate the classification of the content being restored | `knowledge-steward` only — `required_roles=["knowledge-steward"]` alone already excludes every service principal, since service tokens never carry a human role (§5.3) | **Never authorized** — no service principal, regardless of role, may restore |
| Merge Entity | `merge` | `knowledge-steward` **only** | Dominate the **maximum** classification across every input entity being merged; ADR-029 §12 owns the resulting survivor classification and field-combination semantics | `knowledge-steward` only | **Never authorized** |
| Update Classification (reclassify) | `reclassify` | `knowledge-steward` **only** | Dominate **both** the current and the target classification | `knowledge-steward` only; a narrower "classification authority" concept beyond role-gating is reserved and requires its own future ADR per Appendix ADR-026A principle 3 — not designed here | **Never authorized** |
| Create Relationship | `create` | `knowledge-steward` or `svc-knowledge-graph-writer` | Dominate the relationship's own classification **and** both endpoint entities' classifications | Same as Create Entity | Same as Create Entity |
| Update Relationship | `update` | `knowledge-steward` or `svc-knowledge-graph-writer` | Dominate current and new relationship classification, and both endpoints' classifications | Same as Update Entity | Same as Update Entity |
| Delete Relationship | `retire` | `knowledge-steward` or `svc-knowledge-graph-writer` | Dominate the relationship's current classification and both endpoints' classifications | Same as Delete Entity | Same as Delete Entity |
| Bulk Operations | `bulk` | `knowledge-steward` or `svc-knowledge-graph-writer` | Dominate the **maximum** classification across every object in the entire batch (a single worst-case check; §11) | `knowledge-steward` only for a human-submitted batch | `svc-knowledge-graph-writer` — the intended primary caller for bulk (future ADR-020 ingestion) |

### 5.2 Ownership-override condition

"Owner-override" (Update/Delete Entity and Relationship, human path) is
expressed as an additional `required_attributes`/ownership check the HTTP
layer performs before calling the PEP a second time if the caller is not
the recorded owner: a `knowledge-steward` may act on any entity regardless
of recorded owner; a caller without that role may only mutate an entity
they themselves are recorded as owning (`owner` is server-assigned at
creation, with persistence defined by ADR-029 §9.1 — never
caller-supplied). This is not a new authorization mechanism — it is a
`resource_attributes` comparison (`owner == caller.subject`) of the exact
same shape ADR-026 Amendment 1 already generalized, evaluated through the
same PEP call.

### 5.3 Why `required_roles=["knowledge-steward"]` alone excludes every service caller

Roles are populated per caller kind at token-issuance time
(`services/identity`'s human login flow vs. each service's own
`ServiceTokenValidator`) — a service principal's `roles` tuple is always
drawn from its registered service-account roles (`service-account`,
`svc-*`), never from the human role vocabulary. No service token in this
repository has ever carried, or could be configured to carry, the
`knowledge-steward` role without also being issued as a human session
token — which would violate the platform's existing, cryptographically
enforced human/machine separation
(`services/identity/tests/test_separation_human_vs_service.py`, unchanged
by this ADR). Restricting Restore/Merge/Reclassify to
`required_roles=["knowledge-steward"]` is therefore sufficient, by
construction, to exclude every service caller — no additional
"human-only" mechanism is introduced.

---

## 6. Goals

1. Define a fine-grained mutation surface — entity creation, entity update,
   relationship creation, relationship update, soft delete, restore, merge,
   reclassification, and bulk operations — that a properly authorized human
   or service caller can invoke over HTTP, with every operation's
   authorization fully specified (§5), not deferred.
2. Reuse, never duplicate, the existing write substrate, revision model,
   and authorization/classification pipeline.
3. Make every mutation idempotent (§8), concurrency-safe under one
   authoritative mechanism (§10), and classification-consistent with
   ADR-026's enforcement model.
4. Eliminate the two-`GraphStore`-Protocol drift definitively (§4). **Status:
   deferred (§4.7)** — this ADR's own mutation surface does not route
   around the drift (it commits through `emg_platform_core.ports.graph_store`
   directly, per §4.4), but the drift's actual elimination in
   `emg-knowledge-pipeline` is tracked as separate future work, not achieved
   by this ADR.
5. Produce a design a future ADR-020 (Knowledge Ingestion Layer) can sit in
   front of (bulk/batch ingestion) without needing to re-litigate any
   decision this ADR fixes.

## 7. Non-Goals

This ADR does not design: Search, GraphRAG, AI Orchestration, or Decision
Intelligence (Modules 8–10); a general-purpose graph query language or bulk
import file format (ADR-020's scope, though this ADR's Bulk Operations
authorization/atomicity model, §5/§11, is a fixed input ADR-020 must build
against); a new authorization mechanism; audit reconciliation (ADR-028); a
  physical-deletion/erasure mechanism (ADR-029 and §9.3 keep this explicitly out of
scope, not merely deferred); real-time collaborative editing or
  conflict-resolution UX; a caller-supplied `If-Match`-style optimistic
  concurrency precondition (§10.2, reserved for ADR-021); or any change to
  `emg_knowledge_graph`'s existing traversal, pagination, temporal, or
  revision-selection algorithms, `GraphStore` (post-§4 unification),
  persistence internals, or the Neo4j projection's own mechanics. The
  lifecycle-visibility eligibility rule required by ADR-029 §18 and consumed
  in §9.6 is not a new query algorithm.

---

## 8. Idempotency Architecture

### 8.1 Idempotency key format

A caller-supplied, opaque string, required on every mutation request
(single or bulk). Validated the same way every other identifier in this
platform already is — bounded length (`MAX_LABEL_LENGTH`-equivalent
ceiling, 256 characters) and passed through the existing
`ensure_safe_label`-style safety check (no control/bidi characters),
reusing `emg-memory-graph`'s existing validation utility rather than
inventing a new one. The server treats the value as opaque; no required
internal structure (UUID, hash, etc.) is mandated, though a client is
expected to derive it deterministically from its own request so that a
genuine retry of "the same logical action" reuses the same key (§8.7).

### 8.2 Storage strategy

A new, additive table, owned by `libs/python/emg-persistence` (the same
package that owns `graph_revisions`/`graph_head`/`outbox` today), following
the exact `idempotency_key ... UNIQUE` precedent the `outbox` table's own
schema already establishes:

**`mutation_idempotency`** — columns: `tenant_id`, `principal_id`,
`idempotency_key`, `operation_type`, `revision_number`, `content_hash`,
`receipt_json` (the serialized `WriteReceipt`), `requested_at`,
`expires_at`. Unique constraint on **`(tenant_id, principal_id,
idempotency_key)`** — deliberately scoped by principal, not only tenant
(§8.8 explains why). A row is inserted **only** after a mutation's
transaction commits successfully (§8.6) — via the same `ON CONFLICT ...
DO NOTHING` atomic-insert pattern already used twice in this exact schema
(`checkpoint_repository.py`; `revision_repository.py`'s `graph_head`
upsert), not a new persistence pattern.

### 8.3 Lifetime (TTL)

A fixed, `Settings`-configurable duration, default **24 hours** —
consistent with this platform's existing convention of configurable,
non-hardcoded time windows (`login_rate_limit_window_seconds`,
`access_token_ttl_seconds`) rather than a literal buried in logic. Rows
past `expires_at` are eligible for removal by either a lazy
`WHERE expires_at < now()` deletion on next write to the same tenant, or a
periodic reaper — the exact mechanism is an implementation detail; the TTL
concept and its configurability are the fixed architectural requirements.

### 8.4 Replay behavior

A request presenting a `(tenant_id, principal_id, idempotency_key)` already
present and unexpired returns the **original stored `WriteReceipt`
verbatim** (the same success response the original request received) —
**without** re-running authorization, classification propagation, or
validation a second time. This is a receipt lookup, not a new decision: a
completed mutation's outcome is fixed at commit time, and re-authorizing on
replay risks an inconsistent "sometimes idempotent, sometimes 403"
experience if the caller's permissions changed between the original call
and the replay. The replay path is therefore: authenticate → resolve tenant
→ look up `(tenant_id, principal_id, idempotency_key)` → if found and
unexpired, return the stored receipt and **stop** (skip every subsequent
step in §13's sequence diagram).

### 8.5 Duplicate detection

Identical to replay (§8.4) — detection **is** the unique-key lookup,
performed immediately after tenant resolution and before the operation-level
PEP call, so a genuine duplicate never re-incurs an authorization or
validation cost.

### 8.6 Failure recovery

**A `mutation_idempotency` row is written if, and only if, the mutation's
`GraphStore.transaction()` commits successfully.** A failed attempt —
validation error, authorization denial, classification denial, or
`ConflictError` — writes **no** row. This guarantees idempotency only ever
memorizes success, never a failure: a client retrying after any failure
mode re-attempts the full pipeline from scratch, exactly as if it were a
first attempt, and can safely reuse the same idempotency key for that retry
without risk of a false-success replay.

### 8.7 Client responsibilities

- Generate one idempotency key per logical mutation attempt; reuse the same
  key across retries of that same logical action; use a new key for a
  genuinely new action.
- Treat a replayed response identically to the original response — a client
  must not assume "replayed" is observable or requires different handling.
- Do not assume a key remains meaningful beyond the documented TTL (§8.3);
  a retry attempted after expiry is treated as a new, non-idempotent
  request.

### 8.8 Server responsibilities

- Enforce `(tenant_id, principal_id, idempotency_key)` uniqueness atomically
  at the storage layer (§8.2), never as an application-level
  check-then-insert race.
- **Scope the key by principal, not only tenant**, so that a different
  principal presenting the same literal key string never receives another
  principal's receipt — a cross-principal key collision is treated as two
  independent, unrelated requests, each fully authorized on its own terms.
  This closes a replay-based information-disclosure risk an
  identically-named-but-tenant-only-scoped key would otherwise create.
- Never persist a key/receipt pair for a failed attempt (§8.6).
- Expire and reclaim keys past TTL (§8.3).
- Validate key shape/length before use (§8.1), rejecting an invalid key with
  the same `InvalidMutationCommandError` shape (§15.1) as any other
  command-shape validation failure.

---

## 9. ADR-029 Domain-Model Dependency

### 9.1 Authority boundary

ADR-029 exclusively owns:

- canonical entity and relationship identity;
- persisted lifecycle state and legal transitions;
- supersession representation, bounds, integrity, and derived reverse lookup;
- graph-level Merge eligibility, field combination, source handling, incident
  relationship closure/reassignment, collision behavior, and atomicity;
- relationship endpoint immutability and validity-closure construction; and
- the additive `MemoryGraphBuilder` replacement path used to realize those
  changes without mutating frozen objects.

ADR-027 does not redefine any of those concepts. Commands validate their own
transport/application fields, authorize under §5, invoke the corresponding
ADR-029 construction operation inside the §13 transaction sequence, and map
the committed receipt. Domain-model validation errors defined by ADR-029
surface through §15's existing validation/failure categories.

### 9.2 Mutation-to-domain mapping

| ADR-027 operation | ADR-029 authority consumed |
| --- | --- |
| Create/Update/Reclassify Entity | Identity preservation, owner/lifecycle fields, and replacement construction: ADR-029 §§9–10, §13 |
| Delete Entity (`retire`) | Lifecycle transition and incident-relationship closure: ADR-029 §§10, 14 |
| Restore Entity | Restore transition and eligibility: ADR-029 §10.2 |
| Merge Entity | Complete graph-level Merge contract: ADR-029 §12 |
| Create/Update Relationship | Relationship identity and endpoint rules: ADR-029 §9.2 |
| Delete Relationship (`retire`) | Relationship validity closure: ADR-029 §14 |

No operation uses `EntityResolver` as a graph-mutation executor, writes
`superseded_by`, mutates an existing frozen node or edge, or derives lifecycle
state independently of ADR-029.

### 9.3 Physical deletion and terminology

No operation defined by this ADR physically deletes a node, edge, or immutable
revision. Physical erasure remains outside ADR-027 and ADR-029.

“Restore Entity” in this ADR means the entity lifecycle operation governed by
ADR-029. It is distinct from ADR-023's `RestoreRevisionCommand`, which stages an
entire historical graph as a new tenant revision and does not perform an
entity-lifecycle transition.

### 9.4 Audit and reason requirements

Delete, Restore, Merge, and Reclassify requests require a caller-supplied,
non-blank `reason`, rejected as a command-shape validation failure (§15.1) when
absent. Their audit actions remain owned by this Mutation API and ADR-028's
future reconciliation work; the state, identity, supersession, relationship
closure, and Merge facts described by those events come exclusively from the
ADR-029 result committed in the same transaction.

### 9.5 Classification boundary

ADR-026 and §5 own authorization and classification-clearance evaluation.
ADR-029 owns how classification is preserved or combined by a domain mutation.
ADR-027 neither introduces a second classification mechanism nor restates
ADR-029's field-combination rules.

### 9.6 Current-view lifecycle visibility

ADR-029 §18 assigns lifecycle-aware query visibility to ADR-027 Revision 3.
Current-view entity projections therefore consult ADR-029's canonical
`lifecycle_status` and `LIVE_STATES`: an entity outside `LIVE_STATES` is
absent from ordinary current-view entity results. This is lifecycle
eligibility, not an authorization decision; ADR-026 classification checks
still run exclusively through the existing PEP/PolicyEngine path.

ADR-023 historical revision reads remain exact immutable snapshot reads and
are not rewritten or filtered by this rule. ADR-024's traversal, pagination,
temporal containment, cursor, and revision-selection algorithms remain
unchanged. For current-view list and traversal results, implementations apply
the ADR-029 eligibility predicate to the candidate graph/result set before
constructing pagination counts, cursors, paths, or history output, then
preserve each endpoint's existing absent/empty response shape. This prevents
non-live entity existence from being exposed through post-filter counts or
cursors without introducing a second lifecycle definition.

---

## 10. Concurrency Model — Authoritative Mechanism

### 10.1 The single authoritative mechanism

**Optimistic concurrency via compare-and-set on the tenant's expected next
revision, enforced at the storage layer by `graph_revisions`' own
`(tenant_id, revision_number)` primary key** — not an application-level
check, a database-enforced constraint. "Compare-and-set," "expected
revision," and "optimistic concurrency" are not three competing mechanisms
this ADR must choose between — they are one mechanism described at three
levels of abstraction: optimistic concurrency is the *strategy*,
compare-and-set is the *pattern*, and the expected next `revision_number`
(equivalently, the parent's `content_hash`) is the *specific value*
compared. This ADR fixes this as authoritative and introduces no
alternative or additional concurrency primitive.

Mechanically, unchanged from `emg-persistence`'s existing implementation
(`RevisionRepository.append_revision`/`revalidate_head`,
`PersistenceConflictError`): every mutation's `GraphStore.transaction()`
reads the current head at start, and the commit only succeeds if no other
writer has advanced that tenant's head in the interim — enforced atomically
by the primary-key constraint on `(tenant_id, revision_number)`.

### 10.2 `expected_revision` is not a caller-supplied HTTP parameter

None of this ADR's endpoints (§6 of the underlying mutation design) require
or accept a caller-supplied "I expect the current revision to be N"
precondition (an `If-Match`-style convention). The expected revision is
always "whatever this transaction's own `read()` observed at start,"
resolved entirely server-side — consistent with how `build_revision`/
`restore_revision` already behave today. A future caller-supplied
optimistic-concurrency precondition is a **reserved extension point**, not
designed here: no existing read or write endpoint in this platform uses
that convention, and introducing it would be a REST-conventions decision
better made holistically under ADR-021 (Enterprise API Strategy, still
Proposed) than locally in this ADR.

### 10.3 Conflict detection

Unchanged: `PersistenceConflictError`, raised by the existing
`emg-persistence` implementation at commit time, mapped to HTTP 409 via the
existing `emg-errors` `ConflictError` family.

### 10.4 Retry behavior

**The server never automatically retries a conflicted mutation.** A
`ConflictError` is surfaced to the caller exactly once per attempt; the
caller decides whether to re-read and reissue. Automatic server-side retry
is deliberately rejected: it would silently re-run authorization,
classification propagation, and validation against a snapshot the original
caller never saw and never consented to, which conflicts with this ADR's
fail-closed principle of never applying a decision the caller did not
explicitly request against the state it was made against.

### 10.5 Concurrent mutation handling for batches

A batch's compare-and-set covers the batch's single resulting revision
(§11) — a conflict fails the **entire** batch atomically, identical in kind
to a single mutation's conflict handling, never a partial-batch commit.

---

## 11. Batch Mutation Behavior

### 11.1 Decision: one batch, one revision

A batch mutation (§5, "Bulk Operations") commits as **exactly one**
revision, regardless of how many entities/relationships it contains — not
one revision per contained mutation.

### 11.2 Justification

- This is the exact shape `build_revision`/`MemoryGraphBuilder.from_ontology`
  already implement today — accepting an arbitrary-size tuple of
  entities/relationships and committing them as a single revision. "One
  mutation per revision" for a batch would require either opening N
  sequential transactions per batch item (N compare-and-set round-trips, N
  revisions, N outbox events for what the caller considers one logical
  action — a poor fit for "batch" semantics and a direct contradiction of
  the atomicity a bulk caller expects), or inventing a partial-revision/
  patch-revision concept this platform's revision model does not have and
  this ADR does not introduce.
- **Atomicity is preserved by construction:** a batch either fully commits
  (one `WriteReceipt`, one revision) or fully fails — no client ever
  observes a batch half-applied, extending this design's existing
  "partial failures are impossible by construction" principle from single
  mutations to batches without exception.
- **Batching reduces, not increases, compare-and-set contention:** N
  logical changes become one compare-and-set attempt instead of N,
  which is the opposite direction from the scaling risk already disclosed
  for high-frequency small mutations (§17, risk item 2) — batching is a
  mitigation for that risk, not an aggravation of it.

### 11.3 Rollback behavior

Identical to any other mutation's rollback: the transaction's own
context-manager semantics abort the **entire** batch if any single item
fails command-shape validation, ontology conformance validation, or
graph-level construction (referential integrity, bounds) — no compensating
logic, no partial commit. A failed batch produces **zero** committed
changes and exactly **one** denied/error-outcome `SubmittedAuditEvent` for
the batch as a whole (not one per contained item, since no item was
actually applied).

### 11.4 Separation of powers within a batch

A batch may only contain `create`/`update`/`retire` operations (§5) — it
may **never** contain a `restore`, `merge`, or `reclassify` operation. This
is a deliberate constraint closing a real gap: without it, a bulk/service
caller could smuggle a human-only operation (§5.1: Restore/Merge/Reclassify
are `knowledge-steward`-only) inside an otherwise-permitted batch. A batch
containing any such operation is rejected at command-shape validation
(§15.1), before authorization, as a well-formedness failure — a batch is
not "authorization-denied" for containing a disallowed operation type, it
is invalid input.

---

## 12. Operational Constraints

These are architectural ceilings, not implementation tuning — the exact
numeric values may be tuned at implementation time within the requirement
that a fixed, code-level ceiling exists (the same "fixed ceiling, not
runtime configuration" convention `MAX_QUERY_PAGE_SIZE`/`MAX_TRAVERSAL_DEPTH`
already establish in `emg_knowledge_graph/commands.py`).

| Constraint | Value | Rationale |
| --- | --- | --- |
| Maximum single-mutation size | Exactly one entity or one relationship | Matches §5/§7's single-object design; existing `MemoryNode`/`MemoryEdge`/ontology field bounds (`MAX_ALIASES`, `MAX_EVIDENCE_REFS`, `MAX_LABEL_LENGTH`, etc.) apply unchanged. |
| Maximum batch size | 500 combined entities + relationships per batch | A fixed ceiling in the same order of magnitude as the existing `MAX_QUERY_PAGE_SIZE = 200` read-side bound, sized upward to accommodate a batch legitimately mixing entities and relationships in one logical unit. |
| Maximum relationships per non-batch request | 1 | A single Create/Update/Delete Relationship mutation is exactly one edge (§5); bulk relationship creation is the Bulk Operations path, bounded by the batch-size ceiling above. |
| Transaction timeout | Bounded by one server-side request-handling cycle — a transaction must never remain open pending additional caller input or a network round-trip | Architectural requirement (fail-closed, no held-open state); the concrete numeric timeout is an `emg-persistence` connection-configuration/deployment parameter, not fixed by this ADR. |
| Retry limits | Zero automatic server-side retries (§10.4); client retry count is not mandated by this ADR | Retry is a client decision; the architectural fix is that the server never silently retries on the caller's behalf. |
| Idempotency window | 24 hours, `Settings`-configurable (§8.3) | Consistent with this platform's existing configurable-TTL convention. |
| Expected latency | No numeric SLO fixed here (FEAT-12-4, Alerting & SLO/Error Budget, not yet started) | Architecturally, latency is bounded by one compare-and-set write plus the existing validation pipeline — the same order of magnitude as the existing single-snapshot read path; no new network hop is introduced. |
| Concurrency expectations | Low-to-moderate concurrent-write contention per tenant, consistent with the existing single-writer-per-tenant model (Freeze §11) | A workload requiring high-throughput concurrent writes to one tenant is out of scope and would require a future ADR revisiting the single-writer-per-tenant model itself (§17, risk item 2, unchanged). |

---

## 13. Sequence Diagram

End-to-end, entity creation as the representative case (update, delete,
restore, merge, reclassify, and batch operations follow the identical
layer order with a different command type and, for batch, the
one-batch-one-revision semantics of §11):

```
Client                HTTP API          PEP              Application        GraphStore        Outbox           Audit
  |                      |                |                   |                  |               |               |
  |--(1) mutation req -->|                |                   |                  |               |               |
  |   + idempotency key  |                |                   |                  |               |               |
  |                      |--(2) authenticate (401 on failure)-|                  |               |               |
  |                      |--(3) resolve tenant (401)----------|                  |               |               |
  |                      |--(4) idempotency lookup------------------------------>|               |               |
  |                      |                |                   |   [if found+unexpired: return    |               |
  |                      |                |                   |    stored receipt, STOP here]     |               |
  |                      |--(5) authorize(create, entity)---->|                   |               |               |
  |                      |                |--PolicyEngine.evaluate()-->          |               |               |
  |                      |                |<--Decision(outcome, policy_id)--------|               |               |
  |                      |<--deny: 403 PermissionDeniedError--|                   |               |               |
  |                      |   (audit "denied" emitted, no idempotency row written)|               |               |
  |                      |--(6) authorize(classification-propagation)---------->|               |               |
  |                      |                |--PolicyEngine.evaluate()-->          |               |               |
  |                      |                |<--Decision------------------------------|            |               |
  |                      |<--deny: 403----|                   |                  |               |               |
  |                      |--(7) construct + .validate() CreateEntityCommand------|               |               |
  |                      |   (400 InvalidMutationCommandError on failure, no transaction opened)  |               |
  |                      |--(8) ontology conformance validation (emg-ontology)---|               |               |
  |                      |--(9) command.execute() ----------->|                  |               |               |
  |                      |                |                   |--(10) transaction(tenant, principal)-->          |
  |                      |                |                   |        read() current snapshot   |               |
  |                      |                |                   |        construct via applicable MemoryGraphBuilder path |
  |                      |                |                   |        stage(new_graph)           |               |
  |                      |                |                   |--(11) commit ------------------->|               |
  |                      |                |                   |   [409 PersistenceConflictError   |               |
  |                      |                |                   |    on concurrent-write conflict]  |               |
  |                      |                |                   |<--WriteReceipt---------------------|               |
  |                      |                |                   |                  |--(12) append event-->|         |
  |                      |                |                   |                  |    idempotency_key = |         |
  |                      |                |                   |                  |    f"{tenant}:{rev}" |         |
  |                      |                |                   |--(13) write mutation_idempotency row-------------->|
  |                      |                |                   |--(14) emit domain event (entity.created)----------|
  |                      |                |                   |--(15) emit SubmittedAuditEvent--------------------->|
  |                      |                |                   |    (outcome=success, classification, policy_id)   |
  |<--(16) receipt-shaped response--------|                   |                  |               |               |
  |   (WriteReceipt fields + mutated id)  |                   |                  |               |               |
```

Steps 5–6 (authorization, classification) always precede step 10 (the
transaction opens) — a denied caller never causes a read-modify-write cycle
to begin, preserving fail-closed semantics identically to ADR-025/026's
existing read-path ordering. Step 4 (idempotency lookup) always precedes
steps 5–9, so a genuine replay never re-incurs authorization or validation
cost (§8.4/§8.5). Steps 12–15 (outbox, idempotency-row write, event, audit)
only ever occur after step 11 (transaction commit) succeeds (§8.6, §9.4)
— never before, and never for a rolled-back transaction.

For Create, the construction step may use the existing ontology conversion
path. Update, Retire, Restore, Reclassify, Merge, and relationship-validity
closure use only the additive ADR-029 construction path. ADR-027 does not
select or reproduce lower-level identity, lifecycle, supersession, or Merge
logic.

---

## 14. Migration Strategy

1. **Stage 0 — Mandatory prerequisites, both COMPLETE.**
   - **0.1 — GraphStore Protocol unification (§4.5): DEFERRED**, removed
     from this ADR's mandatory gate — see §4.7. Not required for Stage 1 or
     any later stage; tracked separately.
   - **0.2 — `svc-knowledge-graph-writer` role-catalog entry (§5):
     COMPLETE.** Added to `ROLE_CATALOG` and the Keycloak realm seed, with
     the catalog/realm-sync test passing.
   - **0.3 — `mutation_idempotency` table migration (§8.2): COMPLETE.**
     Added as an additive, schema-only Postgres migration in
     `emg-persistence`; no application code reads or writes it yet.

   Stage 0 is now complete in full: both items that actually gate Stage 1
   are done, and the one item that does not gate Stage 1 (GraphStore
   unification) has been explicitly removed from the gate rather than left
   blocking indefinitely.

### Stage 4 — HTTP/API Delivery Layer

1.  **Schema Negotiation (ADR-032):** The API layer negotiates the schema version before any command construction.
2.  **Authorization Preflight:** Before the `GraphStore` transaction, evaluate metadata via `IResourceMetadataReader`.
3.  **Application Metadata Interface:** Implement `IResourceMetadataReader` (Application Layer) to fetch resource metadata.
4.  **Transaction Execution:** The mutation is performed atomically using the `AtomicMutationExecutionPort` (ADR-030).
5.  **Audit/Ledger Mapping:** Map the ledger response to the public response envelope (ADR-030 Revision 4).
2. **ADR-029 implementation prerequisite.** Implement and independently
   validate ADR-029's approved additive `emg-memory-graph` contract before
   Stage 1 begins. ADR-027 does not absorb that implementation into Stage 1
   and does not provide a fallback when the prerequisite is unavailable.
3. **Stage 1 — Fine-grained commands in the application layer.** Add the
   new commands (`CreateEntityCommand`, `UpdateEntityCommand`,
   `RetireEntityCommand`, `RestoreEntityCommand`, `MergeEntityCommand`,
   `ReclassifyEntityCommand`, and the relationship/batch equivalents) to
   `emg_knowledge_graph/commands.py`, and the corresponding
   `KnowledgeGraphApplication` methods. All writes use
   `GraphStore.transaction()` exactly as `build_revision` does; graph
   construction uses the applicable ADR-029 builder operation rather than
   application-owned replacement or merge logic. Verifiable
   entirely by unit tests against the application layer, per ADR-024 §25's
   own precedent ("Phase 1 scope only: command models, validation, and
   safety limits"). The same stage adds the narrowly scoped current-view
   lifecycle eligibility mapping required by §9.6, using ADR-029's
   `LIVE_STATES` without altering ADR-024's query algorithms.
4. **Stage 2 — Authorization/classification policy data.** Author the new
   `resource_type`/`action` `PolicyRule` entries (§5) and the
   classification-propagation/ownership-override rules in
   `services/knowledge-graph/config/policy.example.yaml`, validated as
   policy data only, mirroring ADR-026's own Phase 1/Phase 2 split. (The
   `svc-knowledge-graph-writer` catalog entry itself is already done —
   Stage 0.2 — so this stage's remaining work is the policy rules only.)
5. **Stage 3 — Concurrency infrastructure wiring.** Wire the
   idempotency-lookup step (§13, step 4) against the already-migrated
   `mutation_idempotency` table (Stage 0.3, complete) — proven in isolation
   before any HTTP surface exists.
6. **Stage 4 — HTTP wiring.** Add the routes (§5's operation list),
   composing authentication → tenant resolution → idempotency lookup →
   operation authorization → classification propagation → command execution
   → outbox/idempotency-row write → event/audit emission → response, in
   that order (§13), mirroring ADR-025/026's existing composition order.
7. **Stage 5 — Deployment documentation and rollout.** Document the new
   role/policy-rule requirements, following the same "identity provisioning
   requirement" pattern ADR-026 §14/Part E already established.
8. **Rollback:** a pure code/config revert at any stage — no persisted
   state depends on this ADR's mechanism; every commit it produces is an
   ordinary revision, readable and diffable by the existing, unchanged
   read/history API regardless of whether the Mutation API is later
   disabled. The `mutation_idempotency` table, if rolled back, simply stops
   being consulted — it holds no state any other subsystem depends on.

`emg-knowledge-pipeline`'s Stage-0 rework (§4.5) was originally folded into
this migration sequence as the single most significant change this revision
made to the migration plan. It has since been **removed from the sequence
and deferred** (§4.7) after implementation attempts showed it required its
own reviewed design rather than a mechanical step within Stage 0 — see the
separate analysis document referenced in §4.7 for the full reasoning.

---

## 15. Failure Handling

### 15.1 Validation failures

Raised before any transaction opens, using a new
`InvalidMutationCommandError` (mirroring the existing
`InvalidRevisionCommandError`/`InvalidQueryError` naming convention),
mapped to HTTP 400. No partial write occurs; no audit event is emitted for
a request that never reached authorization.

### 15.2 Authorization failures

`PermissionDeniedError`, mapped to HTTP 403, identical to ADR-025's
convention. A `SubmittedAuditEvent` **is** emitted (`outcome="denied"`).

### 15.3 Concurrency

Per §10 — `PersistenceConflictError` mapped to HTTP 409; no automatic
server-side retry.

### 15.4 Partial failures

Impossible by construction for both single mutations and batches (§11.3) —
`GraphTransaction.stage()`/commit is atomic; either the entire staged
change commits or nothing does.

### 15.5 Retries

Safe by construction via idempotency (§8) for transient/network-failure
retries; a `ConflictError` is a genuine concurrent-change signal, not
silently retried by the server (§10.4).

### 15.6 Rollback strategy

No explicit rollback step beyond the transaction's own context-manager
semantics — identical to how `build_revision` already behaves when
`MemoryGraphBuilder` raises. No compensating-transaction or saga pattern,
because no mutation (or batch, §11) in this ADR spans more than one
transaction.

---

## 16. Alternatives Considered

**A. Expose `BuildRevisionCommand`/`build_revision` directly over HTTP as
the entire Mutation API.** Rejected as the sole mechanism — insufficient
authorization/concurrency granularity (§16 of the original draft,
unchanged reasoning). Retained internally as the underlying builder
mechanism fine-grained commands compose down to.

**B. Wire `emg-knowledge-pipeline` in directly, unreconciled, as the
synchronous mutation path.** Rejected — this is the option whose
unreviewed-adapter risk §4 now resolves definitively rather than deferring;
seeing it through would have required either silent port reconciliation or
an unreviewed bridge.

**C. Fine-grained commands against `emg_platform_core.ports.GraphStore`,
consuming ADR-029's `MemoryGraphBuilder` construction contract.**
**Selected.** The application owns orchestration; ADR-029 owns all
identity/lifecycle/supersession/Merge mechanics; the existing GraphStore
transaction remains the only write substrate.

**D. A dedicated, new `MutationStore` port distinct from `GraphStore`.**
Rejected — duplicates an already-sufficient port (§16 of the original
draft, unchanged reasoning).

**E. (New in this revision) Defer the GraphStore/authorization/idempotency/
concurrency decisions to implementation time, as the original draft did.**
Rejected by this revision itself, per the independent architecture review:
an ADR whose purpose is to make implementation mechanical cannot leave its
four highest-leverage decisions unmade — doing so reproduces exactly the
kind of undocumented, later-discovered drift this repository's own
governance register (D-A-001, D-A-002, the original GraphStore duplication
itself) already shows is costly to leave open.

---

## 17. Repository Impact

- **`libs/python/emg-knowledge-pipeline`** — **modified** (this revision
  corrects the original draft's "not modified" claim): gains
  `emg-memory-graph`/`emg-platform-core` dependencies; its own
  `graph_store.py` (Protocol + in-memory adapter) is deleted; internal
  construction switches to `MemoryGraphBuilder`/`MemoryNode.from_entity`.
- **`libs/python/emg-persistence`** — new additive migration for
  `mutation_idempotency` (§8.2); no change to `graph_revisions`/
  `graph_head`/`outbox`.
- **`services/knowledge-graph` (`emg_knowledge_graph`)** — new commands,
  new `KnowledgeGraphApplication` methods, new result DTOs, new typed
  errors (`InvalidMutationCommandError` and siblings). No change to any
  existing query method or the dependency-boundary test's governing
  invariant.
- **`services/knowledge-graph` (`emg_knowledge_graph_api`)** — new routes
  for every operation in §5's matrix; extension of the existing
  authorization/classification wiring to the new `resource_type`/`action`
  pairs and the ownership-override/classification-propagation checks;
  idempotency-lookup wiring.
- **`services/knowledge-graph/config/policy.example.yaml`** — new
  `PolicyRule` entries (data only) per §5.
- **`libs/python/emg-policy-engine/src/emg_policy_engine/roles.py`** — one
  new `ROLE_CATALOG` entry, `svc-knowledge-graph-writer` (data only).
- **New architecture-fitness test** (§4.5, item 6) —
  `test_only_one_graphstore_protocol_exists`, added alongside the existing
  dependency-boundary/no-scripting-capability test suites.
- **`libs/python/emg-auth-client`, `libs/python/emg-audit-client`** —
  likely none (both already carry every field this ADR's design needs).
- **`libs/python/emg-memory-graph`** — changed only by ADR-029's separately
  approved implementation prerequisite, not by ADR-027 Stage 1. ADR-027
  consumes the resulting contract and introduces no parallel construction,
  identity, lifecycle, supersession, or Merge mechanism.
- **`libs/python/emg-ontology`** — unchanged by ADR-027 and ADR-029.
- **`libs/python/emg-knowledge-lifecycle`** — unchanged; ADR-029 owns how
  `emg-memory-graph` consumes its canonical lifecycle primitives.
- **`libs/python/emg-trust-scoring`** — not modified; future wiring into
  `CreateEntityCommand`'s server-assigned trust-score resolution remains
  scoped at implementation time.
- **Documentation** — `ARCHITECTURE_STATUS.md`,
  `EMG_ARCHITECTURE_DECISION_REGISTER.md`, and
  `EMG_PRODUCTION_READINESS_ROADMAP.md` require an update once any stage
  is implemented.

---

## 18. Risks

1. **GraphStore Protocol unification (§4.5) has been deferred, not
   eliminated** — the two-Protocol duplication this ADR's §4 analysis
   identified still exists in the repository after Stage 0's completion.
   This is a disclosed, deliberate scope boundary (§4.7), not a dropped
   requirement: the duplication is a maintainability/CI-fitness risk, not a
   correctness or security defect, and no code this ADR introduces depends
   on it being resolved. It remains open, tracked debt for a future,
   separately-reviewed change.
2. **Revision-per-mutation/per-batch granularity at scale** (unchanged from
   the original draft) — a write-heavy tenant will still drive compare-and-set
   contention; batching (§11) mitigates but does not eliminate this.
3. **`svc-knowledge-graph-writer` has no registered concrete consumer yet**
   — it is added in anticipation of a future ADR-020 ingestion service;
   until one exists and is registered (ADR-025 §18's still-open
   client-registry allow-list gap), this role exists as vocabulary only,
   consistent with how other roles were catalogued ahead of their first
   concrete grantee.
4. **ADR-029 is approved but not implemented.** Stage 1 remains blocked
   until ADR-029's additive memory-graph contract is implemented and
   independently validated. ADR-027 provides no substitute mechanism.
5. **Client-registry allow-list gap (ADR-025 §18/OBS-A-003) now gates a
   write surface** — unchanged in substance from the original draft,
   still recommended as a pre-production-grant priority, still not this
   ADR's own scope to resolve.

---

## 19. Future ADR Dependencies

- **ADR-020 (Knowledge Ingestion Layer)** — has a concrete `GraphStore`
  contract (§4) and a defined batch atomicity model (§11) to build against.
  Note the unification of `emg-knowledge-pipeline`'s own separate
  `GraphStore` Protocol with this contract is deferred (§4.7); a future
  ADR-020 should either build directly against
  `emg_platform_core.ports.graph_store` (recommended, avoiding the
  duplication entirely for new code) or explicitly account for the
  still-open duplication if it builds on `emg-knowledge-pipeline`.
- **ADR-021 (Enterprise API Strategy)** — the reserved `If-Match`-style
  caller-supplied concurrency precondition (§10.2) is a candidate for that
  ADR's REST-conventions scope, not this one.
- **A future physical-erasure ADR** (§9.4) — separate, higher-stakes, not
  designed here.
- **A future "classification authority" ADR** (§5.1, Reclassify row) — if
  a narrower reclassification-approval concept beyond simple role-gating
  is ever needed, per Appendix ADR-026A principle 3.
- **ADR-028 (Audit reconciliation)** — must account for mutation-sourced
  audit events (§9.4, §13) alongside read-path and operation-level events.

---

## 20. Final Architecture Consistency Report

Consistency confirmed against each named reference:

- **ADR-022 (Revision Build Workflow):** unchanged — this ADR's every
  commit still produces exactly one immutable revision via the same
  builder/transaction mechanism ADR-022 established.
- **ADR-023 (Revision History & Navigation):** unchanged — `WriteReceipt`'s
  `revision_number`/`committed_at`/`revision_created` fields (ADR-023's own
  addition) are reused verbatim by every new mutation command's result
  shape (§13, step 16); no history/navigation read path is altered.
- **ADR-024 (Query Engine):** consistent — traversal, pagination, cursor,
  temporal-axis, and revision-selection semantics are unchanged. §9.6 adds
  only the lifecycle eligibility mapping ADR-029 explicitly assigns to
  ADR-027 Revision 3.
- **ADR-025 (Tenant & Authorization Model):** consistent — every new
  mutation route follows the identical authenticate → resolve-tenant →
  authorize composition order (§13), through the same
  `PolicyEnforcementPoint`, with no new trust path.
- **ADR-026 Revision 2 (Classification Enforcement Model):** consistent —
  classification propagation (§5) is the write-side mirror of ADR-026's
  read-side gate, using the identical `required_resource_attributes`
  mechanism, never a second classification concept; Appendix ADR-026A's
  three governing principles (declarative-only, symmetric mechanism,
  independent-ADR-per-new-concept) are explicitly honored at §5.1's
  Reclassify row and §19.
- **ADR-029 (Canonical Identity, Lifecycle, and Supersession):**
  consistent — §9 delegates the complete identity, lifecycle,
  supersession, relationship-validity closure, and graph-level Merge model
  to ADR-029. This ADR retains only Mutation API orchestration,
  authorization, audit, idempotency, and transaction responsibilities. It
  defines no competing field, transition, back-reference, merge algorithm,
  or replacement path.
- **Repository Governance:** consistent — `check_dependency_manifest.py`/
  `check_dependency_drift.py`/`check_implicit_dependencies.py` apply
  unchanged to every package this ADR touches; §4.5 adds a new
  architecture-fitness test rather than weakening any existing one.
- **Dependency Direction:** consistent — the one new dependency edge this
  ADR introduces (`emg-knowledge-pipeline` → `emg-memory-graph`/
  `emg-platform-core`, §4.5) is non-circular and flows in the same
  direction every other library-to-foundation dependency already flows;
  `emg_knowledge_graph` (domain layer) still imports neither
  `emg_auth_client` nor `emg_policy_engine`.
- **Security Model:** consistent — fail-closed preserved at every failure
  mode (§15); classification and authorization checks always precede
  transaction opening (§13); idempotency replay never bypasses
  authorization for a first-time request, only for an already-decided one
  (§8.4); ownership-override (§5.2) is expressed through the existing
  mechanism, not a new one.
- **Architecture Principles (§ of this document, unchanged from the
  original draft):** dependency direction, `PolicyEngine`/PEP identity,
  ADR-026 preservation, repository governance, and fail-closed security are
  all restated as satisfied by every section above, not merely asserted.

No inconsistency was found against ADR-022, ADR-023, ADR-026, or ADR-029.
Revision 3's substantive change is an ownership correction: domain mutation
mechanics previously duplicated in ADR-027 are removed and referenced to
ADR-029.

---

## 21. Final Readiness Assessment

**Architecture Readiness: Ready for Revision 3 review.** ADR-027 now owns
only the Mutation API decisions in its scope. ADR-029 is the sole authority
for identity, lifecycle, supersession, relationship-validity closure, and
graph-level Merge.

**Implementation Readiness: Gated.** Stage 0 is complete, but Stage 1 must
not begin until approved ADR-029 is implemented and independently validated.
GraphStore Protocol unification (§4.5) remains formally deferred (§4.7) and
is not this gate.

**Security Readiness: Ready.** Fail-closed is preserved at every failure
mode (§15); the authorization matrix (§5) leaves no mutation operation's
permission, clearance, or identity rule unspecified; idempotency replay
cannot be used to bypass a first-time authorization decision (§8.4); the
ownership-override and reclassification-authority boundaries are drawn
precisely, with the latter's narrower future form explicitly reserved
under Appendix ADR-026A rather than invented ad hoc.

**Repository Readiness: Ready, with one disclosed cost.** The
`emg-knowledge-pipeline` dependency change (§4.5) is a real, non-trivial
piece of migration work with its own review surface — larger than the
original draft's "not modified" claim implied, but necessary to eliminate
drift rather than manage it.

**Remaining Risks:** §18, items 1–5 — none reopen the decisions in this ADR; all
are either a disclosed, deliberate deferral (item 1 — GraphStore
unification, tracked separately per §4.7), pre-existing, already-tracked
platform risks this ADR does not worsen (items 2, 5), or ordinary
implementation follow-through (items 3, 4).

**Implementation Recommendation:** Proceed in the exact stage order §14
defines. Stage 0 is complete; implement and validate ADR-029 next; only then
begin Stage 1 as its own independently-reviewed change. GraphStore unification
(§4.5), when it is eventually undertaken, should likewise be its own
standalone, independently-reviewed change — not bundled into Stage 1 or any
other stage's review — so it receives attention proportionate to its blast
radius (§4.4, "wider than a Knowledge-Graph-local change") whenever it is
taken up.

### Final Decision

**REVISION 3 READY FOR BOARD REVIEW. Stage 0 complete; Stage 1 gated by
ADR-029 implementation (2026-07-28).**

The Mutation API architecture is internally consistent. Its prerequisite
status is:

1. The `svc-knowledge-graph-writer` role-catalog entry (§5) — **COMPLETE.**
   Added to `ROLE_CATALOG` and the Keycloak realm seed.
2. The `mutation_idempotency` table migration (§8.2) — **COMPLETE.** Added
   as an additive, schema-only Postgres migration.
3. GraphStore Protocol unification (§4.5) — **DEFERRED**, removed from
   this ADR's mandatory gate per §4.7. Confirmed (§4.4) not to be a
   dependency of Stage 1 or any later stage; tracked as separate,
   independently-reviewable future work via
   `docs/architecture/EMG_ADR-027_STAGE_0_1_GRAPHSTORE_UNIFICATION_ANALYSIS.md`.
4. ADR-029 — **APPROVED, IMPLEMENTATION REQUIRED BEFORE STAGE 1.** ADR-029
   is the exclusive domain-model authority consumed by §9.

Stage 0 is complete. Stage 1 may proceed only after item 4 is implemented
and independently validated.

---

## 22. Compliance Checklist

- [x] Repository-driven: every mechanism named already exists or is the
      smallest additive extension of something that already exists.
- [x] `emg-policy-engine` remains the platform's single authorization
      mechanism — no second engine introduced.
- [x] `PolicyEnforcementPoint` contract unchanged.
- [x] ADR-026's classification enforcement model and evaluation order are
      preserved and mirrored, not redesigned.
- [x] `emg_knowledge_graph`'s dependency-boundary invariant is preserved.
- [x] Fail-closed preserved at every failure mode.
- [x] No scripting/expression language or ranking/dominance comparator
      introduced anywhere.
- [x] Repository governance unaffected in kind; one new architecture-fitness
      test added (§4.5), no existing check weakened.
- [ ] The two-`GraphStore`-Protocol drift is eliminated — **deferred, not
      done** (§4.7); explicitly scoped out of this ADR's implementation
      gate and tracked as separate future work. Confirmed not to be a
      dependency of any stage this ADR implements.
- [x] Every mutation operation's authorization is fully specified (§5) —
      none deferred.
- [x] Idempotency (§8) and concurrency (§10) each have one authoritative,
      fully-specified mechanism.
- [x] Batch mutation atomicity is fully specified by §11.
- [x] Identity, lifecycle, supersession, relationship-validity closure, and
      graph-level Merge are not duplicated; §9 consumes ADR-029 exclusively.
- [x] Operational constraints (§12) are fixed as architectural ceilings.
- [x] Search, GraphRAG, AI Orchestration, Decision Intelligence, audit
      reconciliation (ADR-028), and physical erasure explicitly out of
      scope.
- [x] No code was written or modified to produce this ADR.

---

## 23. Architecture Dependency Matrix

| Concern | Authoritative ADR | ADR-027 responsibility | Dependency effect |
| --- | --- | --- | --- |
| Immutable graph revision construction and commit | ADR-022 | Invoke one `GraphStore.transaction()` and stage one immutable snapshot | Preserved; no alternate commit path |
| Revision numbering, receipts, history, diff, and whole-revision restore | ADR-023 | Return committed receipt data; keep entity Restore distinct from revision Restore | Preserved; no history mutation |
| Authorization and classification enforcement | ADR-026 (with ADR-025) | Define mutation actions, policy data, ordering, and fail-closed HTTP composition | Preserved; no comparator or second engine |
| Entity/relationship identity | ADR-029 | Supply command intent and consume the resulting replacement | Required prerequisite; no local identity rule |
| Lifecycle and supersession | ADR-029 | Authorize and orchestrate the requested operation | Required prerequisite; no local transition or back-reference |
| Current-view lifecycle eligibility | ADR-029 (`LIVE_STATES`); ADR-027 §9.6 integration | Apply the canonical eligibility predicate at the application result boundary | ADR-024 algorithms and ADR-023 historical snapshots remain unchanged |
| Relationship validity closure | ADR-029 | Invoke closure for relationship Retire and incident edges during entity Retire/Merge | Required prerequisite; no use of `active_edges_at` as a mutator |
| Graph-level Merge | ADR-029 | Authorize, transact, audit, and return the result | Required prerequisite; no `EntityResolver` execution |
| Idempotency and concurrency | ADR-027, using ADR-022/023 storage contracts | Own replay, key scope, and conflict behavior | Unchanged |
| Audit reconciliation | ADR-028 (future) | Define mutation audit intent only | Deferred production-enablement dependency |

---

## 24. Changelog

### Revision 3 — 2026-07-28

- Added approved ADR-029 as an explicit prerequisite and authoritative
  dependency.
- Removed ADR-027's duplicated lifecycle state machine and operation-to-state
  definitions.
- Removed the obsolete assumption that `EntityResolver` executes graph-level
  Merge.
- Removed the obsolete assumption that `active_edges_at` closes stored
  relationship validity.
- Delegated entity/relationship identity, lifecycle, supersession,
  relationship endpoint/validity behavior, Merge field combination,
  collision handling, and immutable replacement construction exclusively to
  ADR-029.
- Preserved ADR-027 ownership of authorization, idempotency, concurrency,
  batching, transaction orchestration, audit intent, HTTP sequencing, and
  operational constraints.
- Distinguished ADR-027 “Restore Entity” from ADR-023 whole-revision restore.
- Added the ADR-029-required current-view lifecycle eligibility integration
  while preserving ADR-024 query algorithms and ADR-023 historical reads.
- Added the Architecture Dependency Matrix and updated the final consistency
  and readiness assessments.
- Gated Stage 1 on implementation and independent validation of ADR-029.

### Revision 2 — 2026-07-27

- Settled GraphStore direction, mutation authorization, idempotency,
  concurrency, batch semantics, and operational constraints.
- Completed Stage 0 role-catalog and idempotency-schema prerequisites.
- Deferred GraphStore Protocol unification to its separately reviewed
  analysis.
