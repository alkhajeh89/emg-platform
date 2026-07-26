# ADR-024 — Knowledge Graph Query Engine — Application-Layer Read Architecture

## 1. Title

Knowledge Graph Query Engine — Application-Layer Read Architecture (Sprint 7.3)

## 2. Status

**Proposed.** Implementation may begin only after architecture approval, following the
same governance pattern ADR-022 and ADR-023 established for Sprints 7.1 and 7.2.

**Date:** 2026-07-26
**Deciders:** Product / Architecture (EMG Platform)
**Supersedes:** none
**Related:** ADR-022 (Knowledge Graph Revision Build Workflow), ADR-023 (Knowledge
Graph Revision History & Navigation), Module 7 (FEAT-05-2, FEAT-05-6),
`PHASE2_ARCHITECTURE.md`, `docs/engineering/memory-graph-architecture.md`

## 3. Context

Sprint 7.1 (ADR-022) implemented `KnowledgeGraphApplication.build_revision()`.
Sprint 7.2 (ADR-023) implemented `list_revisions`, `read_revision`,
`compare_revisions`, and `restore_revision`, and settled the entire revision-history
architecture: `GraphRevisionReader` as a separate read-only port, `RevisionMetadata`/
`HistoricalGraphRevision` as the canonical persistence-independent revision shapes,
`WriteReceipt` extended with `revision_number`/`committed_at`/`revision_created`, and
the exact restore sequence. **None of that is reopened here.** ADR-023's decisions are
treated as repository fact, not proposal, for the remainder of this document.

A read-only architecture discovery for Sprint 7.3 (Knowledge Graph Query Engine)
established the following as repository fact:

- `MemoryGraph` (`libs/python/emg-memory-graph/src/emg_memory_graph/graph.py`) already
  provides O(1) `node(id)`/`edge(id)`/`has_node`/`has_edge` lookup, O(deg)
  `out_edges`/`in_edges`/`incident_edges`/`neighbors`, O(N) `nodes_of_type`, and
  deterministic iteration (both field validators reject duplicate ids and sort by id;
  every adjacency accessor re-sorts by `edge_id`).
- `MemoryQueryEngine` (`emg_memory_graph/query.py`) already implements a general
  edge-type/target-type-filtered neighbor primitive (`_related`, backing
  `who_approved`/`meetings_discussing`/`participants`/etc.) and a BFS
  `shortest_path(from_id, to_id) -> PathResult | None`, O(N+E), deterministically
  ordered.
- `temporal_query.py` already implements `node_exists_at`, `active_edges_at`,
  `subgraph_as_of`, `neighbors_at`, and `attribute_at` — every "valid at time T"
  primitive this sprint needs, as pure functions over a `MemoryGraph`.
- `MemoryEdge`'s own model validator rejects self-loops outright
  (`source_id == target_id` raises `ValueError`); edge identity is content-addressed
  from `(edge_type, source_id, target_id)`, so two edges of the *same* type between
  the same two nodes collide onto one `edge_id` — parallel edges between one node
  pair are only possible when their `edge_type` differs.
- `GraphStore`/`GraphRevisionReader`/`RevisionMetadata`/`HistoricalGraphRevision`
  (all `emg_platform_core.ports`) are unchanged since ADR-023 and were re-verified
  against the current working tree during this discovery.
- `PostgresNeo4jGraphStore.read()` (`emg-persistence/store.py`) is the only place
  Neo4j is wired into a read path: it prefers the Neo4j projection with read-repair,
  falling back to authoritative PostgreSQL on any `PersistenceError`, for the
  **current head only**. `list_revisions`/`read_revision` never touch Neo4j at all —
  they are pure PostgreSQL. `ProjectionWorker` is explicitly documented as "never
  started by `GraphStore.write()`" — projection lag versus PostgreSQL is real and
  operator/CI-driven, not synchronous with writes.
- `KnowledgeGraphApplication` (`services/knowledge-graph/src/emg_knowledge_graph/service.py`)
  today exposes only whole-graph, revision-shaped operations
  (`build_revision`/`list_revisions`/`get_revision`/`compare_revisions`/`restore_revision`).
  It has no entity/edge/neighbor/path query method. Its dependency-boundary test
  (`test_dependency_boundary.py`) already forbids the package from importing
  `emg_persistence`/`emg_knowledge_pipeline.graph_store` directly and from declaring
  classes named `Node`/`Edge`/`Graph`/`GraphStore`/`GraphRevisionReader`/`Revision`/
  `Projection`/`Version`/`Evidence`/`Lineage`.
- No index or matching helper for free-text search exists anywhere in the domain or
  platform layers. No timestamp-based ("as of wall-clock time T") historical-revision
  lookup exists anywhere — ADR-023 §15 explicitly rejected an `as_of` field on
  `RestoreRevisionCommand` for the identical reason this ADR now reaffirms for
  queries: no concrete domain meaning was identified for it.

## 4. Problem Statement

`services/knowledge-graph` cannot answer entity, edge, neighbor, path, or temporal
questions today — only whole-graph revision operations exist. The graph algorithms
this capability needs already exist, proven and tested, one layer down in
`emg-memory-graph`; this ADR decides how the application layer acquires a graph
snapshot (current or historical), which of those existing algorithms it calls, what
shape it returns to callers, how pagination and safety limits are enforced, and which
capabilities are explicitly out of scope for V1 — without reopening ADR-023's
revision-history architecture and without duplicating `MemoryQueryEngine`/
`temporal_query.py` logic inside a new platform-core port or a new adapter.

## 5. Existing Architecture

(Established by the prior read-only discovery; restated here only as decision input,
not re-derived.)

- `emg_memory_graph.graph` — `MemoryGraph` (node/edge lookup, adjacency, ordering).
- `emg_memory_graph.query` — `MemoryQueryEngine`, `RelatedNode`, `PathResult`.
- `emg_memory_graph.temporal_query` — `node_exists_at`, `active_edges_at`,
  `subgraph_as_of`, `neighbors_at`, `attribute_at`.
- `emg_memory_graph.temporal` — `TemporalValidity` (`[valid_from, valid_until)`,
  `valid_until=None` open-ended), `TemporalHistory.as_of(moment)`.
- `emg_memory_graph.limits` — `MAX_TRAVERSAL_DEPTH = 64`, `MAX_PATH_RESULTS = 1_000`
  (reserved, currently unenforced by any caller).
- `emg_platform_core.ports.graph_store` — `GraphStore`, `GraphTransaction`,
  `WriteReceipt` (unchanged since ADR-023).
- `emg_platform_core.ports.graph_revision_reader` /
  `emg_platform_core.ports.revision_metadata` — `GraphRevisionReader`,
  `RevisionMetadata`, `HistoricalGraphRevision` (unchanged since ADR-023).
- `services/knowledge-graph/src/emg_knowledge_graph/{service,commands,results,errors}.py` —
  `KnowledgeGraphApplication` and its five existing methods; `KnowledgeGraphApplicationError`
  and its existing four subclasses (`InvalidRevisionCommandError`, `RevisionBuildError`,
  `InvalidHistoryQueryError`, `RevisionNotFoundError`, `RevisionRestoreError`,
  `UnsupportedHistoryCapabilityError`).
- `emg-persistence/store.py` (`PostgresNeo4jGraphStore`) and
  `neo4j/projection.py` (`Neo4jGraphProjection`) — current-head read-repair/fallback
  behavior, unchanged since Phase 2.

## 6. Decision Drivers

- No graph-traversal or temporal-filtering algorithm already proven correct in
  `emg-memory-graph` should be reimplemented anywhere else.
- `GraphStore` and `GraphRevisionReader` must remain exactly as ADR-022/ADR-023 left
  them — this sprint is additive at the application layer only.
- The service must keep depending only on `emg-platform-core` and `emg-memory-graph`,
  satisfying the existing, unmodified dependency-boundary test.
- Revision selection (which immutable snapshot) and domain temporal filtering (which
  facts were valid at a moment inside that snapshot) are two independent axes that
  must never be conflated into one field or one concept.
- Every new query must be tenant-scoped and must reject invalid input before any
  `GraphStore`/`GraphRevisionReader` interaction, mirroring every existing command's
  `validate()`-before-transaction pattern.
- Cross-tenant and nonexistent-entity lookups must remain indistinguishable, exactly
  as ADR-023 §22 established for revisions.
- Deterministic ordering must not depend on which adapter (`InMemoryGraphStore` vs.
  `PostgresNeo4jGraphStore`) produced the snapshot.
- Safety limits must be hard, code-level ceilings, matching the existing convention
  in `emg_memory_graph.limits` and ADR-023's `MAX_REVISION_LIST_LIMIT`, not runtime
  configuration.

## 7. Considered Options

**Option 1 — Add entity/traversal query methods directly to `GraphStore`.**
Rejected. `GraphStore` is the minimal current-state read/write/transaction contract
ADR-022 deliberately kept small; every adapter, including any future one, would be
forced to reimplement `MemoryQueryEngine`/`temporal_query.py`'s logic itself, and the
port's responsibility would blur from "durability" into "query planning."

**Option 2 — Add graph-query methods to `GraphRevisionReader`.** Rejected. That
port's entire reason for existing (ADR-023 §9) is read-only *historical revision*
access — metadata listing and full historical reads. It has no natural home for
`find_shortest_path` or `list_neighbors`, and conflating the two would recreate the
exact "two responsibilities, one Protocol" problem ADR-023 avoided by keeping
`GraphRevisionReader` separate from `GraphStore` in the first place.

**Option 3 — A new `GraphQueryReader` platform-core port.** Rejected for V1. It would
require every current and future adapter to re-implement traversal/temporal-filter/
pagination logic that already exists, correctly and deterministically, in
`emg-memory-graph`, plus a new mirrored canonical-DTO surface across the port
boundary — a large new commitment with no present evidence of a second consumer that
would need query capability outside `services/knowledge-graph`.

**Option 4 — A separate query-domain library.** Rejected. Nothing in the repository
indicates a second service needs entity/neighbor/path querying independent of
`services/knowledge-graph`; `emg_semantic_layer`/`MemoryGraphExecutor` already occupy
the "reusable, storage-independent query model" niche this option would duplicate.

**Option 5 — An application-only in-memory query layer inside
`services/knowledge-graph`, over `GraphStore`/`GraphRevisionReader` acquisition and
`MemoryGraph`/`MemoryQueryEngine`/`temporal_query.py` execution.** **Selected.**
Zero new platform-core port surface, zero new adapter work, full reuse of code
already proven by the Sprint 7.1/7.2 test suites, and a natural continuation of the
"thin orchestrator" pattern `build_revision`/`restore_revision` already established.

## 8. Decision

1. Adopt an application-only in-memory query layer inside `services/knowledge-graph`
   (Option 5, §7). `GraphStore` and `GraphRevisionReader` are not modified.
2. Every query command resolves its graph snapshot through `GraphQueryScope` (§11):
   `revision_number is None` reads the current head via `GraphStore.read(tenant)`;
   an explicit `revision_number` reads that exact immutable revision via
   `GraphRevisionReader.read_revision(tenant, revision_number)`.
3. V1 supports exactly the thirteen capabilities enumerated in §10 — entity/edge
   lookup, type filtering, exact property matching, single-direction and
   both-direction neighbors, single shortest-path search, valid-at temporal
   filtering, current-head and historical-revision queries, and deterministic
   cursor pagination — and explicitly defers the ten capabilities enumerated in §20.
4. New, service-owned, immutable application DTOs are introduced per §16; no
   `MemoryNode`/`MemoryEdge`/`SafeLabel`/persistence/Neo4j/repository type is ever
   returned to a caller of `KnowledgeGraphApplication`.
5. Cursor pagination, ordering by `node_id`/`edge_id` ascending, and a maximum page
   size of 200 are adopted per §14; offset pagination is rejected.
6. Path search is limited to one unweighted shortest path between two node ids,
   reusing `MemoryQueryEngine.shortest_path` unchanged, bounded by
   `MAX_TRAVERSAL_DEPTH = 64` per §15.
7. A new application error taxonomy (§17) is added beneath the existing
   `KnowledgeGraphApplicationError`; no `CrossTenantAccessError` is introduced.
8. Safety limits (§18) are fixed code-level constants, validated before any store
   interaction.
9. Neo4j's role is unchanged and out of scope for modification (§19): it remains an
   optional, best-effort current-head accelerator, never queried directly by this
   sprint's query engine, never consulted for historical queries.
10. No change to `GraphStore`, `GraphRevisionReader`, PostgreSQL schema, Neo4j schema,
    or ADR-023's revision semantics is in scope.

## 9. Query Flow

Every new `KnowledgeGraphApplication` query method follows the same five-step flow,
mirroring the validate-before-transaction discipline every existing method already
uses:

1. **Validate** the command/query object via its own `validate()` method — reject
   malformed tenant, limit, cursor, revision number, filter, or temporal value before
   any port call, exactly as `ListRevisionsQuery.validate()` already does today.
2. **Resolve the graph snapshot** through `GraphQueryScope` (§11): current head via
   `GraphStore.read(tenant)`, or one immutable historical revision via
   `GraphRevisionReader.read_revision(tenant, revision_number)`. Exactly one snapshot
   is acquired per query; a query never combines two snapshots.
3. **Execute the query** against the acquired `MemoryGraph`, calling only:
   `MemoryGraph`'s own O(1)/O(deg) lookup and adjacency methods; `MemoryQueryEngine`
   (constructed over the acquired graph) for related-node lookup and shortest-path;
   and `temporal_query.py`'s free functions for valid-at filtering. No new traversal,
   filtering, or temporal-reconstruction algorithm is written — every execution step
   calls code that already exists and is already tested.
4. **Map** the domain result (`MemoryNode`/`MemoryEdge`/`RelatedNode`/`PathResult`/
   `TemporalFact`) into the immutable, service-owned DTOs defined in §16. No domain
   or platform-core type crosses this boundary unwrapped.
5. **Return** the mapped result together with a `QueryRevisionContext` (§16)
   identifying which snapshot — current head or which exact `revision_number` — the
   result was computed against.

This is the same shape `list_revisions`/`get_revision`/`compare_revisions` already
established in ADR-023 §12, extended from "revision metadata" results to "graph
content" results.

**Addendum (Phase 2 implementation clarification).** Step 5's `QueryRevisionContext`
carries a non-optional `revision_number`/`committed_at` (§16). `GraphStore.read()`
alone exposes no revision identity, so the current-head path in step 2 also requires
`GraphRevisionReader.list_revisions(tenant, limit=1)` to obtain the head's identity —
this port call happens in addition to, not instead of, `GraphStore.read(tenant)` for
the graph content itself. Consequently, **every** query method requires a configured
`GraphRevisionReader`, not only ones that select an explicit historical
`revision_number` (see also §17's `UnsupportedHistoryCapabilityError`, which now
applies uniformly for the same reason). This adds one `GraphRevisionReader` call
(pure PostgreSQL, §19) alongside `GraphStore.read()` on every current-head query,
including ones that would otherwise only need the Neo4j-accelerated read path. This
is accepted as the correct resolution given §16's fixed `QueryRevisionContext` shape,
not a defect: the alternative would require making `QueryRevisionContext.revision_number`
optional, which this ADR does not adopt.

## 10. V1 Query Capabilities

Adopted for V1, each backed entirely by an existing, unmodified domain primitive:

| # | Capability | Domain primitive |
| --- | --- | --- |
| A | Entity lookup by canonical node id | `MemoryGraph.node(node_id)` |
| B | Entity listing/filtering by node type | `MemoryGraph.nodes_of_type(node_type)` |
| C | Exact entity property matching | Scan over `MemoryGraph.nodes`, matched against typed scalar fields and `metadata` (§12) |
| D | Edge lookup by canonical edge id | `MemoryGraph.edge(edge_id)` |
| E | Edge listing/filtering by edge type | Scan over `MemoryGraph.edges`, filtered by `edge_type` |
| F | Outgoing neighbors | `MemoryGraph.out_edges(node_id)` |
| G | Incoming neighbors | `MemoryGraph.in_edges(node_id)` |
| H | Both-direction neighbors | `MemoryGraph.incident_edges(node_id)` / `MemoryQueryEngine._related`-style filtering |
| I | Single unweighted shortest-path search | `MemoryQueryEngine.shortest_path(from_id, to_id)` |
| J | Valid-at temporal filtering | `temporal_query.active_edges_at` / `neighbors_at` / `attribute_at` / `node_exists_at` |
| K | Current-head queries | `GraphStore.read(tenant)` |
| L | Historical-revision queries | `GraphRevisionReader.read_revision(tenant, revision_number)` |
| M | Deterministic cursor pagination | Ordering over `MemoryGraph`'s already-sorted `.nodes`/`.edges` tuples (§14) |

Explicitly deferred for V1 (detailed rejection rationale in §20): free-text search,
fuzzy search, tokenized search, full-text indexes, all-path enumeration, k-shortest
paths, arbitrary path enumeration, timestamp-based historical-revision lookup, a
generic query DSL, and direct Neo4j query execution.

## 11. GraphQueryScope — The Revision Axis vs. the Domain Temporal Axis

`GraphQueryScope` is the one binding concept every query command carries to select
its graph snapshot:

```python
@dataclass(frozen=True, slots=True)
class GraphQueryScope:
    """Which tenant's graph, and which immutable snapshot of it, a query runs
    against. Contains no timestamp — see the Revision Axis / Domain Temporal
    Axis distinction below."""

    tenant: TenantId
    revision_number: int | None  # None = current head
```

Semantics, fixed by this ADR:

- **`revision_number is None`** — the query runs against the current graph head,
  acquired via `GraphStore.read(tenant)`.
- **`revision_number` is an explicit `int`** — the query runs against that exact
  immutable revision, acquired via
  `GraphRevisionReader.read_revision(tenant, revision_number)`. A nonexistent
  revision number raises `RevisionNotFoundError` (§17), identically for an unused
  number and a different tenant's number, per ADR-023 §22's existing convention.
- **`GraphQueryScope` carries no `as_of` timestamp selector.** Exactly as ADR-023 §15
  rejected `as_of` on `RestoreRevisionCommand` for lack of concrete domain meaning,
  no timestamp-to-revision resolution mechanism exists anywhere in the revision
  layer today, and this ADR does not invent one. Selecting a revision by wall-clock
  time is explicitly deferred (§20.10).

This ADR fixes, as a hard architectural rule, the distinction between two
independent axes that must never be treated as equivalent or merged into one field:

- **The revision axis** — *which immutable whole-graph snapshot* is selected
  (`GraphQueryScope.revision_number`). This is a commit-identity concept, resolved
  through `GraphStore`/`GraphRevisionReader`, and is the only axis ADR-023 governs.
- **The domain temporal axis** — *which nodes, edges, or attribute values were valid
  at a moment* **inside** whichever snapshot the revision axis selected (a
  `valid_at: datetime` argument on a query command, executed via
  `temporal_query.py` against the graph `GraphQueryScope` already resolved).

These two axes **compose** (e.g. "what was node X's `owner` attribute as of last
Tuesday, according to the graph as it stood at revision 12") but are never
interchangeable: a query with `revision_number=None` and a `valid_at` filter answers
"what was true at that moment, according to the *current* graph's own temporal
history for that node/edge/attribute" — it does not, and cannot, reach back to a
different whole-graph revision. Selecting an older revision does not, by itself,
imply any particular `valid_at` filtering, and vice versa.

## 12. Property Matching

Exact entity property matching (§10.C) in V1 is limited to two categories, both
already present on `MemoryNode` (`emg_memory_graph/nodes.py`) without any model
change:

- **Typed `MemoryNode` scalar fields** the domain model already declares:
  `node_type`, `source`, `confidence`, `classification` (and, symmetrically for edge
  queries, `MemoryEdge`'s own `edge_type`/`direction`/`confidence`/`classification`).
  Matching against any of these is a direct equality (or, where the underlying field
  is numeric, comparison) check against an already-typed value.
- **Exact key/value matching inside `metadata`** (`Metadata.items`, capped at
  `MAX_METADATA_ENTRIES = 128`) — a caller supplies a key and an expected value; a
  match requires an entry in `node.metadata.items` (or `edge.metadata.items`) whose
  key and value both match exactly.

Explicitly **not** in scope for V1: arbitrary object traversal (reflecting into
nested pydantic model internals beyond the declared scalar fields and `metadata`),
internal pydantic-model reflection of any kind, and a generic predicate language
(comparison operators, boolean combinators, or anything resembling
`emg_semantic_layer.SemanticFilter`'s operator set). `metadata` must not be
described, documented, or implemented as strongly typed anywhere in this feature —
it remains exactly what `Metadata` already is: a bounded, schemaless key/value
container, matched by exact equality only, not by type-aware comparison.

## 13. Temporal Semantics

Existing domain semantics are preserved exactly, with no change to
`emg_memory_graph`'s temporal models:

- **Edge validity:** `TemporalValidity`'s half-open `[valid_from, valid_until)`
  interval, `valid_until=None` meaning open-ended (still currently valid), tested via
  `MemoryEdge.is_active_at(moment)` / `temporal_query.active_edges_at`.
- **Node existence:** `created_at <= moment` (`temporal_query.node_exists_at`).
  There is currently no node-deletion or end-of-existence timestamp anywhere in the
  domain model; this ADR does not introduce one.
- **Node attribute history:** `TemporalHistory.as_of(moment)`
  (`temporal_query.attribute_at`), where each tracked attribute (e.g. `owner`) has
  its own independent, non-overlapping timeline, enforced by
  `TemporalHistory`'s own existing model validator.

New application-layer requirement, enforced at the command-validation boundary, not
inside `emg_memory_graph`: **any application command accepting a `valid_at` argument
must require a timezone-aware `datetime`, rejecting a naive one during command
validation, before any `GraphStore`/`GraphRevisionReader` interaction** — the same
requirement `BuildRevisionCommand.as_of` already enforces today
(`InvalidTemporalFilterError`, §17). This is a new application-boundary rule, not a
change to `TemporalValidity`/`TemporalHistory`'s own fields, which today accept plain
`datetime` values without enforcing timezone-awareness themselves. That underlying
domain-model gap is recorded as a possible future hardening item (§22/Risks) — this
ADR does not resolve it inside `emg_memory_graph`, only guards against it at the one
new place naive datetimes could enter the system through this feature.

## 14. Pagination and Ordering

Cursor pagination is adopted; offset pagination is rejected.

- **Node ordering key:** `node_id`, ascending — already `MemoryGraph`'s own natural
  sort order (its field validator sorts `.nodes` by `node_id` at construction).
- **Edge ordering key:** `edge_id`, ascending — already `MemoryGraph`'s own natural
  sort order (its field validator sorts `.edges` by `edge_id`; every adjacency
  accessor additionally re-sorts by `edge_id` at call time).
- **Cursor semantics:** an exclusive boundary cursor, in the same spirit as
  `before_revision_number`'s existing convention from ADR-023, adapted for the
  opposite ordering direction. `before_revision_number` restricts to ids *less than*
  the boundary because revision listing is **descending** — "less than the last id
  seen" is what advances a descending list forward. Node/edge listing is fixed
  **ascending** by this same section, so the operator that advances a page forward
  is necessarily the opposite one: `before_node_id`/`before_edge_id` restrict a page
  to ids **strictly greater than** the given boundary (the last id returned on the
  previous page), never including the boundary id itself. (Earlier drafts of this
  ADR stated the boundary comparison as "strictly-earlier ids than the boundary,"
  copied verbatim from `before_revision_number`'s wording without adjusting for the
  ordering direction; applied literally to an ascending listing that wording would
  make every page identical to the first, never advancing, which is not a viable
  pagination design. This is corrected here; the Phase 2 implementation already used
  the greater-than comparison this corrected wording now describes, and needs no
  code change.) The field names (`before_*`) are kept unchanged for continuity with
  the ADR-023 convention despite the flipped comparison.
- **Maximum page size:** 200, mirroring `MAX_REVISION_LIST_LIMIT`. Validated as
  `1 <= limit <= 200` in command validation; a request above the ceiling is rejected,
  never silently clamped.
- **Offset pagination is rejected** (§20.6): cursor pagination over a stable,
  content-addressed id is safer against concurrent writes shifting a window, and it
  is the convention ADR-023 already established for revision listing — introducing a
  second, inconsistent pagination style for graph queries in the same service would
  be an unforced regression.

**Adapter independence.** Deterministic ordering across `InMemoryGraphStore` and
`PostgresNeo4jGraphStore` is guaranteed structurally, not by separate enforcement per
adapter: pagination and ordering happen entirely over the **already-acquired,
already-sorted** `MemoryGraph.nodes`/`MemoryGraph.edges` immutable tuples, after
snapshot acquisition (§9 step 2) has completed. The query layer never orders by an
adapter-specific row order or database cursor — by the time ordering/pagination logic
runs, the only input is one in-memory `MemoryGraph`, whose own sortedness is already
adapter-independent (both `_unique_sorted_nodes`/`_unique_sorted_edges` field
validators run identically regardless of which adapter constructed the graph).

## 15. Path Search

V1 path search is limited to exactly one unweighted shortest path between two
canonical node ids, reusing `MemoryQueryEngine.shortest_path(from_id, to_id)`
unchanged — no new traversal algorithm is introduced.

- **Ceiling:** `MAX_TRAVERSAL_DEPTH = 64` (already reserved in
  `emg_memory_graph.limits`) is adopted as the absolute maximum path length V1 will
  accept or return.
- **Caller-requested depth:** a query command may request a smaller maximum depth
  than the ceiling; it may never request a larger one. The requested depth is
  validated in command validation — **before** any graph snapshot is acquired — and
  a request exceeding `MAX_TRAVERSAL_DEPTH` raises `PathDepthExceededError` (§17)
  prior to any `GraphStore`/`GraphRevisionReader` call.
- **Unreachable paths:** when `MemoryQueryEngine.shortest_path` returns `None`
  (no path exists), the query result is an explicit not-found `PathResult` with
  `found=False` and empty `node_ids`/`edge_ids` (§16) — this is a normal, valid
  result, not an error, and it must never trigger any broader or unrestricted
  traversal attempt.
- **A found path longer than the caller's requested `maximum_depth`:**
  `MemoryQueryEngine.shortest_path` has no depth parameter — it always runs an
  unbounded BFS and returns *the* shortest path, whatever its length. When that
  length exceeds the query's own (already-validated, `<= MAX_TRAVERSAL_DEPTH`)
  `maximum_depth`, the result is the same explicit not-found `PathResult`
  (`found=False`, empty `node_ids`/`edge_ids`) described above for unreachable
  pairs — **not** `PathDepthExceededError`. `PathDepthExceededError` is reserved
  exclusively for the command-validation-time case above (a *requested* depth
  exceeding the ceiling, rejected before any graph snapshot is acquired); it is
  never raised from an executed traversal outcome, consistent with this
  section's rule that unsatisfying path-search outcomes are normal results, not
  errors.
- **Not in scope for V1:** all-path enumeration, weighted paths, k-shortest paths,
  and any path-pattern DSL (§20.9). `MAX_PATH_RESULTS = 1_000` (also already reserved
  in `emg_memory_graph.limits`) is **not** used by the single-path V1 API — it is
  recorded here as reserved for a future multi-path capability, not wired into
  anything this ADR authorizes.

## 16. Application Contracts

All new types are immutable (matching `BuildRevisionCommand`/`RevisionSummary`'s
existing `@dataclass(frozen=True, slots=True)` convention). This section settles
their binding field lists; it does not implement them — no method body, store call,
or business logic is specified here, only shape.

```python
@dataclass(frozen=True, slots=True)
class GraphQueryScope:
    tenant: TenantId
    revision_number: int | None


@dataclass(frozen=True, slots=True)
class QueryRevisionContext:
    """Identifies which immutable snapshot a query result was computed against."""

    revision_number: int
    committed_at: datetime
    is_current_head: bool


@dataclass(frozen=True, slots=True)
class EntitySummary:
    node_id: str
    node_type: str
    label: str
    confidence: float
    classification: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EntityDetails:
    summary: EntitySummary
    source: str
    aliases: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    histories: tuple[TemporalHistory, ...]
    metadata: Metadata


@dataclass(frozen=True, slots=True)
class EdgeDetails:
    edge_id: str
    edge_type: str
    source_id: str
    target_id: str
    direction: str
    confidence: float
    validity: TemporalValidity
    created_at: datetime
    updated_at: datetime
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class NeighborResult:
    entity: EntitySummary
    via_edge_id: str
    edge_type: str
    confidence: float
    direction: str


@dataclass(frozen=True, slots=True)
class PathResult:
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    length: int
    found: bool


@dataclass(frozen=True, slots=True)
class PageInfo:
    limit: int
    returned_count: int
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class PagedEntityResult:
    items: tuple[EntitySummary, ...]
    page_info: PageInfo
    revision_context: QueryRevisionContext


@dataclass(frozen=True, slots=True)
class EntityQueryResult:
    item: EntityDetails
    revision_context: QueryRevisionContext
```

(`PagedEdgeResult`/`PagedNeighborResult`/`EdgeQueryResult`/`PathQueryResult` follow
the identical `items`/`page_info`/`revision_context` or `item`/`revision_context`
shape and are not separately enumerated here.)

Decisions binding these contracts:

- **Paginated result concepts carry exactly `items`, `page_info`, and
  `revision_context`.** **Single-item result concepts carry exactly `item` and
  `revision_context`.** No other top-level shape is introduced.
- `EvidenceRef`, `TemporalHistory`, `Metadata`, and `TemporalValidity` are reused
  directly from `emg_memory_graph` inside `EntityDetails`/`EdgeDetails` — these are
  already-exposed, stable domain value objects (the same reuse pattern ADR-023 §12
  already established by embedding `emg_memory_graph`'s `MemoryGraph`/`GraphDiff`
  directly inside `RevisionDetails`/`RevisionDiff`). This is reuse of stable domain
  value objects, not a leak of persistence or adapter internals.
- **Never exposed, under any circumstance:** Neo4j records, PostgreSQL rows, the
  persistence-internal `RevisionRecord` (ADR-023 §18), or any raw `GraphStore`
  adapter/repository-internal type. `MemoryNode`/`MemoryEdge`/`SafeLabel` are not
  returned directly either — `EntitySummary`/`EntityDetails`/`EdgeDetails` are the
  service's own types, mapped from domain objects, exactly as `RevisionSummary` is
  its own type mapped from `RevisionMetadata` rather than a re-export of it.
- Service-owned contracts (this section) remain the public application boundary for
  every new query method; a caller of `KnowledgeGraphApplication` never needs to
  import `emg_memory_graph` or `emg_platform_core` to consume a query result.

**Addendum (Phase 2 implementation clarification): `EntityHistoryResult`.** This
section did not originally enumerate a result type for
`EntityAttributeHistoryQuery` (§10.J) — no dedicated contract existed for "the
value of one attribute at a moment." `EntityHistoryResult(item: TemporalFact |
None, revision_context: QueryRevisionContext)` is adopted as that contract,
following the identical single-item `item`/`revision_context` shape this section
already fixes for every other single-item result. It reuses `TemporalFact`
directly from `emg_memory_graph`, the same reuse pattern already applied above to
`EvidenceRef`/`TemporalHistory`/`Metadata`/`TemporalValidity` — `TemporalFact` is
`TemporalHistory`'s own element type and was already transitively reachable via
`EntityDetails.histories[i].facts`, so this does not expose a previously-unreachable
domain type. `item is None` is the normal, explicit result when the attribute had
no value at the requested moment (mirroring `TemporalHistory.as_of`'s own contract),
not an error.

## 17. Error Model

All new errors derive from the existing `KnowledgeGraphApplicationError` base,
following the established convention.

- **`InvalidQueryError(KnowledgeGraphApplicationError)`** — raised by a query
  command's own `validate()` for an invalid limit, an invalid cursor, an invalid
  revision number, or a malformed filter (mirroring `InvalidHistoryQueryError`'s
  existing scope for paging/revision-number validation, extended to the new query
  commands).
- **`EntityNotFoundError(KnowledgeGraphApplicationError)`** — raised when a requested
  `node_id` is absent from the selected tenant's resolved graph snapshot. Wraps the
  domain-level `NodeNotFoundError` (`emg_memory_graph.errors`) via `raise ... from
  cause`, exactly as `RevisionNotFoundError` already wraps its platform-core
  counterpart — the domain exception type never crosses the application boundary
  unwrapped.
- **`EdgeNotFoundError(KnowledgeGraphApplicationError)`** — raised when a requested
  `edge_id` is absent from the selected tenant's resolved graph snapshot.
- **`RevisionNotFoundError`** — the existing application error (ADR-023 §17) is
  reused, unmodified, for an invalid `GraphQueryScope.revision_number`.
- **`UnsupportedHistoryCapabilityError`** — the existing application error
  (ADR-023 §17) is reused, unmodified, for a historical-revision query attempted
  without a configured `revision_reader`.
- **`QueryLimitExceededError(KnowledgeGraphApplicationError)`** — raised when a
  requested hard safety limit (page size, neighbor-result count, property-predicate
  count) is exceeded (§18).
- **`InvalidTemporalFilterError(KnowledgeGraphApplicationError)`** — raised for an
  invalid or timezone-naive `valid_at` value (§13), before any store interaction.
- **`PathDepthExceededError(KnowledgeGraphApplicationError)`** — raised when a
  requested path-search depth exceeds `MAX_TRAVERSAL_DEPTH = 64` (§15), before any
  graph snapshot is acquired.

**Explicitly rejected:** a dedicated `CrossTenantAccessError` is **not** introduced,
for the identical reason ADR-023 §17 already gave and reaffirms here — no second
security/authorization context exists against which a query's tenant could be
checked, and tenant isolation is structural (every lookup is scoped by `tenant` at
acquisition), not an access-control decision requiring its own error type. A missing
entity/edge for one tenant and an entity/edge that exists only for a different tenant
must both surface as the same `EntityNotFoundError`/`EdgeNotFoundError`, by
construction, so no information about another tenant's data is ever revealed.

## 18. Validation and Safety Limits

Command validation occurs before any `GraphStore`/`GraphRevisionReader` interaction,
for every new query command, without exception — the same discipline every existing
command already follows.

Adopted ceilings, all fixed code-level constants, never runtime configuration:

- **Maximum page size:** 200 (`1 <= limit <= 200`), mirroring
  `MAX_REVISION_LIST_LIMIT`.
- **Maximum path depth:** 64 (`MAX_TRAVERSAL_DEPTH`), per §15.
- **Maximum exact property predicates per query:** 8.
- **Maximum metadata key length / maximum metadata value length:** the existing
  domain limits already enforced by `emg_memory_graph.limits`/`Metadata` (no new
  ceiling is introduced; the existing one is reused as-is).
- **Maximum neighbor results per page:** 200 — the same ceiling as maximum page size,
  not a separate concept.

Free-text length limits are explicitly out of scope, because free-text search itself
is deferred (§20.8). These limits are, per the existing convention
`emg_memory_graph.limits` already establishes ("deliberate, conservative ceilings —
not tuning knobs"), deliberate ceilings enforced in code, not performance-tuning
knobs a deployment could adjust.

## 19. Neo4j Role

Unchanged from Phase 2 / ADR-023, and explicitly out of scope for modification in
this sprint:

Neo4j **remains**: an optional current-head projection; a read accelerator, wired
only into `PostgresNeo4jGraphStore.read()`'s existing read-repair/fallback path;
subject to projection lag (the `ProjectionWorker` is operator/CI-driven, not
synchronous with writes); protected by the existing read-repair and PostgreSQL
fallback behavior on any `PersistenceError`.

Neo4j is **not**: the authoritative revision source (PostgreSQL remains
authoritative, unchanged); queried directly by the Sprint 7.3 query engine (every
new query method acquires its snapshot exclusively through `GraphStore.read()` or
`GraphRevisionReader.read_revision()`, never through a Cypher query issued by this
feature); used for historical-revision queries under any circumstance (`list_revisions`/
`read_revision` are, and remain, pure PostgreSQL); or modified with new Cypher
queries, constraints, indexes, or projection-worker changes in this sprint.

Historical queries always resolve through PostgreSQL-backed revision history (via
`PostgresRevisionRepository`) or the in-memory revision reader (`InMemoryGraphStore`'s
retained history) — never through the Neo4j projection. No Neo4j schema, constraint,
index, projection-worker, or Cypher change belongs in Sprint 7.3 V1.

## 20. Rejected Alternatives

1. **Extending `GraphStore` with entity/traversal query methods.** Rejected now
   because it would force every current-state consumer to structurally depend on
   query capability it may never use, and would duplicate `MemoryQueryEngine`/
   `temporal_query.py` logic per-adapter. May be reconsidered only if a future
   adapter genuinely cannot support the "acquire whole graph, query in memory"
   pattern this ADR relies on — no such adapter exists or is planned today.
2. **Extending `GraphRevisionReader` with graph-query methods.** Rejected now
   because that port's sole responsibility (ADR-023 §9) is historical-revision
   metadata/full-read access, not graph-structure querying. Unlikely to be
   reconsidered; conflating the two would undo ADR-023's own separation rationale.
3. **Creating a `GraphQueryReader` platform-core port.** Rejected for V1 for lack of
   a second consumer and because it would require duplicating already-correct
   `emg-memory-graph` logic across adapters. May be reconsidered later if a second
   service (outside `services/knowledge-graph`) needs the same query capability
   against a different acquisition path.
4. **Creating a separate query-domain package.** Rejected now; no evidence of a
   second consumer. `emg_semantic_layer`/`MemoryGraphExecutor` already fill the
   "reusable, storage-independent query model" role this option would duplicate.
   May be reconsidered if query logic needs to be shared outside
   `services/knowledge-graph` at a later date.
5. **Direct Neo4j query execution in V1.** Rejected now because Neo4j is a
   best-effort, lagging, current-head-only accelerator with no historical
   capability and no query surface beyond its internal MERGE/DELETE/CAS mechanics
   (§19) — building a query engine on top of it would inherit its staleness and
   fallback behavior as correctness risk rather than as an already-isolated,
   already-tolerated current-head nuance. May be reconsidered only alongside a
   dedicated ADR establishing Neo4j as a genuine, consistency-guaranteed query
   source, which no evidence in this repository supports today.
6. **Offset pagination.** Rejected now in favor of cursor pagination (§14), for
   consistency with ADR-023's existing convention and safety against concurrent
   writes shifting an offset window. Unlikely to be reconsidered absent a concrete
   requirement cursor pagination cannot satisfy.
7. **A generic query DSL.** Rejected now; no repository evidence supports the
   complexity of a predicate/traversal language, and `emg_semantic_layer`'s existing
   `SemanticFilter` demonstrates what such a DSL would cost to build correctly. May
   be reconsidered if V1's fixed capability set proves insufficient in practice.
8. **Free-text search without explicit semantics/index design.** Rejected now;
   "text match" semantics (prefix, substring, fuzzy, tokenized) are undefined by any
   repository evidence, and building one without a settled definition risks
   inventing semantics this discovery process was explicitly instructed to avoid.
   Should be reconsidered only via its own dedicated ADR once concrete matching
   semantics and an index strategy are proposed.
9. **All-path enumeration (and k-shortest paths, arbitrary path enumeration).**
   Rejected for V1; algorithmically distinct (exponential path enumeration) from the
   single-shortest-path BFS that exists today, with no existing bounded
   implementation to build on. `MAX_PATH_RESULTS` is reserved (§15) precisely so this
   can be reconsidered later without a naming or constant conflict.
10. **Timestamp-based revision selection (`as_of` on `GraphQueryScope`).** Rejected
    now, for the identical reason ADR-023 §15 already rejected it on
    `RestoreRevisionCommand`: no timestamp-to-revision resolution mechanism exists in
    the revision layer today, and inventing one here would silently reintroduce,
    through a query-engine side door, a decision ADR-023 deliberately deferred. May
    be reconsidered only alongside its own ADR extending the revision-history
    architecture itself — not as part of this query-engine ADR.

## 21. Dependency Boundaries

Confirmed, none newly introduced or violated:

- `services/knowledge-graph` continues to depend only on `emg-platform-core`
  (`GraphStore`, `GraphRevisionReader`, `RevisionMetadata`, `HistoricalGraphRevision`,
  identity types) and `emg-memory-graph` (`MemoryGraph`, `MemoryQueryEngine`,
  `temporal_query`, `TemporalHistory`, `TemporalValidity`, `EvidenceRef`, `Metadata`),
  exactly as it already does today.
- No new import of `emg_persistence` or `emg_knowledge_pipeline.graph_store` is
  introduced anywhere in `services/knowledge-graph`; the existing, unmodified
  `test_dependency_boundary.py` AST checks continue to apply unchanged to every new
  module.
- No new forbidden declared type name (`Node`/`Edge`/`Graph`/`GraphStore`/
  `GraphRevisionReader`/`Revision`/`Projection`/`Version`/`Evidence`/`Lineage`) is
  introduced by any new query command/result/error type — `EntitySummary`,
  `EdgeDetails`, `NeighborResult`, `PathResult`, `GraphQueryScope`, etc. are all
  clear of that forbidden set.
- `emg-platform-core`'s and `emg-persistence`'s own dependency directions are
  entirely unmodified by this ADR — no new port, no new adapter method, no new
  platform-core or persistence file is introduced.

## 22. Consequences

**Positive:**

- Maximum reuse of existing, already-tested graph primitives
  (`MemoryGraph`/`MemoryQueryEngine`/`temporal_query.py`) — no new traversal,
  filtering, or temporal-reconstruction algorithm is written.
- No duplicated query algorithm across adapters — `InMemoryGraphStore` and
  `PostgresNeo4jGraphStore` both feed the same in-memory query execution path, so
  there is exactly one implementation of every query behavior to maintain.
- No new platform-core port — `GraphStore` and `GraphRevisionReader` are untouched.
- Consistent current/historical query behavior — both paths converge on the same
  `MemoryGraph`-execution step (§9) regardless of which acquisition method supplied
  the snapshot.
- Deterministic, adapter-independent results, since ordering/pagination operate over
  `MemoryGraph`'s own already-sorted immutable tuples (§14).
- Minimal Sprint 7.3 implementation surface — new application-layer files only; zero
  new adapter or platform-core files.
- Easy in-memory testing — every pure-application and adapter-contract test can run
  entirely against `InMemoryGraphStore`, with no live PostgreSQL/Neo4j required,
  mirroring ADR-023's existing test strategy.
- No Neo4j dependency for correctness — every query path resolves through
  `GraphStore`/`GraphRevisionReader`, whose own existing fallback behavior already
  isolates callers from Neo4j's availability/staleness.

**Negative:**

- The whole graph snapshot must be loaded into memory before any query executes —
  there is no partial/streaming acquisition; a very large tenant graph is fully
  materialized for even a single-entity lookup.
- Node-type and edge-type filtering remain O(N)/O(E) linear scans (`nodes_of_type`
  has no index; no equivalent edge-type index exists either) — acceptable at today's
  scale but a real cost as tenant graphs grow toward `MAX_NODES`/`MAX_EDGES`.
- Large graphs may eventually require an indexed read adapter (e.g., a
  materialized-view or search-index layer) that this ADR does not attempt to design.
- Current-head query latency inherits `PostgresNeo4jGraphStore.read()`'s existing
  Neo4j read-repair/fallback behavior unchanged — this sprint neither improves nor
  worsens that existing characteristic, but callers of the new query methods inherit
  it for the first time.
- `KnowledgeGraphApplication` gains meaningfully more query-orchestration
  responsibility (thirteen new capabilities' worth of validate/acquire/execute/map
  methods) than the five methods it has today.
- No full-text search or advanced (multi-path/weighted/pattern) path-query
  capability exists in V1 — real user-facing capability is deferred, by design,
  pending its own future architectural decision.

## 23. Risks

| Risk | Mitigation |
| --- | --- |
| A future large tenant graph makes O(N) type/property filtering unacceptably slow | Page-size and result-count ceilings (§18) bound per-call cost; an indexed read adapter is an explicitly out-of-scope future option (§22), not attempted here |
| Naive `valid_at` datetimes silently produce wrong-timezone comparisons | Command validation rejects timezone-naive `valid_at` values before any store interaction (§13), via `InvalidTemporalFilterError` |
| A caller conflates the revision axis with the domain temporal axis (§11) | This ADR fixes the distinction explicitly and requires it be documented in every new command's own docstring at implementation time |
| `TemporalValidity`/`TemporalHistory`'s underlying fields still accept naive datetimes at the domain-model layer, inconsistently with the new application-layer enforcement | Recorded as a possible future hardening item (§13); not resolved by this ADR, which deliberately does not modify `emg_memory_graph`'s temporal models |
| A future maintainer reintroduces offset pagination or a second, inconsistent cursor style | This ADR fixes cursor semantics and page-size ceiling as binding (§14); any deviation is a visible diff against this document |
| `MAX_TRAVERSAL_DEPTH`/`MAX_PATH_RESULTS` drift out of sync between `emg_memory_graph.limits` and this feature's own validation | This ADR mandates reusing the existing constants directly (§15/§18), not redefining them locally |

## 24. Deferred Work

- Free-text, fuzzy, and tokenized entity search, and any full-text index (§20.8).
- All-path enumeration, k-shortest paths, and arbitrary path enumeration (§20.9).
- A generic query predicate/DSL language (§20.7).
- Timestamp-based (`as_of`) historical-revision selection (§20.10).
- Direct Neo4j query execution or any new Neo4j schema/constraint/index/Cypher
  surface for this feature (§19, §20.5).
- Domain-model-level timezone-awareness enforcement inside `TemporalValidity`/
  `TemporalHistory` themselves (§13/§23) — recorded as a possible future hardening
  item, not undertaken here.
- Any indexed/materialized read adapter for large-scale node/edge filtering (§22).
- Authentication, authorization, and tenant-authorization policy enforcement for
  read operations (unchanged non-goal from ADR-022/ADR-023).
- Any change to ADR-023's revision-history architecture, `GraphStore`, or
  `GraphRevisionReader` themselves.

## 25. Implementation Boundary

This ADR is architecture-only. No production code and no tests are added by this
document. Implementation is expected to occur later, as its own separate task, and is
expected to include:

- New query command models (one per capability in §10, each with its own
  `validate()` mirroring the existing command/query pattern).
- The immutable result DTOs fixed in §16 (`GraphQueryScope`, `QueryRevisionContext`,
  `EntitySummary`, `EntityDetails`, `EdgeDetails`, `NeighborResult`, `PathResult`,
  `PageInfo`, and their paginated/single-item wrapper shapes).
- The application error types fixed in §17, added beneath the existing
  `KnowledgeGraphApplicationError`.
- New `KnowledgeGraphApplication` query orchestration methods, following the
  five-step flow in §9.
- Thin internal query helper functions inside `services/knowledge-graph` (e.g. a
  type-filter scan, a metadata-match predicate, a cursor-boundary slice) — each a
  direct, minimal wrapper around an existing `MemoryGraph`/`MemoryQueryEngine`/
  `temporal_query.py` call, never a new algorithm.
- The validation constants fixed in §18.
- Pure application tests (validation-before-store-interaction, DTO mapping,
  not-found handling) per §26.
- Adapter-parity tests confirming identical results across `InMemoryGraphStore`- and
  `PostgresNeo4jGraphStore`-backed applications, per §26.

This ADR itself contains no production implementation code — the field lists in §16
and the port/flow descriptions in §9–§15 are binding contracts for a later
implementation task, not code to be merged as-is. The following are explicitly **not**
modified by this ADR or by the implementation it authorizes: the `GraphStore`
Protocol, the `GraphRevisionReader` Protocol, the PostgreSQL revision schema, the
Neo4j projection schema, ADR-023 itself, or any graph revision semantics ADR-023
already settled.

## 26. Test Strategy

Later implementation must add tests covering, at minimum: validation rejecting
invalid input before any `GraphStore`/`GraphRevisionReader` interaction (mirroring
the existing call-counter test-double pattern); current-head entity queries;
historical-revision entity queries; tenant isolation (a query scoped to one tenant
never returns another tenant's nodes/edges, and a foreign-tenant id produces the same
not-found result as a genuinely unused one); entity-not-found and edge-not-found
behavior; node-type filtering; exact scalar-property matching; exact metadata
matching; edge-type filtering; outgoing, incoming, and both-direction neighbor
queries; deterministic ordering (`node_id`/`edge_id` ascending, stable across repeated
calls); cursor pagination (exclusive boundary, bounded limit, correct `next_cursor`/
`has_more`); valid-at temporal filtering (before/inside/after an interval, including
the open-`valid_until` case); timezone-naive `valid_at` datetime rejection before any
store interaction; open-ended edge validity; temporal attribute history reconstruction
via `as_of`; a reachable shortest path; an unreachable shortest path (explicit
`found=False` result, not an error); path-depth-exceeded rejection before graph
acquisition; parallel edges of different types between the same node pair; self-loop
rejection continuing to hold as a domain invariant (not retested as new behavior, but
confirmed unaffected); adapter parity (`InMemoryGraphStore` vs.
`PostgresNeo4jGraphStore` producing field-identical results for the same query); and
`test_dependency_boundary.py`'s existing forbidden-import/forbidden-type-name checks
continuing to pass unmodified against every new module.

## 27. Compliance Checklist

- [ ] No graph-query method added to `GraphStore`.
- [ ] No graph-query method added to `GraphRevisionReader`.
- [ ] No new platform-core `GraphQueryReader` (or equivalent) port introduced in V1.
- [ ] No separate query-domain package introduced.
- [ ] Every new query method follows the five-step flow in §9 (validate → resolve
      scope → execute against `MemoryGraph`/`MemoryQueryEngine`/`temporal_query.py`
      → map to service-owned DTO → return with `QueryRevisionContext`).
- [ ] `GraphQueryScope` contains exactly `tenant` and `revision_number`; no `as_of`
      field is added anywhere in this feature.
- [ ] Exact property matching is limited to typed `MemoryNode`/`MemoryEdge` scalar
      fields and `metadata` key/value pairs; no generic predicate language is
      introduced; `metadata` is never documented as strongly typed.
- [ ] `valid_at` command validation rejects timezone-naive datetimes before any
      store interaction.
- [ ] Cursor pagination adopted; offset pagination rejected; page size validated
      `1 <= limit <= 200`.
- [ ] Path search limited to one unweighted shortest path; requested depth validated
      against `MAX_TRAVERSAL_DEPTH = 64` before graph acquisition.
- [ ] No DTO in §16 exposes a Neo4j record, PostgreSQL row, `RevisionRecord`, or raw
      adapter/repository-internal type.
- [ ] All new errors inherit from `KnowledgeGraphApplicationError`; no
      `CrossTenantAccessError` introduced.
- [ ] No change made to the Neo4j projection schema, constraints, indexes, or
      `ProjectionWorker`.
- [ ] `test_dependency_boundary.py` passes unmodified against every new module
      (at implementation time).
- [ ] No change made to `GraphStore`, `GraphRevisionReader`, PostgreSQL revision
      schema, or ADR-023's revision semantics.

---

## Decisions Made

- Adopt an application-only in-memory query layer inside `services/knowledge-graph`
  (Option 5, §7); `GraphStore`/`GraphRevisionReader` remain unmodified.
- `GraphQueryScope` (`tenant`, `revision_number: int | None`) is the binding
  snapshot-selection concept; no `as_of` field is introduced.
- The revision axis (which immutable snapshot) and the domain temporal axis (which
  facts were valid at a moment inside that snapshot) are fixed as distinct,
  composable, never-equivalent concepts (§11).
- Exact property matching is scoped to typed `MemoryNode`/`MemoryEdge` scalar fields
  plus `metadata` key/value pairs; `metadata` remains bounded and schemaless (§12).
- Existing temporal semantics (`TemporalValidity`, `TemporalHistory`,
  `node_exists_at`) are preserved unmodified; `valid_at` commands must require
  timezone-aware datetimes, enforced at the application-validation boundary (§13).
- Cursor pagination adopted (`node_id`/`edge_id` ascending, exclusive boundary
  cursor, page-size ceiling 200); offset pagination rejected (§14).
- Path search limited to one unweighted shortest path, bounded by
  `MAX_TRAVERSAL_DEPTH = 64`; `MAX_PATH_RESULTS` reserved but unused in V1 (§15).
- Application contracts fixed per §16 (`GraphQueryScope`, `QueryRevisionContext`,
  `EntitySummary`, `EntityDetails`, `EdgeDetails`, `NeighborResult`, `PathResult`,
  `PageInfo`, and their paginated/single-item wrappers).
- Error taxonomy fixed per §17 (`InvalidQueryError`, `EntityNotFoundError`,
  `EdgeNotFoundError`, reused `RevisionNotFoundError`/`UnsupportedHistoryCapabilityError`,
  `QueryLimitExceededError`, `InvalidTemporalFilterError`, `PathDepthExceededError`),
  all beneath `KnowledgeGraphApplicationError`; no `CrossTenantAccessError`.
- Safety limits fixed per §18 as code-level constants, validated before any store
  interaction.
- Neo4j's role is unchanged and out of scope for modification (§19).

## Rejected Alternatives

- Extending `GraphStore` with entity/traversal query methods (§20.1).
- Extending `GraphRevisionReader` with graph-query methods (§20.2).
- A new `GraphQueryReader` platform-core port (§20.3).
- A separate query-domain package (§20.4).
- Direct Neo4j query execution in V1 (§20.5).
- Offset pagination (§20.6).
- A generic query DSL (§20.7).
- Free-text search without explicit semantics/index design (§20.8).
- All-path enumeration, k-shortest paths, arbitrary path enumeration (§20.9).
- Timestamp-based revision selection (§20.10).

## Exact Future Files Expected to Change

- `services/knowledge-graph/src/emg_knowledge_graph/commands.py` (new query commands)
- `services/knowledge-graph/src/emg_knowledge_graph/results.py` (new result/summary/details/page DTOs)
- `services/knowledge-graph/src/emg_knowledge_graph/errors.py` (new application errors)
- `services/knowledge-graph/src/emg_knowledge_graph/service.py` (new orchestrator query methods)
- `services/knowledge-graph/src/emg_knowledge_graph/__init__.py` (export surface)
- `services/knowledge-graph/tests/test_query_engine.py` (new, name illustrative)
- `services/knowledge-graph/tests/test_dependency_boundary.py` (extended)
- No files under `libs/python/emg-platform-core/` (no `GraphStore`/`GraphRevisionReader` change).
- No files under `libs/python/emg-persistence/` (no adapter/repository change).
- No files under `libs/python/emg-memory-graph/` (no domain-model change).
- No files under `docker/`, `migrations/`, or any `.sql`/`.cypher` path.
- No change to `docs/architecture/EMG_ADR-023_KNOWLEDGE_GRAPH_REVISION_HISTORY_AND_NAVIGATION.md`.

## Unresolved Questions

None blocking. All questions raised during discovery (which read architecture to
adopt, how the revision axis and domain temporal axis relate, what is safe to ship in
V1 versus deferred, the exact DTO/error/limit shapes) are resolved as binding
decisions above. One non-blocking, explicitly deferred item is recorded for a
possible future ADR: whether `TemporalValidity`/`TemporalHistory`'s own fields should
gain enforced timezone-awareness at the domain-model layer, rather than only at this
feature's application-validation boundary (§13, §23).
