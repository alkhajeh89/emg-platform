# Sprint 12 Design — Semantic Layer (FEAT-05-4)

Reference: Engineering Backlog v1.0 §3 (FEAT-05-4 — "Semantic Layer:
Storage-independent query/traversal abstraction"), §6 row 9, §8 (8 story points);
Architecture Baseline (*Storage-technology independence* — "The Semantic Layer
(Module 7, §10) decouples every consumer — Search, GraphRAG, AI, Decision,
Presentation — from the underlying persistence technology, allowing that
technology to be selected, scaled, or replaced without architectural rework");
Master Plan §Technology table (Neo4j is the *concrete* store behind the Module 7
§10 storage-independent contract). Builds on FEAT-05-1 (`emg-ontology`); does not
depend on FEAT-05-2 or FEAT-05-3.

## Scope

Sprint 12 implements **FEAT-05-4 only**, delivered **library-first** as
`libs/python/emg-semantic-layer`: a **storage-independent, deterministic**
query / traversal / projection model plus a single storage-binding extension
point. It **defines semantics only — it executes nothing.**

Out of scope (deferred / excluded): the concrete **Neo4j** binding, **FEAT-05-5**
(lifecycle & versioning), and all retrieval, graph-database integration,
embeddings, AI, LLM integration, REST API, and UI. No persistence, no database
driver, no networking, no storage coupling. The engine is **not wired** into any
service, the knowledge pipeline, or the trust-scoring runtime.
`services/knowledge-graph` remains scaffolded.

## Architecture

Library-first and pure. The layer depends only on `emg-common-types` (the
platform `Classification` label vocabulary) and `emg-errors` (the shared
`ValidationError` base) — **not** on `emg-ontology`, `emg-knowledge-pipeline`, or
`emg-trust-scoring`, so the dependency direction stays clean and the layer is
reusable by any consumer. Node/relationship *types* are plain string labels and
properties are plain scalars, so the Semantic Layer neither depends on nor
re-implements the ontology's concrete classes; a storage binding maps ontology
entities onto these projections.

**Integration happens only through one extension point.** A future storage
binding (a Neo4j adapter, an in-memory test double, a federated backend)
implements the `SemanticQueryExecutor` protocol to actually run a query. This
library implements nothing, connects to nothing, and imports no driver or network
client. `plan()` is provided so a binding can obtain the validated, canonical
**step order** without re-deriving it.

## Two seams: `GraphStore` (FEAT-05-2) vs. `SemanticQueryExecutor` (FEAT-05-4)

Module 7 now has two storage-independent contracts, and they are deliberately
**separate, complementary concerns** — not duplicates:

- **`emg_knowledge_pipeline.GraphStore` / `GraphTransaction` (FEAT-05-2)** owns
  **persistence primitives**: append-only writes and point reads by id
  (`has_entity`, `get_entity`, `has_relationship`, `get_relationship`, `begin`),
  operating on `emg-ontology` `Entity`/`Relationship`. It is the *system-of-record
  write/read* contract used by the ingestion pipeline.
- **`emg_semantic_layer.SemanticQueryExecutor` (FEAT-05-4)** owns **query and
  traversal execution semantics**: given a validated, bounded `SemanticQuery`
  (multi-node selection, bounded traversal, filtering, projection, ordering,
  pagination), return a storage-independent `SemanticResult`. This is a *read
  query* contract, a fundamentally different shape from `GraphStore`'s
  id-addressed point reads — which is why it is a new seam rather than an
  extension of `GraphStore`.

**Why not extend `GraphStore`?** `GraphStore`'s read side is intentionally minimal
(by-id lookup, to support idempotent/atomic ingestion). Query and traversal are a
different capability with different bounds and a different result shape; bolting
them onto the persistence contract would overload FEAT-05-2's append-only
system-of-record role. Keeping the query contract separate also lets non-pipeline
consumers (Search, GraphRAG, Decision, Presentation) depend on the query seam
without depending on the write/ingestion contract.

**How they compose (future work, not this sprint).** A single storage adapter
(e.g. a Neo4j binding) may implement **both** contracts — `GraphStore` for
ingestion writes/reads and `SemanticQueryExecutor` for queries — over the same
underlying store, or the two may be implemented by separate adapters that share a
connection. That composition, and the concrete binding, are **deferred**: **no
Neo4j binding is implemented in Sprint 12**, and the Semantic Layer introduces
**no dependency on `emg-knowledge-pipeline`** (it must not — dependency direction
stays clean, and the query seam is reusable independently of ingestion).

**Ontology-to-semantic adapter: intentionally deferred.** `SemanticNode` /
`SemanticRelationship` are storage-independent *projections* (plain labels +
scalar properties), deliberately decoupled from `emg-ontology`'s concrete
`Entity`/`Relationship` classes. A helper that maps an ontology `Entity` onto a
`SemanticNode` (analogous to `signals_from_entity` in FEAT-05-3) would live at the
boundary where a storage binding materialises results — i.e. **with the binding**,
not in this abstraction. The frozen Backlog's FEAT-05-4 line ("storage-independent
query/traversal *abstraction*") does not require it, so it is **intentionally
deferred** to the binding sprint rather than added here as an unscoped
improvement.

## Semantic Layer architecture

```
                         INPUT (caller-supplied, immutable, self-validating)
SemanticQuery
  ├─ NodeSelector          entity lookup: ids / type / filter  (unbounded selection rejected)
  ├─ SemanticTraversal     ordered TraversalStep hops; depth <= MAX_TRAVERSAL_DEPTH
  │    └─ TraversalStep    direction (OUTGOING/INCOMING/BOTH) + relationship types + target
  ├─ SemanticFilter        bounded recursive boolean tree (depth & width capped); closed-enum ops
  ├─ SemanticProjection    which fields/relationships to return (field count capped)
  ├─ SemanticOrdering      total, deterministic sort keys (key count capped)
  └─ Pagination            bounded window: limit in [MIN,MAX], offset in [0, MAX_PAGE_OFFSET]
        │
        ▼   plan()  — pure, deterministic; executes nothing
   SemanticPlan  = ordered PlanSteps in the fixed canonical order:
        SELECT -> TRAVERSE (one per hop) -> FILTER -> ORDER -> PAGINATE -> PROJECT
        │
        ▼   SemanticQueryExecutor.execute(query)   ← the ONLY integration seam
            (implemented by a future storage binding; NOT in this library)
        │
        ▼   OUTPUT (executor-produced, immutable)
   SemanticResult = SemanticGraph (SemanticNode[] + SemanticRelationship[]) + PageInfo

   SemanticGraph — storage-independent value object with pure lookup helpers
                   (node, relationships_of, neighbors); NOT a store.
```

## Key decisions

- **Storage independence.** The query model describes *what* to return, never
  *how* to fetch it; the same query is valid against any backend. The layer holds
  no data and does no I/O — `SemanticGraph` is an in-memory frozen value object,
  not a persistence engine.
- **Single extension point.** All integration is via the `SemanticQueryExecutor`
  protocol (structural, so bindings need not import/subclass anything beyond the
  query/result types). Defining it as the *only* seam keeps the layer free of any
  backend dependency and satisfies "integrate only through abstractions".
- **Deterministic canonical step order (not an executable plan).** `plan()`
  compiles a query into a fixed **canonical stage order** so results are
  reproducible across backends; identical queries produce byte-identical plans.
  A `PlanStep` carries a machine-consumable `kind` and a **human-readable
  `detail` string only** — a binding reads operational parameters from the
  structured `SemanticQuery`, never by parsing `detail`; `SemanticPlan` is not a
  complete executable representation. `SemanticOrdering` defines a total,
  unambiguous order (distinct sort fields required).
- **Bounded by construction — in size, not only depth.** Every user-controlled
  quantity is capped at model construction: traversal depth
  (`MAX_TRAVERSAL_DEPTH`), page limit (`[MIN_PAGE_LIMIT, MAX_PAGE_LIMIT]`), **page
  offset (`MAX_PAGE_OFFSET`)**, relationship-type fan-out
  (`MAX_RELATIONSHIP_TYPES_PER_STEP`), filter nesting (`MAX_FILTER_DEPTH`),
  **filter width (`MAX_FILTER_CONDITIONS`, `MAX_FILTER_GROUPS`)**, **selector-id
  count (`MAX_SELECTOR_IDS`)**, **projection-field count
  (`MAX_PROJECTION_FIELDS`)**, and **ordering-key count (`MAX_ORDERING_KEYS`)**.
  An unbounded selection, an unbounded page, an arbitrarily deep offset, or an
  oversized collection is not expressible.
- **No arbitrary code / no injection surface.** Operators and directions are
  closed enums; values are plain scalars; and every identifier/label (ids, type
  names, relationship-type names, filter/projection/ordering field names, and
  property keys) is validated by `ensure_safe_label`, which rejects empty/
  whitespace-only strings and any NUL, ASCII control, CR/LF, or Unicode bidi
  override/control character (legitimate Unicode is preserved). There is no
  free-form operator string, no raw query fragment, and no callable — so a query
  carries no injection payload. Bindings must map operators onto a *parameterised*
  backend API.
- **Deep immutability.** Every query, plan, graph, and result model is frozen with
  `extra="forbid"`, **and** `properties` on `SemanticNode`/`SemanticRelationship`
  is stored as a read-only `MappingProxyType` over a private copy — so a caller
  can neither reassign a field, mutate a returned node's properties, nor mutate
  the dict it passed in after construction. Malformed input is rejected at
  construction (`pydantic.ValidationError`); cross-model semantic violations raise
  the typed `SemanticQueryError` (an `emg_errors.ValidationError` subclass).
- **Input vs. output boundary.** `SemanticQuery` (and its parts) are inputs;
  `SemanticResult` / `PageInfo` are executor outputs — frozen DTOs that must be
  obtained from a `SemanticQueryExecutor`, never hand-fabricated in place of a
  real result (they remain constructable in Python; this is the documented trust
  boundary, and they are still internally consistency-checked).

## Security

- Deeply immutable, self-validating query models; malformed queries rejected at
  construction.
- Bounded traversal depth, page limit **and offset**, fan-out, filter nesting
  **and width**, selector-id/projection/ordering counts — no unbounded scan,
  page, deep offset, or oversized collection is expressible.
- Closed-enum operators + scalar values + `ensure_safe_label` on every identifier
  — no arbitrary code execution and no injection surface (including no
  control/bidi-spoofed identifiers); a binding must parameterise.
- Deterministic, reproducible canonical step order (`plan()` is pure).
- Data-access authorization (classification / need-to-know, Module 7 §21) is
  **out of scope** here — enforced by the consuming service and the storage
  binding. Documented in `security-limitations.md`.

## Testing

See `testing-strategy.md` (Sprint 12 section): graph value objects + lookups,
filter operand and nesting-bound validation, selector/traversal/projection/
ordering/pagination validation and immutability, planner canonical order +
determinism + conditional steps + a defensive over-depth rejection, result
consistency, the executor protocol (structural, via a test double), and security
(no arbitrary code / no injection surface, bounded traversal, malformed-query
rejection, immutability, determinism) — plus the Module 6 golden audit-hash and
Sprint 9 golden ontology descriptor regressions unchanged and the full Sprint
1–11 suite.
