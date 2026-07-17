# emg-semantic-layer

**Semantic Layer** for Module 7 (Enterprise Knowledge Graph Platform) — EPIC-05,
**FEAT-05-4**, added Sprint 12.

Part of the EMG™ shared-libraries workspace (Module 3, ADR-012), delivered
**library-first**, **storage-independent**, and **deterministic**: it defines an
immutable query / traversal / projection model and a single storage-binding
extension point that decouples every knowledge consumer (Search, GraphRAG, AI,
Decision, Presentation) from the underlying persistence technology (Architecture
Baseline, *Storage-technology independence*; Module 7 §10).

It **defines semantics only — it executes nothing.** There is **no persistence,
no database driver, no networking, no Neo4j, no retrieval, no embeddings, no AI,
no REST API, and no UI**.

## What this is

- **Graph value objects** (`graph.py`): `SemanticNode`, `SemanticRelationship`,
  and `SemanticGraph` — immutable, storage-independent projections of a
  materialised subgraph, with pure lookup helpers (`node`, `relationships_of`,
  `neighbors`). Node/relationship types are plain labels and properties are plain
  scalars, so this layer does not depend on the ontology's concrete classes.
- **Closed enums** (`enums.py`): `TraversalDirection`, `FilterOperator`,
  `BooleanOperator`, `SortDirection` — every operator/direction is a fixed
  vocabulary member, never a caller string, callable, or expression.
- **Filtering** (`filters.py`): `FilterCondition` (a leaf `field op value`
  predicate) combined by `SemanticFilter` (a bounded, recursive boolean
  expression). Pure data — no callables, no raw query fragments.
- **Query model** (`query.py`): `NodeSelector` (entity lookup), `TraversalStep`
  / `SemanticTraversal` (bounded relationship traversal), `SemanticProjection`,
  `SortKey` / `SemanticOrdering`, `Pagination`, and the composed `SemanticQuery`
  — all frozen and self-validating.
- **Planner** (`planner.py`): `plan(query)` compiles a query into an immutable,
  deterministic `SemanticPlan` (canonical step order:
  `SELECT → TRAVERSE → FILTER → ORDER → PAGINATE → PROJECT`) — the execution
  *semantics*, without executing.
- **Result model** (`result.py`): `SemanticResult` + `PageInfo` — the immutable
  output shape every conforming executor returns.
- **Extension point** (`execution.py`): the `SemanticQueryExecutor` protocol —
  the *only* integration seam. A future storage binding implements it; this
  library implements nothing.

## What this is not

- **Not a database, driver, client, or connection.** It holds no data and does
  no I/O. `SemanticGraph` is an in-memory frozen value object, not a store.
- **Not Neo4j, retrieval, embeddings, AI, an LLM integration, a REST API, or a
  UI** — and it is **not wired** into the knowledge pipeline or trust-scoring
  runtime. Those integrate only through `SemanticQueryExecutor`.
- **Not lifecycle management** (FEAT-05-5).

## Bounds & security

- Query models are **frozen** and **validated at construction**; a malformed
  query is rejected immediately (field/structure errors as
  `pydantic.ValidationError`, cross-model semantic errors as
  `SemanticQueryError`).
- **Bounded by construction — in size, not only depth:** traversal depth ≤
  `MAX_TRAVERSAL_DEPTH`, page limit within `[MIN_PAGE_LIMIT, MAX_PAGE_LIMIT]`,
  page offset ≤ `MAX_PAGE_OFFSET`, relationship-type fan-out ≤
  `MAX_RELATIONSHIP_TYPES_PER_STEP`, filter nesting ≤ `MAX_FILTER_DEPTH`, filter
  width ≤ `MAX_FILTER_CONDITIONS` / `MAX_FILTER_GROUPS`, selector ids ≤
  `MAX_SELECTOR_IDS`, projection fields ≤ `MAX_PROJECTION_FIELDS`, ordering keys ≤
  `MAX_ORDERING_KEYS`. An unbounded selection, page, deep offset, or oversized
  collection is not expressible.
- **No arbitrary code / no injection surface:** operators are closed enums,
  values are plain scalars, and every identifier/label (ids, type names,
  relationship-type names, filter/projection/ordering fields, property keys) is
  validated by `ensure_safe_label` — empty/whitespace-only strings and any NUL,
  ASCII control, CR/LF, or Unicode bidi override/control character are rejected
  (legitimate Unicode preserved). Nothing is `eval`'d; a binding must map
  operators onto its own *parameterised* query API.
- **Deeply immutable:** models are frozen, **and** `SemanticNode` /
  `SemanticRelationship` `properties` is a read-only mapping over a private copy
  — a caller cannot mutate a returned node's properties or mutate the dict it
  passed in after construction.
- **Deterministic:** `plan()` is pure — identical queries yield an identical
  plan; `SemanticOrdering` defines a total, unambiguous order.

## Planner: a canonical step-order plan, not an executable form

`plan()` returns the deterministic **canonical order** of stages
(`SELECT → TRAVERSE → FILTER → ORDER → PAGINATE → PROJECT`). A `PlanStep` carries a
machine-consumable `kind` and a **human-readable `detail` string only** — an
executor reads operational parameters from the structured `SemanticQuery`, never
by parsing `detail`. `SemanticPlan` is not a complete executable representation.

## Input vs. output

`SemanticQuery` (and its parts) are caller-supplied **inputs**. `SemanticResult`
and `PageInfo` are executor **outputs** — frozen DTOs that are constructable in
Python but must be obtained from a `SemanticQueryExecutor`, never hand-fabricated
in place of a real query result (they are still internally consistency-checked).

## Usage

```python
from emg_semantic_layer import (
    NodeSelector, SemanticQuery, SemanticTraversal, TraversalStep,
    SemanticFilter, FilterCondition, FilterOperator, TraversalDirection,
    SemanticProjection, SemanticOrdering, SortKey, Pagination, plan,
)

query = SemanticQuery(
    selector=NodeSelector(type="Person"),
    traversal=SemanticTraversal(steps=(
        TraversalStep(direction=TraversalDirection.OUTGOING,
                      relationship_types=("WORKS_FOR",), target_type="Organization"),
    )),
    filter=SemanticFilter(conditions=(
        FilterCondition(field="status", operator=FilterOperator.EQ, value="active"),
    )),
    projection=SemanticProjection(fields=("name", "title")),
    ordering=SemanticOrdering(keys=(SortKey(field="name"),)),
    pagination=Pagination(limit=50, offset=0),
)

# Deterministic canonical step-order plan — no database, executes nothing:
for step in plan(query).steps:
    print(step.index, step.kind.value, "-", step.detail)
```
