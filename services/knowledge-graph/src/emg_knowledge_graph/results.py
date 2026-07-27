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
    TemporalFact,
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
class MutationAuditIntent:
    """Immutable application intent for later audit reconciliation.

    Stage 1 returns this data to its caller and performs no audit persistence.
    """

    tenant: TenantId
    principal: PrincipalRef
    idempotency_key: str
    action: str
    resource_type: str
    resource_id: str
    related_resource_ids: tuple[str, ...]
    classification: Classification
    reason: str | None
    revision_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class MutationResult:
    """Committed mutation receipt data, build statistics, and audit intents."""

    tenant: TenantId
    principal: PrincipalRef
    revision_number: int
    content_hash: str
    node_count: int
    edge_count: int
    revision_created: bool
    nodes_created: int
    edges_created: int
    node_inputs_merged: int
    edge_inputs_merged: int
    audit_intents: tuple[MutationAuditIntent, ...]


@dataclass(frozen=True, slots=True)
class MutationReplayProjection:
    """External-safe projection of the internal persisted mutation result."""

    tenant_id: str
    revision_number: int
    content_hash: str
    node_count: int
    edge_count: int
    revision_created: bool
    nodes_created: int
    edges_created: int
    node_inputs_merged: int
    edge_inputs_merged: int


def project_mutation_replay(result: MutationResult) -> MutationReplayProjection:
    """Exclude principal, audit, reason, classification, and ledger metadata."""
    return MutationReplayProjection(
        tenant_id=result.tenant.value,
        revision_number=result.revision_number,
        content_hash=result.content_hash,
        node_count=result.node_count,
        edge_count=result.edge_count,
        revision_created=result.revision_created,
        nodes_created=result.nodes_created,
        edges_created=result.edges_created,
        node_inputs_merged=result.node_inputs_merged,
        edge_inputs_merged=result.edge_inputs_merged,
    )


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
    ``EdgeSummary`` is introduced; edges are always returned in full.

    ``classification`` (ADR-026 Revision 2 §8, Amendment 3 / Group D7): the
    edge's own classification, sourced directly from the already-computed
    ``MemoryEdge.classification`` the mapping function producing this DTO
    already holds in scope — a data-projection addition only, not a change
    to any traversal, pagination, or revision-resolution logic. Consumed by
    the HTTP-layer classification-enforcement module (Group D8) to decide
    whether this edge is within the caller's clearance; never read by
    ``emg_knowledge_graph`` itself, which carries no principal/authorization
    concept."""

    edge_id: str
    edge_type: str
    source_id: str
    target_id: str
    direction: EdgeDirection
    confidence: float
    classification: Classification
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
    of the result.

    ``edge_classification`` (ADR-026 Revision 2 §8.6, Group D7): the
    *traversed edge's* classification — distinct from ``entity.classification``
    (the neighboring entity's own classification, already present via
    ``EntitySummary``). ADR-026 Revision 2 §8.6 requires a neighbor to be
    hidden if *either* the neighboring entity's classification *or* the
    connecting edge's classification exceeds the caller's clearance, so both
    values must be independently available to the Group D8 enforcement
    module."""

    entity: EntitySummary
    via_edge_id: str
    edge_type: str
    confidence: float
    direction: EdgeDirection
    edge_classification: Classification


@dataclass(frozen=True, slots=True)
class PathResult:
    """A single unweighted shortest path result (ADR-024 §16, §15).
    ``found=False`` with empty ``node_ids``/``edge_ids`` is the normal,
    explicit result for an unreachable pair — not an error.

    ``node_classifications``/``edge_classifications`` (ADR-026 Revision 2
    §8.6, Group D7): the classification of each node/edge on the path,
    index-aligned one-for-one with ``node_ids``/``edge_ids`` respectively.
    Both are empty exactly when ``found`` is ``False`` (mirroring
    ``node_ids``/``edge_ids``' own emptiness in that case). This is plain
    per-object classification *data* — a fixed-shape tuple, not a ranking or
    dominance computation — the Group D8 enforcement module decides
    clearance by evaluating each value through the existing PolicyEngine,
    never by comparing these values against each other or an ordinal table
    here."""

    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    length: int
    found: bool
    node_classifications: tuple[Classification, ...]
    edge_classifications: tuple[Classification, ...]


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


@dataclass(frozen=True, slots=True)
class EntityHistoryResult:
    """The value of one of a node's tracked attributes at a moment in time
    (``EntityAttributeHistoryQuery`` / ADR-024 §10.J), plus the revision
    context it was computed against.

    Not one of ADR-024 §16's originally enumerated result shapes — Phase 1
    defined no dedicated contract for this capability. This is a minimal,
    Phase 2 (application-service-layer) addition, reusing ``TemporalFact``
    directly, exactly the same reuse pattern §16 already applies to
    ``TemporalHistory``/``TemporalValidity``/``EvidenceRef``. ``item`` is
    ``None`` when the attribute had no value at ``valid_at`` — a normal,
    explicit result, not an error, mirroring ``TemporalHistory.as_of``'s own
    contract.

    ``classification`` (ADR-026 Revision 2 §8.6, Group D7; narrowed to
    ``Classification | None`` by the Batch 2 remediation): the *subject
    node's* classification at the resolved revision, as populated by
    ``KnowledgeGraphApplication.get_entity_history`` itself — always a real
    value at that point (the node's existence was already confirmed before
    this result is constructed), independent of whether ``item`` is
    ``None``.

    The Group D8 enforcement module (``classification.gate_history_fact``)
    consumes this real value to decide access, exactly as before — but once
    that decision is made and access is denied, it returns a *new*
    ``EntityHistoryResult`` with both ``item`` and ``classification`` set to
    ``None``, never the true classification. This is the fix for an audited
    finding: the true value must not survive past the authorization decision
    in the object handed back to the HTTP layer, since "may remain available
    internally only for authorization" cannot be guaranteed for a value that
    is still sitting in a DTO field after the decision has already been
    made — a future consumer of that field (a log line, a new mapping
    function, a debugger) would otherwise see it regardless of the current
    (and already correct) response mapping. ``None`` here therefore means
    either "no classification to report" (denied) or is otherwise always a
    concrete value; it is a distinct condition from ``item is None`` ("no
    value at that moment"), the same way ``TemporalHistory.as_of`` already
    treats its own ``None`` as a normal, non-error outcome."""

    item: TemporalFact | None
    revision_context: QueryRevisionContext
    classification: Classification | None
