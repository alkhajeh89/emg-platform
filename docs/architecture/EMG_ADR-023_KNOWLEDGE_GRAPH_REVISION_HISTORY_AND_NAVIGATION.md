# ADR-023 — Knowledge Graph Revision History & Navigation

## 1. Title

Knowledge Graph Revision History & Navigation (Sprint 7.2)

## 2. Status

**Accepted.**

**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-03

> **Ratification note — 2026-08-03.** This ADR originally read *"Proposed.
> Implementation may begin only after architecture approval, following the same
> governance pattern ADR-022 established for Sprint 7.1."* It was implemented
> without that status ever being changed — recorded by the Architecture
> Baseline Review as finding MAJ-1, a GR-001 Rule 2 and Rule 6 defect.
>
> **Acceptance is retrospective ratification of the decisions exactly as
> written. No architectural decision is added, removed, or altered, and no new
> implementation authority is created.** Every item in the §28 compliance
> checklist was verified against the repository before ratification:
>
> - `GraphRevisionReader`, `RevisionMetadata`, and `HistoricalGraphRevision`
>   exist in `emg-platform-core` and are imported by
>   `services/knowledge-graph/src/emg_knowledge_graph/service.py:24`.
> - `WriteReceipt` carries `revision_number`, `committed_at`, and
>   `revision_created`, consumed at `service.py:509`, `:519`, and `:692-693`.
> - `KnowledgeGraphApplication` gained thin orchestrator methods only
>   (`service.py:588`, `:600`, `:619`, `:649`).
> - `list_revisions` reads metadata only and never deserializes `graph_json`.
> - Historical reads raise `SnapshotIntegrityError` on hash mismatch.
> - Restore opens exactly one transaction and stages the historical graph
>   unmodified (`service.py:674-681`).
> - No PostgreSQL migration was added for this ADR; the schema set is V001–V006,
>   none of which serves it.
> - `CrossTenantAccessError` does not exist, and
>   `services/knowledge-graph/tests/test_query_contracts.py:502` actively
>   asserts its absence.
> - `RestoreRevisionCommand` carries no `as_of` field, and its docstring cites
>   §12 and §15 as the reason.
>
> **One documented naming inconsistency, disclosed rather than corrected.**
> §8.4 names the application method `read_revision` while §13 refers to
> `get_revision`; the implementation uses `get_revision` at the application
> layer and `read_revision` on the port. This is an inconsistency internal to
> this ADR's own prose, not implementation drift, and the decision text is left
> unchanged.

**Date:** 2026-07-26
**Deciders:** Product / Architecture (EMG Platform)
**Supersedes:** none
**Related:** ADR-022 (Knowledge Graph Revision Build Workflow), Module 7 (FEAT-05-2,
FEAT-05-6), `PHASE2_ARCHITECTURE.md`, `docs/engineering/memory-graph-architecture.md`

## 3. Context

Sprint 7.1 (ADR-022) implemented `KnowledgeGraphApplication.build_revision()`: a
single orchestration method that opens one `GraphStore.transaction()`, calls
`MemoryGraphBuilder.from_ontology()`, stages the result, and returns a
`BuildRevisionResult` derived from `WriteReceipt`. That workflow is complete, tested,
and out of scope for modification here.

A read-only architecture discovery for Sprint 7.2 (list / read / compare / restore
historical revisions) established the following as repository fact, not proposal:

- PostgreSQL already stores the complete, immutable, append-only revision chain in
  `graph_revisions` (`tenant_id`, `revision_number`, `content_hash`, `parent_hash`,
  `principal_id`, `principal_kind`, `node_count`, `edge_count`, `graph_json`,
  `created_at`), anchored by a compare-and-set `graph_head` pointer.
- `RevisionRepository` (`libs/python/emg-persistence/src/emg_persistence/revisions/repository.py`)
  can already fetch one revision by `(tenant, revision_number)` via `get_revision`,
  and already exposes `revision_count`/`revision_exists`/`get_head`. It has **no**
  metadata-only list/range method — every existing read returns the full row,
  including `graph_json`.
- The canonical `emg_platform_core.ports.graph_store.GraphStore` Protocol exposes
  only current-state operations: `read(tenant)`, `write(...)`, `tenants()`,
  `transaction(...)`. There is no revision-addressed read anywhere on this port.
- `WriteReceipt` (same module) carries `tenant`, `principal`, `content_hash`,
  `node_count`, `edge_count` — **no** `revision_number`, **no** commit timestamp.
  `PostgresNeo4jGraphStore._revision_for()` computes a `revision_number` internally
  and then discards it before building the receipt actually returned to callers.
- `emg_memory_graph.versioning` already provides a proven, production-used diff
  function, `diff_graphs(before, after) -> GraphDiff`, reporting added/removed/
  modified node and edge ids in O(N+E). It is already relied upon by
  `PostgresNeo4jGraphStore._persist()` for no-op detection today.
- The same module also defines `GraphHistory`/`GraphRevision` — a second,
  **unrelated**, in-memory-only, non-tenant-scoped revision-chain model, used only
  by its own test file and one unused method on `MemoryQueryEngine`.
- Restoring a historical graph requires no new persistence primitive: staging a
  historical `MemoryGraph` through the existing `GraphStore.transaction()` already
  triggers the correct append-or-no-op behavior in `_persist()`.
- No PostgreSQL migration is required for any capability described in this ADR —
  every column Sprint 7.2 needs already exists in `graph_revisions`.
- ADR-022 §5, §12, §14, and §17 explicitly reserved "changes to the platform
  `GraphStore`, `GraphTransaction`, or `WriteReceipt`" as deferred, separately
  decided work, and explicitly stated the current result "does not manufacture a
  revision number the port does not expose." This ADR is that separate decision.

## 4. Problem Statement

`services/knowledge-graph` cannot list, read, compare, or restore historical
revisions today because the only persistence contract it is permitted to depend on
(`GraphStore`, enforced by `test_dependency_boundary.py`'s forbidden-import checks)
has no historical-read surface, and `WriteReceipt` cannot identify which revision a
commit produced. The revision data the feature needs already exists durably one
layer down, inside `emg-persistence`, which the service must never import directly.
This ADR decides the exact shape of the new read-only capability, where it lives,
what it returns, how restore commits are identified, and how existing invariants
(tenant isolation, principal attribution, optimistic concurrency, transactional
outbox/projection) are preserved rather than re-implemented.

## 5. Existing Architecture

(Established by the prior read-only discovery; restated here only as decision input,
not re-derived.)

- `services/knowledge-graph/src/emg_knowledge_graph/{service,commands,results,errors}.py`
  — `KnowledgeGraphApplication.build_revision`, `BuildRevisionCommand`,
  `BuildRevisionResult`, `InvalidRevisionCommandError`, `RevisionBuildError`.
- `emg_platform_core.ports.graph_store` — `GraphStore`, `GraphTransaction`,
  `WriteReceipt`. Implemented by `InMemoryGraphStore` (`adapters/in_memory.py`) and
  `PostgresNeo4jGraphStore` (`emg-persistence/store.py`).
- `emg_persistence.revisions.{model,repository,in_memory}` and
  `postgres/revision_repository.py` — `Revision`, `RevisionHead`,
  `RevisionRepository` Protocol and its two implementations.
- `emg_memory_graph.versioning` — `GraphDiff`, `diff_graphs`, `GraphHistory`,
  `GraphRevision` (the latter two unused in production).
- `emg_persistence.outbox` — `OutboxEvent`, written atomically with each appended
  revision; consumed only by the internal `ProjectionWorker`.

## 6. Decision Drivers

- PostgreSQL remains authoritative; no schema change should be introduced unless a
  genuine new fact must be stored (none was found — see §3).
- Historical reads must never load more than the caller asked for; listing must not
  deserialize `graph_json` for every revision.
- The service must keep depending only on `emg-platform-core` and `emg-memory-graph`
  — the existing dependency-boundary test's forbidden-import list must remain
  satisfied without modification to its intent.
- A second, competing "revision" abstraction must not be introduced — one canonical,
  tenant-scoped, persistence-independent revision-metadata shape is required.
- Restore must reuse the existing transaction, concurrency, outbox, and projection
  machinery unchanged — it is a new *caller* of `_persist()`'s existing logic, not a
  new commit path.
- A caller must be able to learn the revision number a commit produced without a
  second list/read round trip, and without racing another writer between commit and
  that second read.
- Every new port method must be addable to `InMemoryGraphStore` and
  `PostgresNeo4jGraphStore` without breaking any existing test in
  `test_revision_workflow.py` or the persistence contract-test suite.

## 7. Considered Options

**Option 1 — Add historical methods directly to `GraphStore`.** Rejected as the
primary design. It would make every current-state consumer of `GraphStore`
structurally depend on history capability even when it never asks for it, and it
blurs a Protocol that ADR-022 deliberately kept minimal ("read current graph, write
graph, open transaction"). A read-only historical capability is a distinct
responsibility from current-state read/write and deserves a distinct, composable
Protocol.

**Option 2 — New `GraphRevisionReader` port, separate from `GraphStore`.**
**Selected.** Keeps `GraphStore` exactly as ADR-022 left it. Adapters that support
history implement both Protocols; `KnowledgeGraphApplication` receives both via
constructor injection. New capability is additive and optional per-adapter.

**Option 3 — Reuse `emg_memory_graph.versioning.GraphHistory` as the persistence
port.** Rejected. `GraphHistory` is not tenant-scoped (it has no `TenantId` field or
parameter anywhere in its API), has no relationship to the PostgreSQL-authoritative
`Revision`/`RevisionHead` rows, and embeds the entire `MemoryGraph` inline in every
`GraphRevision` with no lazy-loading story — using it here would mean either loading
every historical graph into memory just to build a `GraphHistory` instance, or
maintaining two independently-updated revision chains for the same tenant data.
Reusing it would recreate exactly the two-incompatible-abstractions problem
ADR-022 was written to resolve, one layer higher. `diff_graphs`/`GraphDiff` from the
same module are reused (§14) — only the chain/container types are rejected.

**Option 4 — Extend `WriteReceipt` with commit-identity fields.** **Selected**
(§11). The alternative (a second call after commit to discover what was just
committed) is explicitly disallowed by this ADR because it is race-unsafe — another
writer could append a revision between the commit and the follow-up read, and the
caller would learn the wrong revision number.

**Option 5 — A caller-side second `read_revision`/`list_revisions` call
immediately after `write()`/`transaction()` to learn the resulting revision
number.** Rejected outright — race-unsafe by construction, explicitly excluded by
the task driving this ADR, and unnecessary once Option 4 is adopted.

## 8. Decision

1. Add a new, read-only, tenant-scoped port, `GraphRevisionReader`, in
   `emg-platform-core`, alongside `GraphStore` but not merged into it.
2. Add a new, persistence-independent, immutable `RevisionMetadata` type in the same
   package, replacing any need to expose `emg_persistence.revisions.Revision` across
   the service boundary.
3. Extend `WriteReceipt` with `revision_number`, `committed_at`, and
   `revision_created`, computed from information the adapters already produce
   internally today and currently discard.
4. `KnowledgeGraphApplication` receives an optional `GraphRevisionReader` via
   constructor injection (alongside the existing `GraphStore`/`MemoryGraphBuilder`)
   and gains `list_revisions`, `read_revision`, `compare_revisions`, and
   `restore_revision` orchestration methods, each following the existing
   validate-before-transaction, thin-orchestrator pattern `build_revision` already
   established.
5. Restore is implemented as: validate command → `GraphRevisionReader.read_revision`
   → one `GraphStore.transaction(tenant, principal)` → `stage()` the historical
   graph directly, unmodified → commit → map the receipt to
   `RestoreRevisionResult`. No new persistence primitive is introduced.
6. Diffing reuses `diff_graphs`/`GraphDiff` unchanged; `RevisionDiff` wraps
   `GraphDiff` with tenant/revision context rather than copying its fields.
7. Read-only queries (`ListRevisionsQuery`, `GetRevisionQuery`,
   `CompareRevisionsQuery`) do not carry `PrincipalRef`. `RestoreRevisionCommand`
   does, because it performs a commit.
8. No PostgreSQL schema or migration change is required. Adapter-internal changes
   only (§18).

## 9. Port Contracts

New module: `libs/python/emg-platform-core/src/emg_platform_core/ports/graph_revision_reader.py`.

```python
"""Read-only historical revision access — a companion to GraphStore.

GraphRevisionReader is deliberately separate from GraphStore: it has no write
methods, and an adapter may implement GraphStore without implementing this port
(see UnsupportedHistoryCapabilityError). Both existing adapters
(InMemoryGraphStore, PostgresNeo4jGraphStore) are expected to implement both
Protocols once Sprint 7.2 lands.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..identity import TenantId
from .revision_metadata import HistoricalGraphRevision, RevisionMetadata

DEFAULT_REVISION_LIST_LIMIT = 50
MAX_REVISION_LIST_LIMIT = 200


@runtime_checkable
class GraphRevisionReader(Protocol):
    """Read-only access to a tenant's immutable revision history."""

    def list_revisions(
        self,
        tenant: TenantId,
        *,
        limit: int = DEFAULT_REVISION_LIST_LIMIT,
        before_revision_number: int | None = None,
    ) -> tuple[RevisionMetadata, ...]:
        """Return up to ``limit`` revisions for ``tenant``, newest first.

        Ordered strictly descending by ``revision_number``. When
        ``before_revision_number`` is given, only revisions with
        ``revision_number < before_revision_number`` are eligible (paging
        strictly further into the past). ``limit`` must be in
        ``[1, MAX_REVISION_LIST_LIMIT]``. Never deserializes ``graph_json``;
        returns an empty tuple for a tenant with no revisions.
        """
        ...

    def read_revision(
        self, tenant: TenantId, revision_number: int
    ) -> HistoricalGraphRevision:
        """Return the exact metadata and MemoryGraph for one revision.

        Raises RevisionNotFoundError if ``tenant`` has no revision numbered
        ``revision_number``. Raises SnapshotIntegrityError if the stored
        payload's recomputed content hash does not match the stored
        content_hash. Never raises a driver/database exception directly.
        """
        ...
```

**Should `GraphStore` implementations also implement `GraphRevisionReader`?**
Yes, structurally — both `InMemoryGraphStore` and `PostgresNeo4jGraphStore` are
expected to implement both Protocols. This is a convention, not an inheritance
requirement: `GraphRevisionReader` is not a subtype of `GraphStore` and does not
appear in `GraphStore`'s own definition. A future adapter may legitimately implement
only `GraphStore` (e.g. a minimal test double) and simply not implement
`GraphRevisionReader` at all — `isinstance(adapter, GraphRevisionReader)` (runtime-
checkable) is the way `KnowledgeGraphApplication`'s history methods could confirm
support if the reader is not supplied at construction time.

**Adapter without history support.** `KnowledgeGraphApplication` accepts
`graph_revision_reader: GraphRevisionReader | None = None`. If history methods are
called with no reader configured, the application raises its own
`UnsupportedHistoryCapabilityError` (application-level, §17) before any store
interaction — this is a configuration error, not a per-call adapter failure.
`UnsupportedHistoryCapabilityError` is retained (yes) as a platform-core error type
as well, reserved for an adapter that declares `GraphRevisionReader` conformance but
cannot serve a specific tenant/revision's history (e.g. a future adapter with
partial history retention) — neither current adapter is expected to raise it.

## 10. Canonical Revision Metadata

Same module family as §9:
`libs/python/emg-platform-core/src/emg_platform_core/ports/revision_metadata.py`.

```python
"""Persistence-independent revision metadata and full historical reads.

RevisionMetadata mirrors emg_persistence.revisions.model.Revision's canonical
fields exactly, minus graph_json — it is the one shape services are permitted
to see across the GraphRevisionReader boundary. emg_persistence.revisions.Revision
itself must never cross into services/knowledge-graph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..identity import PrincipalRef, TenantId
from emg_memory_graph import MemoryGraph

HexHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RevisionMetadata(BaseModel):
    """Canonical, immutable metadata for one committed tenant revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    revision_number: int = Field(ge=1)
    content_hash: HexHash
    parent_hash: HexHash | None = None
    principal: PrincipalRef
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    created_at: datetime


class HistoricalGraphRevision(BaseModel):
    """One fully-read historical revision: metadata plus its exact graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: RevisionMetadata
    graph: MemoryGraph
```

Decisions:

- **Exact type names:** `RevisionMetadata` (list results) and
  `HistoricalGraphRevision` (single full read). No separate "`RevisionSummary`"
  name at the platform-core layer — the application-layer `RevisionSummary` DTO
  (§12) is a thin re-export/alias of `RevisionMetadata`, kept distinct only so the
  service package never imports a platform-core type directly into its public
  surface (matching the existing pattern where `BuildRevisionResult` is its own
  type rather than a bare `WriteReceipt`).
- **`revision_number` stays a plain `int`** (`Field(ge=1)`), not a value object.
  Every existing revision-carrying type (`RevisionHead`, `Revision`,
  `OutboxEvent.revision_number`) already uses plain `int`; introducing a wrapper
  type here would create an inconsistency with those existing, unmodified types
  for no demonstrated benefit (no polymorphic revision-id scheme exists or is
  planned).
- **`parent_hash` is `None` if and only if `revision_number == 1`** — identical
  semantics to `emg_persistence.revisions.model.Revision.parent_hash`, restated at
  the platform-core layer. This invariant is enforced by the adapter producing
  `RevisionMetadata`, not by a validator on the model itself (mirroring how
  `Revision` today leaves this invariant to `PostgresNeo4jGraphStore._revision_for`
  rather than a field validator).
- **Ordering guarantee:** `list_revisions` returns strictly descending
  `revision_number` (newest first). This is a deliberate choice for history-
  navigation UX (most recent changes surface first) and pairs naturally with
  `before_revision_number` as an exclusive "older than" cursor.
- **The full `MemoryGraph` does not belong in `RevisionMetadata`.** It belongs only
  in `HistoricalGraphRevision.graph`, so that `list_revisions` can never be made to
  deserialize `graph_json` by a careless caller reusing the same type for both
  purposes.
- **Combined vs. separate full-read result:** `read_revision` returns
  `HistoricalGraphRevision` (metadata + graph combined), not two separate calls or
  return values. Every caller (`read_revision`, `compare_revisions`,
  `restore_revision`) needs the graph *and* its revision context together; a split
  API would force two round-trips or force callers to manually pair a metadata
  object with a graph object with no compiler-enforced correspondence.

## 11. WriteReceipt Decision

`WriteReceipt` is extended (Option 4 from §7) with three new required fields:

```python
class WriteReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    principal: PrincipalRef
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    # --- new in ADR-023 ---
    revision_number: int = Field(ge=1)
    committed_at: datetime
    revision_created: bool
```

Semantics:

- **No-op write** (staged content hash equals the current head's content hash):
  `revision_number` identifies the *current authoritative head* (unchanged),
  `revision_created` is `False`, and `committed_at` reflects the timestamp the head
  revision was originally created at — **not** the wall-clock time of the no-op
  call, since no new commit occurred and fabricating a fresh timestamp for nothing
  would misrepresent when the returned content was actually committed. No new
  outbox event is created, exactly as `_persist()` already guarantees today.
- **Actual append:** `revision_number` identifies the newly created revision,
  `revision_created` is `True`, `committed_at` is the new revision's `created_at`
  (server clock at commit, the same clock `_revision_for()` already uses).
- Both adapters already compute everything required for these fields internally —
  `PostgresNeo4jGraphStore._persist()` already builds a `Revision` with
  `revision_number`/`created_at` (for the appended case) and already knows the
  existing head's `revision_number`/hence its `Revision.created_at` via
  `get_revision(tenant, head.revision_number)` (for the no-op case) — this is a
  matter of *not discarding* data already computed, not new computation.
- **The application must never infer `revision_number` via a second list/read call
  after commit.** `WriteReceipt` is the single, race-safe source of that
  information, returned atomically with the commit itself.

**Backward compatibility.** `WriteReceipt` is constructed in exactly two places
today: `PostgresNeo4jGraphStore._receipt_for()`
(`emg-persistence/src/emg_persistence/store.py`) and `InMemoryGraphStore._receipt_for()`
(`emg-platform-core/src/emg_platform_core/adapters/in_memory.py`). No other module
in the repository constructs a `WriteReceipt` directly (confirmed by repository-wide
search); every other reference only *reads* its existing fields. The three new
fields are required, not defaulted — a silently-defaulted `revision_number` (e.g.
`0`) would be actively misleading, and since both construction sites are internal
factory functions under this ADR's direct control, there is no external caller whose
construction call would break. Both factory functions must be updated in the
implementation PR to compute and pass all three new fields; every *consumer* of an
already-constructed `WriteReceipt` (e.g. `BuildRevisionResult`'s mapping in
`build_revision`) continues to work unchanged, since consumption only reads existing
fields today — extending `BuildRevisionResult`/`RestoreRevisionResult` to also
surface `revision_number` is a §12 application-layer decision, not a breaking change
to `WriteReceipt` consumption.

## 12. Application Contracts

All new types are immutable (`@dataclass(frozen=True, slots=True)`, matching
`BuildRevisionCommand`/`BuildRevisionResult`). Validation lives on the
command/query object's own `validate()` method, called by
`KnowledgeGraphApplication` before any port interaction — exactly the existing
`build_revision` pattern. None of the new types import or expose
`emg_persistence.revisions.Revision`; `RevisionSummary`/`RevisionDetails` are
built from the platform-core `RevisionMetadata`/`HistoricalGraphRevision` types
only.

```python
# commands.py / queries — services/knowledge-graph/src/emg_knowledge_graph

@dataclass(frozen=True, slots=True)
class ListRevisionsQuery:
    tenant: TenantId
    limit: int = DEFAULT_REVISION_LIST_LIMIT
    before_revision_number: int | None = None

    def validate(self) -> None:
        """Reject a missing tenant, an out-of-range limit, or a non-positive cursor."""
        ...


@dataclass(frozen=True, slots=True)
class RevisionSummary:
    tenant: TenantId
    revision_number: int
    content_hash: str
    parent_hash: str | None
    principal: PrincipalRef
    node_count: int
    edge_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GetRevisionQuery:
    tenant: TenantId
    revision_number: int

    def validate(self) -> None:
        """Reject a missing tenant or revision_number < 1."""
        ...


@dataclass(frozen=True, slots=True)
class RevisionDetails:
    summary: RevisionSummary
    graph: MemoryGraph


@dataclass(frozen=True, slots=True)
class CompareRevisionsQuery:
    tenant: TenantId
    from_revision_number: int
    to_revision_number: int

    def validate(self) -> None:
        """Reject a missing tenant or either revision_number < 1.

        Does NOT reject from_revision_number > to_revision_number (reverse
        comparison is valid, see Section 14), and does NOT reject
        from_revision_number == to_revision_number (self-comparison is valid,
        see Section 14).
        """
        ...


@dataclass(frozen=True, slots=True)
class RevisionDiff:
    tenant: TenantId
    from_revision_number: int
    to_revision_number: int
    diff: GraphDiff  # emg_memory_graph.versioning.GraphDiff, reused as-is


@dataclass(frozen=True, slots=True)
class RestoreRevisionCommand:
    tenant: TenantId
    principal: PrincipalRef
    source_revision_number: int

    def validate(self) -> None:
        """Reject a missing tenant/principal or source_revision_number < 1."""
        ...


@dataclass(frozen=True, slots=True)
class RestoreRevisionResult:
    tenant: TenantId
    principal: PrincipalRef
    source_revision_number: int
    revision_number: int
    content_hash: str
    node_count: int
    edge_count: int
    committed_at: datetime
    revision_created: bool
```

`KnowledgeGraphApplication` gains:

```python
def list_revisions(self, query: ListRevisionsQuery) -> tuple[RevisionSummary, ...]: ...
def read_revision(self, query: GetRevisionQuery) -> RevisionDetails: ...
def compare_revisions(self, query: CompareRevisionsQuery) -> RevisionDiff: ...
def restore_revision(self, command: RestoreRevisionCommand) -> RestoreRevisionResult: ...
```

Each method: validate the query/command (raising before any port call, matching
`test_invalid_command_is_rejected_before_transaction`'s existing assertion style) →
call the appropriate port method(s) → map the result into the DTOs above → catch and
translate the typed errors named in §17. `KnowledgeGraphApplication` remains a pure
orchestrator: no diffing logic, no SQL, no revision-numbering logic lives in this
class, matching `build_revision`'s existing division of responsibility.

## 13. List/Read Semantics

- **Ordering:** `list_revisions` returns strictly descending `revision_number`
  (newest first) — see §10.
- **Paging:** `limit` defaults to `DEFAULT_REVISION_LIST_LIMIT = 50`, bounded by
  `MAX_REVISION_LIST_LIMIT = 200`; a query requesting more than the maximum is
  rejected by `ListRevisionsQuery.validate()` before any store interaction, not
  silently clamped. `before_revision_number`, when supplied, restricts results to
  `revision_number < before_revision_number` (an exclusive, strictly-older cursor);
  omitted, listing starts from the current head.
- **Not-found behavior:** `read_revision`/`GetRevisionQuery` for a `revision_number`
  that does not exist for the given tenant raises `RevisionNotFoundError` (§17).
  `list_revisions` never raises not-found — a tenant with zero revisions (or zero
  revisions older than a given cursor) simply returns an empty tuple.
- **Tenant isolation:** every query is scoped by `tenant` at the repository-query
  level (`WHERE tenant_id = ...`), never filtered after a broader fetch. A
  `revision_number` that exists for a different tenant produces the identical
  `RevisionNotFoundError` as a `revision_number` that does not exist at all — the
  response must not reveal whether the number is in use by another tenant (§22).
- **Snapshot integrity:** `read_revision`'s full-graph path reuses the exact
  deserialize-then-verify behavior `PostgresNeo4jGraphStore._deserialize_snapshot`
  already implements today (recompute `MemoryGraph.content_hash()` on the
  deserialized payload; compare to the stored `content_hash`; raise on mismatch).
  This is not new logic — it is the same check already guarding head reads, now
  also guarding historical reads.
- **Listing must not deserialize `graph_json`.** The new `RevisionRepository`
  method backing `list_revisions` selects only `revision_number, content_hash,
  parent_hash, principal_id, principal_kind, node_count, edge_count, created_at` —
  never `graph_json` — for every row it returns (§18).

## 14. Diff Semantics

`RevisionDiff` **wraps** `GraphDiff` (adds `tenant`/`from_revision_number`/
`to_revision_number` context fields alongside an unmodified `diff: GraphDiff`
field) rather than copying `GraphDiff`'s six tuple fields onto a new type. Wrapping
means any future change to `GraphDiff`'s shape is inherited automatically instead of
requiring `RevisionDiff` to be kept in sync by hand — the two rejected-duplication
risk this ADR flags in §26.

No new diff engine is implemented. `compare_revisions` calls `read_revision` twice
(via `GraphRevisionReader.read_revision`, reusing its integrity verification both
times) and passes the two resulting graphs to the existing
`diff_graphs(before, after) -> GraphDiff`.

- **Self-comparison** (`from_revision_number == to_revision_number`) is valid input
  and returns an empty `GraphDiff` (`is_empty is True`) — not rejected by
  `CompareRevisionsQuery.validate()`.
- **Forward comparison** (`from < to`, the common case) calls
  `diff_graphs(graph_at(from), graph_at(to))` directly.
- **Reverse comparison** (`from > to`) is valid and is **not** rejected — the
  domain does not require chronological-only comparison (a caller may legitimately
  want "what would I undo to go from revision 10 back to revision 4"). Reverse
  comparison calls `diff_graphs(graph_at(from), graph_at(to))` with the arguments
  in the order the caller specified: `added_nodes`/`added_edges` in the result then
  mean "present at `to` but not at `from`" exactly as `diff_graphs`'s existing
  contract already defines for any two graphs, regardless of which one is
  chronologically earlier. No special-casing or argument-swapping is introduced.

## 15. Restore Semantics

Adopted, unmodified, as the binding sequence:

1. Validate `RestoreRevisionCommand` (tenant, principal, `source_revision_number`
   present and well-formed) — before any port call.
2. Read the historical `MemoryGraph` via
   `GraphRevisionReader.read_revision(tenant, source_revision_number)`.
3. Open exactly one `GraphStore.transaction(tenant, principal)` — `principal` here
   is the **restoring** principal (the caller performing this restore), which is
   distinct from, and does not alter, the historical revision's own immutably
   recorded `principal`.
4. `transaction.stage(historical_graph)` — the historical graph is staged
   **directly**, with no re-validation and no pass through `MemoryGraphBuilder`.
   Restore is not an ontology-ingestion operation; `from_ontology()` is not called.
5. Exit the transaction context; commit proceeds through the existing,
   unmodified `_persist()` path (head comparison, `diff_graphs` no-op check,
   append-or-no-op, outbox event on append).
6. Map the resulting `WriteReceipt` (§11) plus `command.source_revision_number`
   into `RestoreRevisionResult`.

Guarantees preserved, all via existing unmodified machinery:

- **Never mutates or deletes history** — the source revision row is only ever read
  (`get_revision`), never updated; restore can only *append* a new revision or
  produce a no-op, exactly like `build_revision` today.
- **Preserves the source graph's internal temporal data exactly** — the staged
  graph is the historical `MemoryGraph` byte-for-byte (its nodes'/edges'
  `effective_from`/`effective_to`/`updated_at` values are untouched); nothing
  re-derives or rewrites them.
- **Attributes the new commit to the restoring principal** — `transaction(tenant,
  principal)` is opened with the command's `principal`, so the new `Revision.principal`
  is the restoring principal, not the historical one.
- **Retains optimistic concurrency** — the transaction re-reads the current head at
  open time exactly as `build_revision` does; a concurrent write between choosing
  `source_revision_number` and committing surfaces the existing
  `PersistenceConflictError` unsuppressed, per ADR-022's existing precedent
  (`test_optimistic_conflict_surfaces_without_suppression`).
- **Retains rollback behavior** — a staging/commit failure aborts the transaction
  with no partial revision, exactly as `test_staging_failure_rolls_back_and_surfaces_original_error`
  already proves for `build_revision`.
- **Retains outbox/projection behavior unchanged** — an actual append still writes
  its `graph.revision.committed` outbox row in the same PostgreSQL transaction;
  `ProjectionWorker` needs no changes.

**`RestoreRevisionCommand` contains only `tenant`, `principal`, and
`source_revision_number`** — `as_of` is explicitly **rejected** as a field. No
concrete domain meaning for a caller-supplied `as_of` was identified: restore does
not call `from_ontology()` (the only existing consumer of `as_of` semantics), so
there is no builder-evidence timestamp for it to feed. The commit's timestamp is
`WriteReceipt.committed_at`/`RestoreRevisionResult.committed_at` — server-clock,
computed at commit, not caller-supplied — and the graph's own internal
`effective_from`/`effective_to`/`updated_at` fields remain exactly as they were on
the source revision, untouched by the restore operation.

## 16. No-op Semantics

Restoring content identical to the current head is a **valid no-op**, not an error
— no evidence in the existing codebase supports treating it as invalid, and
`build_revision`'s existing no-op path (driven by the same `_persist()` logic)
already establishes this precedent for the build workflow. Expected result,
identical in spirit to the existing build no-op:

- No new revision row is created.
- No new outbox event is created.
- `RestoreRevisionResult.revision_number` equals the current head's
  `revision_number` (unchanged).
- `RestoreRevisionResult.revision_created` is `False`.
- `RestoreRevisionResult.source_revision_number` is still populated with whatever
  `source_revision_number` the caller requested, even though it happened to match
  the current head — the result must not hide what the caller asked to restore.

## 17. Error Model

All new errors derive from the existing `EMGError`-rooted hierarchy, following the
established two-tier convention (`PlatformCoreError`/`KnowledgeGraphApplicationError`
as package-level bases, concrete errors beneath).

**Platform-core** (`emg_platform_core/errors.py`, alongside the existing
`TransactionStateError`):

- `RevisionNotFoundError(PlatformCoreError)` — raised by a `GraphRevisionReader`
  implementation when `(tenant, revision_number)` does not resolve. Deliberately
  tenant-scoped in its implementation (query-time filtering) so that a wrong-tenant
  lookup and a genuinely-missing revision are indistinguishable to the caller.
- `SnapshotIntegrityError(PlatformCoreError)` — raised when a deserialized
  historical payload's recomputed content hash does not match its stored
  `content_hash` (mirrors the existing, unnamed hash-mismatch `PersistenceError`
  raised inline in `store.py` today; now given a dedicated, reusable type since two
  adapters and two call paths — head read and historical read — need to raise it
  consistently).
- `UnsupportedHistoryCapabilityError(PlatformCoreError)` — reserved for an adapter
  that implements `GraphRevisionReader` but cannot serve history for a specific
  case. Retained per §9 for forward compatibility; neither current adapter is
  expected to raise it.

**Application** (`services/knowledge-graph/src/emg_knowledge_graph/errors.py`,
alongside the existing three):

- `InvalidHistoryQueryError(KnowledgeGraphApplicationError)` — raised by
  `ListRevisionsQuery.validate()`/`GetRevisionQuery.validate()`/
  `CompareRevisionsQuery.validate()` for a missing tenant, an out-of-range
  `limit`, a non-positive cursor, or a non-positive `revision_number`. Covers
  invalid paging as a specific message on this one type — a dedicated
  "InvalidPagingError" is not introduced, to avoid proliferating near-identical
  error classes for what is, in every case, a malformed query object rejected
  before any store interaction.
- `RevisionNotFoundError(KnowledgeGraphApplicationError)` — the application's own
  type, raised by `read_revision`/`compare_revisions`/`restore_revision` by
  catching and wrapping the platform-core `RevisionNotFoundError` (`raise ... from
  cause`), consistent with how `RevisionBuildError` already wraps
  `MergeConflictError`. Not-found is treated as an expected business outcome
  (wrap, add tenant/revision context), unlike a concurrency conflict, which must
  remain unsuppressed and undisguised for retry logic (§15) — this asymmetry is
  intentional and mirrors ADR-022's existing distinction between build-failure
  wrapping and conflict pass-through.
- `RevisionRestoreError(KnowledgeGraphApplicationError)` — raised by
  `restore_revision` when staging/commit fails for a reason other than a
  concurrency conflict (mirrors `RevisionBuildError`'s wrap-with-cause style).
- `UnsupportedHistoryCapabilityError(KnowledgeGraphApplicationError)` — raised by
  `KnowledgeGraphApplication` itself when a history method is called but no
  `GraphRevisionReader` was supplied at construction — a configuration error,
  checked before any store interaction.

**Explicitly rejected:** a dedicated `CrossTenantAccessError` is **not** introduced.
No second security/authorization context exists yet against which a query's tenant
could be checked (authorization enforcement remains explicitly out of scope, as in
ADR-022). Tenant isolation here is structural — every repository query is filtered
by tenant at the source — not an access-control decision requiring its own error
type. A missing revision for one tenant and an existing revision belonging to
another tenant both surface as the same `RevisionNotFoundError`, by construction,
so no information about another tenant's data is ever revealed (§22).

Driver/database exceptions (`psycopg.Error` and subclasses) must never cross the
application boundary — the new `RevisionRepository`/`GraphRevisionReader` adapter
methods must wrap them in `PersistenceError`/platform-core errors exactly as every
existing `PostgresNeo4jGraphStore` method already does.

## 18. Persistence and Adapter Impact

No PostgreSQL table or column migration is required — `graph_revisions` already
carries every field `RevisionMetadata`/`HistoricalGraphRevision` need.

**`RevisionRepository` (Protocol, `emg-persistence/src/emg_persistence/revisions/repository.py`):**
add one new method,

```python
def list_revisions(
    self,
    tenant: TenantId,
    *,
    limit: int,
    before_revision_number: int | None,
) -> tuple[RevisionRecord, ...]:
    """Return up to `limit` revision records for `tenant`, newest first,
    strictly older than `before_revision_number` when given. Never includes
    graph_json."""
    ...
```

where `RevisionRecord` is a new, persistence-internal, metadata-only sibling of
`Revision` (same fields, minus `graph_json`), added to
`emg-persistence/src/emg_persistence/revisions/model.py`. `RevisionRecord` never
crosses the service boundary — `PostgresNeo4jGraphStore`'s `GraphRevisionReader`
implementation maps each `RevisionRecord` into a platform-core `RevisionMetadata`
before returning it.

**`PostgresRevisionRepository`:** implements `list_revisions` with a new query
selecting exactly `revision_number, content_hash, parent_hash, principal_id,
principal_kind, node_count, edge_count, created_at` — deliberately omitting
`graph_json` — filtered by `tenant_id` and, when supplied,
`revision_number < %(before)s`, ordered `ORDER BY revision_number DESC LIMIT
%(limit)s`.

**`InMemoryRevisionRepository`:** implements the same method over its existing
in-memory `dict[str, dict[int, Revision]]`, sorting and slicing in Python; still
never constructs a payload containing `graph_json` for list results (it can simply
omit that field when building the `RevisionRecord` view, since it already holds the
full `Revision` in memory).

**`PostgresNeo4jGraphStore`:** implements `GraphRevisionReader.list_revisions` by
delegating to `RevisionRepository.list_revisions` and mapping each `RevisionRecord`
to `RevisionMetadata`. Implements `read_revision` by delegating to the existing
`RevisionRepository.get_revision` + the existing `_deserialize_snapshot`
integrity-verification helper (already used by `_load_head_snapshot` today),
wrapping a miss as `RevisionNotFoundError` and a hash mismatch as
`SnapshotIntegrityError` instead of the current inline, unnamed `PersistenceError`.
Also updates `_receipt_for()` to populate `WriteReceipt`'s three new fields (§11),
using the `Revision`/head data `_persist()` already computes.

**`InMemoryGraphStore`:** the one adapter with a genuine behavioral gap — today it
keeps exactly one `MemoryGraph` per tenant and fully overwrites it on every
`write()`/`transaction()` commit, retaining no history at all. It must change to
retain an ordered, immutable, append-only list of revisions per tenant (mirroring
`InMemoryRevisionRepository`'s existing shape) while preserving every existing
`GraphStore` behavior unchanged: `read(tenant)` continues to return the current
(latest) graph, `write`/`transaction` continue to behave exactly as today for every
existing caller, and its `_receipt_for()` gains the same three new `WriteReceipt`
fields computed from its own now-retained history. It additionally implements
`GraphRevisionReader.list_revisions`/`read_revision` against that retained history.
This change must not alter the observable behavior of any existing test in
`test_revision_workflow.py`, `test_dependency_boundary.py`, or `test_import.py` —
all of which only observe current-state behavior today.

## 19. Concurrency and Transaction Ownership

No new transaction-ownership model is introduced. `restore_revision` opens exactly
one `GraphStore.transaction(tenant, principal)`, identical in shape to
`build_revision`'s existing single-transaction pattern — never two transactions,
never a transaction spanning `GraphRevisionReader` and `GraphStore` together (the
historical read happens entirely before the write transaction opens). All existing
optimistic-concurrency guarantees (`compare_and_set_head`, `revalidate_head`,
`_persist()`'s diff-emptiness/hash-equality invariants) apply to a restore commit
exactly as they already apply to a build commit, without modification.
`GraphRevisionReader.read_revision` performs its own, separate, read-only
transaction/connection (or lock, for the in-memory adapter) — it does not read
inside the caller's eventual write transaction, since the historical revision being
restored is immutable and cannot change between the read and the subsequent write
transaction's own head check.

## 20. Outbox and Projection Behavior

Unchanged. An actual restore-triggered append still produces exactly one
`graph.revision.committed` outbox event, written in the same PostgreSQL transaction
as the new revision and head update, via the existing `_outbox_event_for()` — no
new event type is introduced for "this revision resulted from a restore" (the
outbox event's existing shape does not distinguish *how* a revision's content was
produced, only that one was committed; nothing in this ADR contradicts that). A
no-op restore creates no outbox event, exactly as a no-op build creates none today.
`ProjectionWorker` requires no changes — it already consumes `graph.revision.committed`
generically.

## 21. Dependency Boundaries

Confirmed, none newly introduced or violated:

- `services/knowledge-graph` may depend on `emg-platform-core` (already does) and
  `emg-memory-graph` (already does, for `MemoryGraphBuilder`; now additionally for
  `GraphDiff`/`MemoryGraph` in the new DTOs).
- `services/knowledge-graph` must not, and per the existing (unmodified)
  `test_dependency_boundary.py` AST check, cannot import `emg_persistence` or
  `emg_knowledge_pipeline.graph_store`. `RevisionMetadata`/`HistoricalGraphRevision`/
  `GraphRevisionReader` all live in `emg-platform-core`, so the new application
  types can be built entirely from platform-core and memory-graph imports.
- `emg-platform-core` may depend on `emg-memory-graph`, exactly as it already does
  today (`ports/graph_store.py` already imports `MemoryGraph` directly) — the new
  `ports/revision_metadata.py` module does the same, introducing no new coupling
  direction.
- `emg-persistence` continues to implement platform-core's ports
  (`GraphStore`, now also `GraphRevisionReader`) — the implementation direction is
  unchanged; persistence depends on platform-core and memory-graph, never the
  reverse.
- No circular dependency is introduced: `emg-memory-graph` does not import
  `emg-platform-core` or `emg-persistence`; `emg-platform-core` does not import
  `emg-persistence`; `emg-persistence` does not import `services/knowledge-graph`.

## 22. Security and Tenant Isolation

Every new port and repository method takes `tenant: TenantId` as a required,
non-optional parameter and filters at the query/lookup level — never by fetching
broadly and filtering in the application layer. `RevisionNotFoundError` is raised
identically whether a revision number is simply unused or is in use by a different
tenant, so no response distinguishes the two cases (§17). Principal-based
authorization (whether `PrincipalRef` may act for `tenant` at all) remains, as in
ADR-022, explicitly out of scope — this ADR only guarantees that queries are
tenant-scoped by construction, not that principals are authorized against tenants.
Read-only queries do not carry `PrincipalRef` (§ "Read principal decision" below);
`RestoreRevisionCommand` does, because it performs a commit and must attribute it.

**Read principal decision:** Option 1 is adopted — `ListRevisionsQuery`,
`GetRevisionQuery`, and `CompareRevisionsQuery` do **not** contain `PrincipalRef`.
No read-audit or read-authorization mechanism exists anywhere in the repository
today, and adding a field for a capability that does not exist would be exactly the
kind of speculative, hypothetical-future-use addition this ADR is instructed to
avoid. `RestoreRevisionCommand` **does** contain `principal`, unconditionally,
because it is a write/commit operation requiring attribution, identical in kind to
`BuildRevisionCommand.principal` today.

## 23. Test Strategy

At minimum, extending the existing `test_revision_workflow.py`-style conventions
(deterministic `InMemoryGraphStore`/in-memory revision repository, no live
PostgreSQL/Neo4j required) with a new `test_revision_history.py`:

Empty history (zero revisions lists as an empty tuple); first revision (a tenant
with exactly one commit lists and reads it correctly); multiple-revision ordering
(list returns strictly descending `revision_number`); bounded pagination
(`limit`/`before_revision_number` produce the exact expected page, and a
`limit` above `MAX_REVISION_LIST_LIMIT` is rejected before any store call); tenant
isolation (tenant A's history never appears in tenant B's list/read/compare, and a
revision number valid for A but not B raises the same not-found error for B as a
genuinely-unused number); historical non-head read (reading revision N-1 while
revision N is current returns exactly revision N-1's graph, not the current one);
revision-not-found (a nonexistent `revision_number` raises `RevisionNotFoundError`);
snapshot-integrity verification (a corrupted/mismatched stored hash raises
`SnapshotIntegrityError`, exercised against the persistence adapter's test double);
metadata listing without graph deserialization (a repository-level test asserting
`list_revisions`'s underlying query never touches/needs `graph_json`, e.g. by
constructing a `RevisionRecord` fixture that structurally has no `graph_json`
field at all); equal-revision comparison returning an empty diff; forward
comparison and reverse comparison both producing the diff `diff_graphs` would
naturally produce for the given argument order; node additions/removals/
modifications and edge additions/removals/modifications between two known
revisions (extending, not duplicating, the existing `diff_graphs` unit tests);
temporal edge identity preserved across a restore/compare, reusing the existing
`test_temporal_relationship_versions_remain_distinct` fixtures; restore creates a
new immutable revision with an incremented `revision_number` and correct
`parent_hash`; the source revision provably remains byte-for-byte unchanged after a
restore (re-read it and compare); restoring principal attribution (the new
revision's principal is the restoring principal, not the historical one); restoring
the current revision is a no-op (`revision_created is False`); a no-op returns the
current head's `revision_number` unchanged; a no-op creates no outbox event
(assertable against the same `RecordingStore`-style test double
`test_revision_workflow.py` already uses); rollback on staging/commit failure
(mirroring `test_staging_failure_rolls_back_and_surfaces_original_error`);
optimistic-concurrency conflict during restore surfaces unsuppressed (mirroring
`test_optimistic_conflict_surfaces_without_suppression`); every new query/command's
`validate()` rejects invalid input before any store call, verified via a
call-counter test double (mirroring `test_invalid_command_is_rejected_before_transaction`);
`test_dependency_boundary.py`'s existing forbidden-import/forbidden-type-name
checks continue to pass unmodified against every new module added to the package
(no new file should need an exception carved into that test); and every existing
Sprint 7.1 test in `test_revision_workflow.py` continues to pass unmodified,
proving `build_revision` behavior is unaffected by this ADR's changes.

## 24. Migration and Implementation Sequence

1. Add `RevisionRecord` to `emg-persistence/revisions/model.py` and the new
   `list_revisions` method to `RevisionRepository` (Protocol) plus both
   implementations — fully internal to `emg-persistence`, no port change yet, and
   independently testable.
2. Add `emg_platform_core.ports.revision_metadata` (`RevisionMetadata`,
   `HistoricalGraphRevision`) and `emg_platform_core.ports.graph_revision_reader`
   (`GraphRevisionReader`, limit constants) — pure new additions, no existing file
   touched.
3. Extend `WriteReceipt` with the three new fields (§11) and update both
   `_receipt_for()` factory functions — the one change in this sequence that
   touches an existing, shared type; do this in its own isolated step so its test
   impact is easy to review separately.
4. Update `InMemoryGraphStore` to retain history and implement
   `GraphRevisionReader`; update `PostgresNeo4jGraphStore` to implement
   `GraphRevisionReader` and the new `RevisionNotFoundError`/
   `SnapshotIntegrityError` wrapping.
5. Add the new command/query/result/error types to `services/knowledge-graph`
   (pure data, reviewable independent of behavior).
6. Add `list_revisions`/`read_revision`/`compare_revisions` to
   `KnowledgeGraphApplication` — read-only, lower risk, independently testable
   before restore.
7. Add `restore_revision` last, since it is the only new method that opens a write
   transaction and carries the concurrency/rollback risk the other three do not.
8. Extend `test_dependency_boundary.py` and add `test_revision_history.py` per §23,
   confirming every existing Sprint 7.1 test still passes unmodified.

## 25. Consequences

**Positive:** one canonical, tenant-scoped, persistence-independent revision-history
capability, additive to and non-competing with the existing `GraphStore` contract;
zero schema migration; the proven `diff_graphs` function finally gets a real caller;
`WriteReceipt` becomes race-safe for identifying what a commit produced, closing the
gap ADR-022 explicitly flagged; restore reuses every existing durability/concurrency
guarantee rather than introducing a parallel commit path.

**Negative:** `WriteReceipt` gains required fields, touching two existing internal
factory functions (small, mechanical, but real); `InMemoryGraphStore` gains real
internal complexity (retaining history) it did not have before, though its external
`GraphStore` behavior is unchanged; two Protocols (`GraphStore`,
`GraphRevisionReader`) must now be kept in mind together by anyone reading or
implementing a new adapter, rather than one.

## 26. Risks

| Risk | Mitigation |
| --- | --- |
| A future adapter implements `GraphStore` but forgets `GraphRevisionReader`, silently degrading history features | `KnowledgeGraphApplication` requires an explicit `graph_revision_reader` constructor argument (not auto-detected), and raises `UnsupportedHistoryCapabilityError` immediately if history methods are called without one configured |
| `RevisionMetadata` drifts out of sync with `emg_persistence.revisions.Revision`'s field set over time | Both are reviewed together in this ADR (§10); any future field added to `Revision` should be evaluated for whether it belongs in `RevisionMetadata` too, as part of that future change, not assumed automatically |
| Listing accidentally deserializes `graph_json` under future maintenance | `RevisionRecord`/the new SQL query structurally omit the column; a future accidental join reintroducing it would need to add the column back explicitly, a visible diff |
| `WriteReceipt`'s new required fields break an unanticipated third construction site | Confirmed by repository-wide search that exactly two factory functions construct it; this should be re-verified against the working tree at implementation time, not assumed frozen |
| Restore is mistaken for a "revert last N revisions" or branching feature | This ADR scopes restore strictly to "stage one historical graph as the next revision"; no branching, no multi-revision revert, no history rewriting is in scope, per §15 |
| Reverse/self comparison being accepted (§14) surprises a caller expecting only chronological comparisons | Documented explicitly in this ADR and in the query's own docstring; no enforcement was found to be required by any existing domain rule |

## 27. Deferred Work

- HTTP/API transport for any of these operations (unchanged non-goal from ADR-022).
- Authentication, authorization, and tenant-authorization policy enforcement for
  read operations (Option 1 of §22/"Read principal decision" — revisit only if a
  concrete read-audit or read-authorization requirement is approved).
- Mutation-audit reconciliation (still deferred per ADR-022, unrelated to this ADR).
- External outbox relay/broker integration (unchanged non-goal).
- Bulk/multi-revision revert, branching, or history rewriting of any kind.
- Deprecation/removal of `emg_knowledge_pipeline.graph_store` (unrelated, tracked
  separately per ADR-022 §11).
- Any change to `emg_memory_graph.versioning.GraphHistory`/`GraphRevision` — they
  remain unused, and this ADR does not schedule their removal, only declines to
  reuse them here.

## 28. Compliance Checklist

- [ ] `GraphRevisionReader` added to `emg-platform-core`, structurally separate
      from `GraphStore`, with no write methods.
- [ ] `RevisionMetadata`/`HistoricalGraphRevision` added to `emg-platform-core`;
      `emg_persistence.revisions.Revision` never imported by `services/knowledge-graph`.
- [ ] `WriteReceipt` extended with `revision_number`/`committed_at`/`revision_created`;
      both existing `_receipt_for()` factories updated; no-op vs. append semantics
      match §11 exactly.
- [ ] `services/knowledge-graph` gains only immutable, self-validating command/query
      types and thin orchestrator methods; no business logic added to
      `KnowledgeGraphApplication` beyond coordination.
- [ ] `list_revisions` never deserializes `graph_json`; verified by a dedicated test.
- [ ] `read_revision` reuses existing hash-verification logic; a mismatch raises
      `SnapshotIntegrityError`, not a generic error.
- [ ] Restore opens exactly one `GraphStore` transaction, stages the historical
      graph unmodified, and never touches `emg_persistence.revisions.Revision`
      history rows other than reading them.
- [ ] No PostgreSQL migration is added.
- [ ] `test_dependency_boundary.py` passes unmodified against every new module.
- [ ] Every existing Sprint 7.1 test in `test_revision_workflow.py` passes
      unmodified.
- [ ] No `CrossTenantAccessError` type introduced.
- [ ] `RestoreRevisionCommand` has no `as_of` field.

---

## Decisions Made

- New port `GraphRevisionReader` (`emg_platform_core.ports.graph_revision_reader`),
  read-only, separate from `GraphStore`.
- New canonical types `RevisionMetadata` and `HistoricalGraphRevision`
  (`emg_platform_core.ports.revision_metadata`).
- `WriteReceipt` extended with `revision_number`, `committed_at`, `revision_created`
  (required fields; both existing factory functions updated).
- `list_revisions`/`read_revision` contracts fixed: descending order, bounded/
  exclusive-cursor paging, combined metadata+graph full-read result, mandatory
  hash-verification reuse, no `graph_json` in listings.
- Restore sequence adopted exactly as proposed: read historical graph → one
  `GraphStore` transaction → stage directly → commit → map receipt.
  `RestoreRevisionCommand` carries only `tenant`, `principal`,
  `source_revision_number` — no `as_of`.
- Restoring the current revision is a valid no-op with the exact semantics
  specified in §16.
- `RevisionDiff` wraps `GraphDiff`; self- and reverse-comparison are both valid.
- Read-only queries do not carry `PrincipalRef` (Option 1); `RestoreRevisionCommand`
  does.
- Error taxonomy fixed per §17, including the explicit rejection of
  `CrossTenantAccessError`.
- No PostgreSQL schema/migration change; adapter-only impact per §18.

## Rejected Alternatives

- Adding historical methods directly onto `GraphStore` (Option 1, §7).
- Reusing `emg_memory_graph.versioning.GraphHistory`/`GraphRevision` as the
  persistence port (Option 3, §7) — not tenant-scoped, not tied to the
  authoritative log, embeds full graphs per revision.
- Learning a commit's revision number via a second list/read call after commit
  (Option 5, §7) — race-unsafe, explicitly excluded.
- A dedicated `InvalidPagingError` type, separate from `InvalidHistoryQueryError`.
- A dedicated `CrossTenantAccessError` type, absent an actual second security
  context.
- Including `as_of` on `RestoreRevisionCommand`.
- Copying `GraphDiff`'s fields onto `RevisionDiff` instead of wrapping.
- Rejecting self-comparison or reverse comparison in `CompareRevisionsQuery`.

## Exact Future Files Expected to Change

- `libs/python/emg-platform-core/src/emg_platform_core/ports/revision_metadata.py` (new)
- `libs/python/emg-platform-core/src/emg_platform_core/ports/graph_revision_reader.py` (new)
- `libs/python/emg-platform-core/src/emg_platform_core/ports/graph_store.py` (extend `WriteReceipt`)
- `libs/python/emg-platform-core/src/emg_platform_core/ports/__init__.py` (export surface)
- `libs/python/emg-platform-core/src/emg_platform_core/adapters/in_memory.py` (retain history; implement `GraphRevisionReader`; update `_receipt_for`)
- `libs/python/emg-platform-core/src/emg_platform_core/errors.py` (`RevisionNotFoundError`, `SnapshotIntegrityError`, `UnsupportedHistoryCapabilityError`)
- `libs/python/emg-persistence/src/emg_persistence/revisions/model.py` (`RevisionRecord`)
- `libs/python/emg-persistence/src/emg_persistence/revisions/repository.py` (`list_revisions` on the Protocol)
- `libs/python/emg-persistence/src/emg_persistence/revisions/in_memory.py` (implement `list_revisions`)
- `libs/python/emg-persistence/src/emg_persistence/postgres/revision_repository.py` (implement `list_revisions`)
- `libs/python/emg-persistence/src/emg_persistence/store.py` (implement `GraphRevisionReader`; update `_receipt_for`; typed not-found/integrity errors)
- `services/knowledge-graph/src/emg_knowledge_graph/commands.py` (new queries/command)
- `services/knowledge-graph/src/emg_knowledge_graph/results.py` (new result/summary/details/diff DTOs)
- `services/knowledge-graph/src/emg_knowledge_graph/errors.py` (new application errors)
- `services/knowledge-graph/src/emg_knowledge_graph/service.py` (four new orchestrator methods)
- `services/knowledge-graph/src/emg_knowledge_graph/__init__.py` (export surface)
- `services/knowledge-graph/tests/test_revision_history.py` (new)
- `services/knowledge-graph/tests/test_dependency_boundary.py` (extended)
- No files under `docker/`, `migrations/`, or any `.sql` path.

## Unresolved Questions

None blocking. All questions raised during discovery (equal-revision comparison
validity, restore-of-current-revision behavior, `as_of` meaning, port placement)
are resolved as binding decisions above. Implementation-time re-verification items
(not open design questions): confirm no third `WriteReceipt` construction site has
been added to the working tree since this ADR was written, before relying on the
"exactly two factories" backward-compatibility argument in §11.
