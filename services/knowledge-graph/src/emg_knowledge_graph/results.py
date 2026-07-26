"""Immutable results returned by knowledge-graph application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from emg_common_types import Classification
from emg_memory_graph import (
    EdgeDirection,
    EvidenceRef,
    GraphDiff,
    MemoryGraph,
    Metadata,
    TemporalHistory,
    TemporalValidity,
)
from emg_platform_core import PrincipalRef, TenantId


@dataclass(frozen=True, slots=True)
class BuildRevisionResult:
    """Application DTO derived from a committed receipt and build statistics."""

    tenant: TenantId
    principal: PrincipalRef
    content_hash: str
    node_count: int
    edge_count: int
    nodes_created: int
    edges_created: int
    node_inputs_merged: int
    edge_inputs_merged: int


@dataclass(frozen=True, slots=True)
class RevisionSummary:
    """Canonical per-revision list/read item (ADR-023 §10, §12).

    A thin application-layer projection of the platform-core
    ``RevisionMetadata`` type — kept as its own type so the service package
    never exposes a platform-core (or persistence) type directly on its public
    surface."""

    tenant: TenantId
    revision_number: int
    content_hash: str
    parent_hash: str | None
    principal: PrincipalRef
    node_count: int
    edge_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RevisionDetails:
    """One fully-read historical revision: summary plus its exact graph
    (ADR-023 §10, §12)."""

    summary: RevisionSummary
    graph: MemoryGraph


@dataclass(frozen=True, slots=True)
class RevisionDiff:
    """The diff between two of a tenant's revisions (ADR-023 §12, §14).

    Wraps ``emg_memory_graph.versioning.GraphDiff`` unchanged, adding only
    tenant/revision context — no diff logic is duplicated here."""

    tenant: TenantId
    from_revision_number: int
    to_revision_number: int
    diff: GraphDiff


@dataclass(frozen=True, slots=True)
class RestoreRevisionResult:
    """Application DTO derived from a restore commit's receipt (ADR-023 §15,
    §16). ``revision_created`` is ``False`` for a no-op restore (restoring
    content identical to the current head); ``revision_number``/
    ``committed_at`` then identify the existing head, not a new commit."""

    tenant: TenantId
    principal: PrincipalRef
    source_revision_number: int
    revision_number: int
    content_hash: str
    node_count: int
    edge_count: int
    committed_at: datetime
    revision_created: bool


# --- Query engine application contracts (ADR-024, Sprint 7.3 Phase 1) --------
#
# Phase 1 scope only: immutable DTO shapes. Nothing in this module is ever
# constructed from a live GraphStore/GraphRevisionReader read yet — that
# mapping step belongs to a later orchestration phase (ADR-024 §25). Field
# lists match ADR-024 §16 exactly. Stable domain value objects
# (``EvidenceRef``, ``TemporalHistory``, ``Metadata``, ``TemporalValidity``,
# ``EdgeDirection``) are reused directly, as ADR-024 §16 explicitly permits —
# never a persistence row, Neo4j record, or repository-internal type.


@dataclass(frozen=True, slots=True)
class QueryRevisionContext:
    """Identifies which immutable snapshot a query result was computed
    against (ADR-024 §9 step 5, §16) — the current head or one exact
    historical revision."""

    revision_number: int
    committed_at: datetime
    is_current_head: bool


@dataclass(frozen=True, slots=True)
class EntitySummary:
    """The list-shaped entity projection (ADR-024 §16), mirroring
    ``MemoryNode``'s scalar fields without its full evidence/history/metadata
    payload."""

    node_id: str
    node_type: str
    label: str
    confidence: float
    classification: Classification
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EntityDetails:
    """The full-read entity projection (ADR-024 §16): a summary plus the
    full evidence/alias/history/metadata payload."""

    summary: EntitySummary
    source: str
    aliases: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    histories: tuple[TemporalHistory, ...]
    metadata: Metadata


@dataclass(frozen=True, slots=True)
class EdgeDetails:
    """The (only) edge projection (ADR-024 §16) — no separate lighter
    ``EdgeSummary`` is introduced; edges are always returned in full."""

    edge_id: str
    edge_type: str
    source_id: str
    target_id: str
    direction: EdgeDirection
    confidence: float
    validity: TemporalValidity
    created_at: datetime
    updated_at: datetime
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class NeighborResult:
    """One neighbor reached from a subject node via one incident edge
    (ADR-024 §16). ``direction`` is the traversed edge's own
    ``EdgeDirection`` (directed/undirected) — not the traversal mode used to
    reach it, which is the query's own ``NeighborDirection`` input, not part
    of the result."""

    entity: EntitySummary
    via_edge_id: str
    edge_type: str
    confidence: float
    direction: EdgeDirection


@dataclass(frozen=True, slots=True)
class PathResult:
    """A single unweighted shortest path result (ADR-024 §16, §15).
    ``found=False`` with empty ``node_ids``/``edge_ids`` is the normal,
    explicit result for an unreachable pair — not an error."""

    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    length: int
    found: bool


@dataclass(frozen=True, slots=True)
class PageInfo:
    """Cursor-pagination metadata (ADR-024 §14, §16)."""

    limit: int
    returned_count: int
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class PagedEntityResult:
    """A paginated entity listing (ADR-024 §16): exactly ``items``,
    ``page_info``, ``revision_context`` — no other top-level shape."""

    items: tuple[EntitySummary, ...]
    page_info: PageInfo
    revision_context: QueryRevisionContext


@dataclass(frozen=True, slots=True)
class PagedEdgeResult:
    """A paginated edge listing (ADR-024 §16): exactly ``items``,
    ``page_info``, ``revision_context`` — no other top-level shape."""

    items: tuple[EdgeDetails, ...]
    page_info: PageInfo
    revision_context: QueryRevisionContext


@dataclass(frozen=True, slots=True)
class PagedNeighborResult:
    """A paginated neighbor listing (ADR-024 §16): exactly ``items``,
    ``page_info``, ``revision_context`` — no other top-level shape."""

    items: tuple[NeighborResult, ...]
    page_info: PageInfo
    revision_context: QueryRevisionContext


@dataclass(frozen=True, slots=True)
class EntityQueryResult:
    """A single-entity result (ADR-024 §16): exactly ``item``,
    ``revision_context`` — no other top-level shape."""

    item: EntityDetails
    revision_context: QueryRevisionContext


@dataclass(frozen=True, slots=True)
class EdgeQueryResult:
    """A single-edge result (ADR-024 §16): exactly ``item``,
    ``revision_context`` — no other top-level shape."""

    item: EdgeDetails
    revision_context: QueryRevisionContext


@dataclass(frozen=True, slots=True)
class PathQueryResult:
    """A single shortest-path result (ADR-024 §16): exactly ``item``,
    ``revision_context`` — no other top-level shape."""

    item: PathResult
    revision_context: QueryRevisionContext
