"""Application-service boundary for Module 7 orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from emg_common_types import Classification
from emg_memory_graph import (
    BuildResult,
    MemoryEdge,
    MemoryGraph,
    MemoryGraphBuilder,
    MemoryGraphError,
    MemoryNode,
    MemoryQueryEngine,
    active_edges_at,
    attribute_at,
    diff_graphs,
    node_exists_at,
)
from emg_memory_graph import NodeNotFoundError as _DomainNodeNotFoundError
from emg_platform_core import RevisionNotFoundError as _PlatformRevisionNotFoundError
from emg_platform_core.ports import GraphRevisionReader, GraphStore, RevisionMetadata

from .commands import (
    BuildRevisionCommand,
    CloseRelationshipCommand,
    CompareRevisionsQuery,
    CreateEntityCommand,
    EntityAttributeHistoryQuery,
    GetEdgeQuery,
    GetEntityQuery,
    GetRevisionQuery,
    GraphQueryScope,
    ListEdgesQuery,
    ListEntitiesQuery,
    ListNeighborsQuery,
    ListRevisionsQuery,
    MergeEntitiesCommand,
    MutationCommand,
    NeighborDirection,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
    RestoreRevisionCommand,
    ShortestPathQuery,
)
from .errors import (
    EdgeNotFoundError,
    EntityNotFoundError,
    InvalidHistoryQueryError,
    InvalidMutationCommandError,
    InvalidQueryError,
    InvalidRevisionCommandError,
    MutationBuildError,
    RevisionBuildError,
    RevisionNotFoundError,
    RevisionRestoreError,
    UnsupportedHistoryCapabilityError,
)
from .results import (
    BuildRevisionResult,
    EdgeDetails,
    EdgeQueryResult,
    EntityDetails,
    EntityHistoryResult,
    EntityQueryResult,
    EntitySummary,
    MutationAuditIntent,
    MutationResult,
    NeighborResult,
    PagedEdgeResult,
    PagedEntityResult,
    PagedNeighborResult,
    PageInfo,
    PathQueryResult,
    PathResult,
    QueryRevisionContext,
    RestoreRevisionResult,
    RevisionDetails,
    RevisionDiff,
    RevisionSummary,
)

_T = TypeVar("_T")
MutationAuthorizationHook = Callable[[MutationCommand], None]


def _summary_from_metadata(metadata: RevisionMetadata) -> RevisionSummary:
    return RevisionSummary(
        tenant=metadata.tenant,
        revision_number=metadata.revision_number,
        content_hash=metadata.content_hash,
        parent_hash=metadata.parent_hash,
        principal=metadata.principal,
        node_count=metadata.node_count,
        edge_count=metadata.edge_count,
        created_at=metadata.created_at,
    )


# --- Query engine mapping helpers (ADR-024, Sprint 7.3 Phase 2) --------------
#
# Pure functions: MemoryNode/MemoryEdge (domain) -> Phase 1 DTOs. No
# persistence model, Neo4j record, or repository-internal type is ever
# touched here — only the already-acquired MemoryGraph snapshot and the
# stable domain value objects ADR-024 §16 explicitly permits reusing.


def _entity_summary(node: MemoryNode) -> EntitySummary:
    return EntitySummary(
        node_id=node.node_id,
        node_type=node.node_type,
        label=node.label,
        confidence=node.confidence,
        classification=node.classification,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def _entity_details(node: MemoryNode) -> EntityDetails:
    return EntityDetails(
        summary=_entity_summary(node),
        source=node.source,
        aliases=node.aliases,
        evidence=node.evidence,
        histories=node.histories,
        metadata=node.metadata,
    )


def _edge_details(edge: MemoryEdge) -> EdgeDetails:
    return EdgeDetails(
        edge_id=edge.edge_id,
        edge_type=edge.edge_type,
        source_id=edge.source_id,
        target_id=edge.target_id,
        direction=edge.direction,
        confidence=edge.confidence,
        classification=edge.classification,
        validity=edge.validity,
        created_at=edge.created_at,
        updated_at=edge.updated_at,
        evidence=edge.evidence,
    )


def _classification_of(item: MemoryNode | MemoryEdge | None) -> Classification:
    """Extract ``.classification`` from a node/edge already looked up by id
    from the same graph snapshot a path was just computed over (ADR-026
    Revision 2 §8.6, Group D7). ``item`` is only ``None`` if the path
    referenced an id absent from its own snapshot — impossible for a graph
    that passed ``MemoryGraph``'s own construction-time referential-integrity
    validator (the same invariant ``_neighbor_result`` above relies on),
    asserted rather than silently defaulted so a real violation fails loudly
    instead of fabricating a classification value."""
    assert item is not None  # guaranteed by MemoryGraph's referential-integrity invariant
    return item.classification


def _matches_entity_filters(node: MemoryNode, query: ListEntitiesQuery) -> bool:
    """Exact scalar/metadata matching only (ADR-024 §12) — no range,
    substring, or fuzzy matching of any kind."""
    if query.node_type is not None and node.node_type != query.node_type:
        return False
    if query.source is not None and node.source != query.source:
        return False
    if query.confidence is not None and node.confidence != query.confidence:
        return False
    if query.classification is not None and node.classification != query.classification:
        return False
    for predicate in query.metadata_predicates:
        if node.metadata.get(predicate.key) != predicate.value:
            return False
    return True


def _matches_edge_filters(edge: MemoryEdge, query: ListEdgesQuery) -> bool:
    """``edge_type``/``direction`` only — ``valid_at`` (if any) is applied
    upstream via ``active_edges_at`` before this predicate ever runs, so it
    is deliberately not repeated here."""
    if query.edge_type is not None and edge.edge_type != query.edge_type:
        return False
    return not (query.direction is not None and edge.direction != query.direction)


def _incident_edges_for_direction(
    graph: MemoryGraph, node_id: str, direction: NeighborDirection
) -> tuple[MemoryEdge, ...]:
    """Dispatch to the matching public ``MemoryGraph`` adjacency accessor —
    all three are already deterministically ordered by ``edge_id``."""
    if direction is NeighborDirection.OUTGOING:
        return graph.out_edges(node_id)
    if direction is NeighborDirection.INCOMING:
        return graph.in_edges(node_id)
    return graph.incident_edges(node_id)


def _neighbor_result(graph: MemoryGraph, node_id: str, edge: MemoryEdge) -> NeighborResult | None:
    """``None`` only if the edge's other endpoint is somehow absent from this
    same snapshot — cannot happen for a graph that passed its own
    ``MemoryGraph`` construction-time referential-integrity validator, but
    guarded defensively rather than assumed."""
    other_id = edge.target_id if edge.source_id == node_id else edge.source_id
    other = graph.node(other_id)
    if other is None:  # pragma: no cover - defensive, graph invariant guarantees this
        return None
    return NeighborResult(
        entity=_entity_summary(other),
        via_edge_id=edge.edge_id,
        edge_type=edge.edge_type,
        confidence=edge.confidence,
        direction=edge.direction,
        edge_classification=edge.classification,
    )


def _paginate_by_id(
    items: Sequence[_T], *, id_of: Callable[[_T], str], cursor: str | None, limit: int
) -> tuple[tuple[_T, ...], PageInfo]:
    """Cursor-paginate a sequence already in ascending id order (ADR-024
    §14). ``items`` must already be ascending-by-id — every call site here
    sources from a ``MemoryGraph`` accessor that already guarantees this, so
    no re-sort is performed.

    ``cursor``, when given, resumes strictly *after* the last id seen on a
    prior page (an exclusive "continue from here" boundary) — the only
    cursor direction that composes correctly with an ascending ordering to
    produce working forward pagination. ADR-024 §14 names this field
    ``before_<id>``/``before_node_id``/``before_edge_id`` after
    ``before_revision_number``'s exact convention, but that convention was
    defined for revision listing's *descending* order, where "strictly less
    than the boundary" *is* "continue forward". Applied literally to an
    *ascending* listing it would instead restrict every page to the very
    smallest ids, never advancing — so this implementation intentionally
    resolves the ambiguity by cursor *direction* (greater-than) rather than
    cursor *comparison operator* (less-than), the only choice that yields a
    working pager. Flagged in the Phase 2 final report as an ADR-024 §14 gap
    worth a clarifying addendum.
    """
    eligible = items if cursor is None else tuple(item for item in items if id_of(item) > cursor)
    page = tuple(eligible[:limit])
    has_more = len(eligible) > len(page)
    next_cursor = id_of(page[-1]) if page and has_more else None
    return page, PageInfo(
        limit=limit, returned_count=len(page), next_cursor=next_cursor, has_more=has_more
    )


class KnowledgeGraphApplication:
    """Application/orchestration layer over the platform GraphStore boundary.

    ``revision_reader`` (ADR-023) is a separate, optional, read-only
    dependency — a caller may supply the same concrete adapter object for
    both ``graph_store`` and ``revision_reader`` (both existing adapters
    implement both Protocols structurally), but the two port types are never
    collapsed into one parameter.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        *,
        builder: MemoryGraphBuilder | None = None,
        revision_reader: GraphRevisionReader | None = None,
        mutation_authorization_hook: MutationAuthorizationHook | None = None,
    ) -> None:
        self._graph_store = graph_store
        self._builder = builder or MemoryGraphBuilder()
        self._revision_reader = revision_reader
        self._mutation_authorization_hook = mutation_authorization_hook

    def build_revision(self, command: BuildRevisionCommand) -> BuildRevisionResult:
        """Build and atomically commit the next immutable tenant snapshot."""
        if not isinstance(command, BuildRevisionCommand):
            raise InvalidRevisionCommandError("command must be a BuildRevisionCommand")
        command.validate()

        with self._graph_store.transaction(command.tenant, command.principal) as transaction:
            current = transaction.read()
            try:
                build = self._builder.from_ontology(
                    entities=command.entities,
                    relationships=command.relationships,
                    as_of=command.as_of,
                    base=current,
                )
            except MemoryGraphError as exc:
                raise RevisionBuildError(
                    f"failed to build revision for tenant {command.tenant.value!r}: {exc}"
                ) from exc
            transaction.stage(build.graph)

        receipt = transaction.receipt
        return BuildRevisionResult(
            tenant=receipt.tenant,
            principal=receipt.principal,
            content_hash=receipt.content_hash,
            node_count=receipt.node_count,
            edge_count=receipt.edge_count,
            nodes_created=build.nodes_created,
            edges_created=build.edges_created,
            node_inputs_merged=build.node_inputs_merged,
            edge_inputs_merged=build.edge_inputs_merged,
        )

    # --- mutations (ADR-027 Revision 3, Stage 1) ----------------------------

    def create_entity(self, command: CreateEntityCommand) -> MutationResult:
        """Create one entity and commit one immutable revision."""
        if not isinstance(command, CreateEntityCommand):
            raise InvalidMutationCommandError("command must be a CreateEntityCommand")
        self._prepare_mutation(command)

        def build(current: MemoryGraph) -> BuildResult:
            if current.node(command.entity.entity_id) is not None:
                raise MutationBuildError(f"entity {command.entity.entity_id!r} already exists")
            return self._builder.from_ontology(
                entities=(command.entity,),
                as_of=command.as_of,
                base=current,
            )

        return self._execute_mutation(
            command=command,
            build=build,
            action="create",
            resource_type="knowledge-graph.entity",
            resource_id=command.entity.entity_id,
            related_resource_ids=(),
            reason=None,
            classification_of=lambda graph: self._node_classification(
                graph, command.entity.entity_id
            ),
        )

    def replace_entity(self, command: ReplaceEntityCommand) -> MutationResult:
        """Replace one node through ADR-029 without duplicating lifecycle rules."""
        if not isinstance(command, ReplaceEntityCommand):
            raise InvalidMutationCommandError("command must be a ReplaceEntityCommand")
        self._prepare_mutation(command)
        node_id = command.replacement.node_id
        return self._execute_mutation(
            command=command,
            build=lambda current: self._builder.replace(
                current, node=command.replacement, as_of=command.as_of
            ),
            action=command.action.value,
            resource_type="knowledge-graph.entity",
            resource_id=node_id,
            related_resource_ids=(),
            reason=command.reason,
            classification_of=lambda graph: self._node_classification(graph, node_id),
        )

    def replace_relationship(self, command: ReplaceRelationshipCommand) -> MutationResult:
        """Replace one edge through ADR-029's endpoint-preserving path."""
        if not isinstance(command, ReplaceRelationshipCommand):
            raise InvalidMutationCommandError("command must be a ReplaceRelationshipCommand")
        self._prepare_mutation(command)
        edge_id = command.replacement.edge_id
        return self._execute_mutation(
            command=command,
            build=lambda current: self._builder.replace(
                current, edge=command.replacement, as_of=command.as_of
            ),
            action="update",
            resource_type="knowledge-graph.relationship",
            resource_id=edge_id,
            related_resource_ids=(
                command.replacement.source_id,
                command.replacement.target_id,
            ),
            reason=None,
            classification_of=lambda graph: self._edge_classification(graph, edge_id),
        )

    def close_relationship(self, command: CloseRelationshipCommand) -> MutationResult:
        """Close one stored validity interval through ADR-029."""
        if not isinstance(command, CloseRelationshipCommand):
            raise InvalidMutationCommandError("command must be a CloseRelationshipCommand")
        self._prepare_mutation(command)
        edge_id = command.edge_id

        def endpoints(graph: MemoryGraph) -> tuple[str, ...]:
            edge = graph.edge(edge_id)
            if edge is None:
                return ()
            return (edge.source_id, edge.target_id)

        return self._execute_mutation(
            command=command,
            build=lambda current: self._builder.replace(
                current, close_edge_id=edge_id, as_of=command.as_of
            ),
            action="retire",
            resource_type="knowledge-graph.relationship",
            resource_id=edge_id,
            related_resource_ids_of=endpoints,
            reason=command.reason,
            classification_of=lambda graph: self._edge_classification(graph, edge_id),
        )

    def merge_entities(self, command: MergeEntitiesCommand) -> MutationResult:
        """Merge entities exclusively through ADR-029's graph-level operation."""
        if not isinstance(command, MergeEntitiesCommand):
            raise InvalidMutationCommandError("command must be a MergeEntitiesCommand")
        self._prepare_mutation(command)
        return self._execute_mutation(
            command=command,
            build=lambda current: self._builder.replace(
                current,
                merge_survivor_id=command.survivor_id,
                merge_source_ids=command.source_ids,
                as_of=command.as_of,
            ),
            action="merge",
            resource_type="knowledge-graph.entity",
            resource_id=command.survivor_id,
            related_resource_ids=command.source_ids,
            reason=command.reason,
            classification_of=lambda graph: self._node_classification(graph, command.survivor_id),
        )

    def _prepare_mutation(self, command: MutationCommand) -> None:
        command.validate()
        if self._mutation_authorization_hook is not None:
            self._mutation_authorization_hook(command)

    def _execute_mutation(
        self,
        *,
        command: MutationCommand,
        build: Callable[[MemoryGraph], BuildResult],
        action: str,
        resource_type: str,
        resource_id: str,
        reason: str | None,
        classification_of: Callable[[MemoryGraph], Classification],
        related_resource_ids: tuple[str, ...] = (),
        related_resource_ids_of: Callable[[MemoryGraph], tuple[str, ...]] | None = None,
    ) -> MutationResult:
        resolved_related_ids = related_resource_ids
        with self._graph_store.transaction(command.tenant, command.principal) as transaction:
            current = transaction.read()
            if related_resource_ids_of is not None:
                resolved_related_ids = related_resource_ids_of(current)
            try:
                result = build(current)
            except MemoryGraphError as exc:
                raise MutationBuildError(
                    f"failed to {action} {resource_type} {resource_id!r}: {exc}"
                ) from exc
            transaction.stage(result.graph)

        receipt = transaction.receipt
        audit_intent = MutationAuditIntent(
            tenant=receipt.tenant,
            principal=receipt.principal,
            idempotency_key=command.idempotency_key,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            related_resource_ids=tuple(sorted(resolved_related_ids)),
            classification=classification_of(result.graph),
            reason=reason,
            revision_number=receipt.revision_number,
            content_hash=receipt.content_hash,
        )
        return MutationResult(
            tenant=receipt.tenant,
            principal=receipt.principal,
            revision_number=receipt.revision_number,
            content_hash=receipt.content_hash,
            node_count=receipt.node_count,
            edge_count=receipt.edge_count,
            revision_created=receipt.revision_created,
            nodes_created=result.nodes_created,
            edges_created=result.edges_created,
            node_inputs_merged=result.node_inputs_merged,
            edge_inputs_merged=result.edge_inputs_merged,
            audit_intents=(audit_intent,),
        )

    @staticmethod
    def _node_classification(graph: MemoryGraph, node_id: str) -> Classification:
        node = graph.node(node_id)
        if node is None:  # pragma: no cover - successful ADR-029 result invariant
            raise MutationBuildError(f"result graph has no entity {node_id!r}")
        return node.classification

    @staticmethod
    def _edge_classification(graph: MemoryGraph, edge_id: str) -> Classification:
        edge = graph.edge(edge_id)
        if edge is None:  # pragma: no cover - successful ADR-029 result invariant
            raise MutationBuildError(f"result graph has no relationship {edge_id!r}")
        return edge.classification

    def list_revisions(self, query: ListRevisionsQuery) -> tuple[RevisionSummary, ...]:
        """List a tenant's revision history, newest first. Never loads a graph."""
        if not isinstance(query, ListRevisionsQuery):
            raise InvalidHistoryQueryError("query must be a ListRevisionsQuery")
        query.validate()
        self._require_revision_reader()

        records = self._revision_reader.list_revisions(  # type: ignore[union-attr]
            query.tenant, limit=query.limit, before_revision_number=query.before_revision_number
        )
        return tuple(_summary_from_metadata(record) for record in records)

    def get_revision(self, query: GetRevisionQuery) -> RevisionDetails:
        """Read one historical revision's metadata and exact graph."""
        if not isinstance(query, GetRevisionQuery):
            raise InvalidHistoryQueryError("query must be a GetRevisionQuery")
        query.validate()
        self._require_revision_reader()

        try:
            historical = self._revision_reader.read_revision(  # type: ignore[union-attr]
                query.tenant, query.revision_number
            )
        except _PlatformRevisionNotFoundError as exc:
            raise RevisionNotFoundError(
                f"no revision {query.revision_number} for tenant {query.tenant.value!r}"
            ) from exc
        return RevisionDetails(
            summary=_summary_from_metadata(historical.metadata), graph=historical.graph
        )

    def compare_revisions(self, query: CompareRevisionsQuery) -> RevisionDiff:
        """Diff two of a tenant's revisions using the existing diff_graphs.

        Self-comparison (``from == to``) and reverse comparison
        (``from > to``) are both valid and produce the diff ``diff_graphs``
        naturally produces for the given argument order.
        """
        if not isinstance(query, CompareRevisionsQuery):
            raise InvalidHistoryQueryError("query must be a CompareRevisionsQuery")
        query.validate()
        self._require_revision_reader()

        try:
            from_revision = self._revision_reader.read_revision(  # type: ignore[union-attr]
                query.tenant, query.from_revision_number
            )
            to_revision = self._revision_reader.read_revision(  # type: ignore[union-attr]
                query.tenant, query.to_revision_number
            )
        except _PlatformRevisionNotFoundError as exc:
            raise RevisionNotFoundError(str(exc)) from exc

        diff = diff_graphs(from_revision.graph, to_revision.graph)
        return RevisionDiff(
            tenant=query.tenant,
            from_revision_number=query.from_revision_number,
            to_revision_number=query.to_revision_number,
            diff=diff,
        )

    def restore_revision(self, command: RestoreRevisionCommand) -> RestoreRevisionResult:
        """Restore a historical revision by committing it as the next
        immutable revision, attributed to the restoring principal.

        Does not call ``MemoryGraphBuilder.from_ontology`` — the historical
        graph is staged directly, preserving its internal temporal fields
        exactly. Restoring content identical to the current head is a valid
        no-op (ADR-023 §16): no new revision row, no new outbox event, and the
        result identifies the existing head with ``revision_created=False``.
        """
        if not isinstance(command, RestoreRevisionCommand):
            raise InvalidRevisionCommandError("command must be a RestoreRevisionCommand")
        command.validate()
        self._require_revision_reader()

        try:
            source = self._revision_reader.read_revision(  # type: ignore[union-attr]
                command.tenant, command.source_revision_number
            )
        except _PlatformRevisionNotFoundError as exc:
            raise RevisionNotFoundError(
                f"no revision {command.source_revision_number} "
                f"for tenant {command.tenant.value!r}"
            ) from exc

        with self._graph_store.transaction(command.tenant, command.principal) as transaction:
            try:
                transaction.stage(source.graph)
            except MemoryGraphError as exc:  # pragma: no cover - defensive
                raise RevisionRestoreError(
                    f"failed to stage revision {command.source_revision_number} "
                    f"for tenant {command.tenant.value!r}: {exc}"
                ) from exc

        receipt = transaction.receipt
        return RestoreRevisionResult(
            tenant=receipt.tenant,
            principal=receipt.principal,
            source_revision_number=command.source_revision_number,
            revision_number=receipt.revision_number,
            content_hash=receipt.content_hash,
            node_count=receipt.node_count,
            edge_count=receipt.edge_count,
            committed_at=receipt.committed_at,
            revision_created=receipt.revision_created,
        )

    # --- query engine (ADR-024, Sprint 7.3 Phase 2) --------------------------
    #
    # Five-step flow per ADR-024 §9, applied identically in every method
    # below: (1) type-guard + validate the command, (2) require a configured
    # GraphRevisionReader and resolve the GraphQueryScope into a graph
    # snapshot + QueryRevisionContext, (3) execute against that snapshot using
    # only existing MemoryGraph / MemoryQueryEngine / temporal_query public
    # APIs, (4) map domain results into Phase 1 DTOs, (5) return with the
    # QueryRevisionContext. No new GraphQueryReader port, repository
    # interface, or adapter is introduced; GraphStore/GraphRevisionReader/
    # MemoryGraph/MemoryQueryEngine internals are used, never modified.

    def get_entity(self, query: GetEntityQuery) -> EntityQueryResult:
        """Entity lookup by canonical node id (ADR-024 §10.A)."""
        if not isinstance(query, GetEntityQuery):
            raise InvalidQueryError("query must be a GetEntityQuery")
        query.validate()
        self._require_revision_reader()

        graph, revision_context = self._resolve_scope(query.scope)
        node = graph.node(query.node_id)
        if node is None:
            raise EntityNotFoundError(
                f"no entity {query.node_id!r} for tenant {query.scope.tenant.value!r}"
            )
        return EntityQueryResult(item=_entity_details(node), revision_context=revision_context)

    def list_entities(self, query: ListEntitiesQuery) -> PagedEntityResult:
        """List/filter entities by type and/or exact scalar/metadata
        properties, cursor-paged (ADR-024 §10.B, §10.C, §12, §14)."""
        if not isinstance(query, ListEntitiesQuery):
            raise InvalidQueryError("query must be a ListEntitiesQuery")
        query.validate()
        self._require_revision_reader()

        graph, revision_context = self._resolve_scope(query.scope)
        matching = tuple(node for node in graph.nodes if _matches_entity_filters(node, query))
        page, page_info = _paginate_by_id(
            matching, id_of=lambda n: n.node_id, cursor=query.before_node_id, limit=query.limit
        )
        return PagedEntityResult(
            items=tuple(_entity_summary(node) for node in page),
            page_info=page_info,
            revision_context=revision_context,
        )

    def get_edge(self, query: GetEdgeQuery) -> EdgeQueryResult:
        """Edge lookup by canonical edge id (ADR-024 §10.D)."""
        if not isinstance(query, GetEdgeQuery):
            raise InvalidQueryError("query must be a GetEdgeQuery")
        query.validate()
        self._require_revision_reader()

        graph, revision_context = self._resolve_scope(query.scope)
        edge = graph.edge(query.edge_id)
        if edge is None:
            raise EdgeNotFoundError(
                f"no edge {query.edge_id!r} for tenant {query.scope.tenant.value!r}"
            )
        return EdgeQueryResult(item=_edge_details(edge), revision_context=revision_context)

    def list_edges(self, query: ListEdgesQuery) -> PagedEdgeResult:
        """List/filter edges by type, storage direction, and/or a
        ``valid_at`` moment, cursor-paged (ADR-024 §10.E, §10.J, §14).
        Temporal filtering calls the existing ``active_edges_at`` directly —
        no interval-containment logic is reimplemented here."""
        if not isinstance(query, ListEdgesQuery):
            raise InvalidQueryError("query must be a ListEdgesQuery")
        query.validate()
        self._require_revision_reader()

        graph, revision_context = self._resolve_scope(query.scope)
        candidates: tuple[MemoryEdge, ...] = (
            active_edges_at(graph, query.valid_at) if query.valid_at is not None else graph.edges
        )
        matching = tuple(edge for edge in candidates if _matches_edge_filters(edge, query))
        page, page_info = _paginate_by_id(
            matching, id_of=lambda e: e.edge_id, cursor=query.before_edge_id, limit=query.limit
        )
        return PagedEdgeResult(
            items=tuple(_edge_details(edge) for edge in page),
            page_info=page_info,
            revision_context=revision_context,
        )

    def list_neighbors(self, query: ListNeighborsQuery) -> PagedNeighborResult:
        """Neighbors of one node, traversed outgoing/incoming/both, optionally
        filtered to those valid at a moment, cursor-paged (ADR-024 §10.F/G/H,
        §10.J, §14).

        Deliberately does not call ``temporal_query.neighbors_at`` — that
        function returns bare neighbor node ids, discarding the per-edge
        ``via_edge_id``/``edge_type``/``confidence``/``direction`` fields
        ``NeighborResult`` requires. Instead it composes the same two public
        primitives ``neighbors_at`` itself uses internally
        (``active_edges_at``-equivalent edge-activity filtering, and
        ``node_exists_at``) directly over the subject node's own directional
        incident-edge set, preserving full per-edge result fidelity without
        duplicating any temporal-containment logic.
        """
        if not isinstance(query, ListNeighborsQuery):
            raise InvalidQueryError("query must be a ListNeighborsQuery")
        query.validate()
        self._require_revision_reader()

        graph, revision_context = self._resolve_scope(query.scope)
        if graph.node(query.node_id) is None:
            raise EntityNotFoundError(
                f"no entity {query.node_id!r} for tenant {query.scope.tenant.value!r}"
            )

        edges = _incident_edges_for_direction(graph, query.node_id, query.direction)
        if query.valid_at is not None:
            moment = query.valid_at
            active_ids = {edge.edge_id for edge in active_edges_at(graph, moment)}
            edges = tuple(edge for edge in edges if edge.edge_id in active_ids)
            edges = tuple(
                edge
                for edge in edges
                if node_exists_at(
                    graph,
                    edge.target_id if edge.source_id == query.node_id else edge.source_id,
                    moment,
                )
            )

        neighbors = tuple(
            result
            for edge in edges
            if (result := _neighbor_result(graph, query.node_id, edge)) is not None
        )
        page, page_info = _paginate_by_id(
            neighbors,
            id_of=lambda n: n.via_edge_id,
            cursor=query.before_edge_id,
            limit=query.limit,
        )
        return PagedNeighborResult(
            items=page, page_info=page_info, revision_context=revision_context
        )

    def find_shortest_path(self, query: ShortestPathQuery) -> PathQueryResult:
        """A single unweighted shortest path, bounded by
        ``query.maximum_depth`` (ADR-024 §10.I, §15).

        ``MemoryQueryEngine.shortest_path`` has no depth parameter (an
        unbounded BFS) and cannot be modified (Phase 2 strict rule), so the
        requested ceiling is enforced here, after the fact, against the
        found path's own ``length``. A path longer than what the caller
        asked for is reported as ``found=False`` — per ``PathResult``'s own
        documented semantics, an explicit not-found-within-budget result, not
        an error — rather than exposing a path deeper than requested.
        """
        if not isinstance(query, ShortestPathQuery):
            raise InvalidQueryError("query must be a ShortestPathQuery")
        query.validate()
        self._require_revision_reader()

        graph, revision_context = self._resolve_scope(query.scope)
        engine = MemoryQueryEngine(graph)
        try:
            found = engine.shortest_path(query.from_node_id, query.to_node_id)
        except _DomainNodeNotFoundError as exc:
            raise EntityNotFoundError(str(exc)) from exc

        if found is None or found.length > query.maximum_depth:
            path = PathResult(
                node_ids=(),
                edge_ids=(),
                length=0,
                found=False,
                node_classifications=(),
                edge_classifications=(),
            )
        else:
            # ADR-026 Revision 2 §8.6, Group D7: per-node/per-edge
            # classification, index-aligned with node_ids/edge_ids. Every id
            # on a path found within this same graph snapshot is guaranteed
            # present in it (referential-integrity invariant, identical to
            # `_neighbor_result`'s own defensive comment above) — `graph`
            # already holds every node/edge this path references in scope.
            path = PathResult(
                node_ids=found.node_ids,
                edge_ids=found.edge_ids,
                length=found.length,
                found=True,
                node_classifications=tuple(
                    _classification_of(graph.node(node_id)) for node_id in found.node_ids
                ),
                edge_classifications=tuple(
                    _classification_of(graph.edge(edge_id)) for edge_id in found.edge_ids
                ),
            )
        return PathQueryResult(item=path, revision_context=revision_context)

    def get_entity_history(self, query: EntityAttributeHistoryQuery) -> EntityHistoryResult:
        """The value of one of a node's tracked attributes at a moment in
        time (ADR-024 §10.J, §11, §13) — the domain temporal axis, composed
        with whichever revision ``scope`` selects. Calls the existing
        ``attribute_at`` directly; no history-reconstruction logic is
        reimplemented here."""
        if not isinstance(query, EntityAttributeHistoryQuery):
            raise InvalidQueryError("query must be an EntityAttributeHistoryQuery")
        query.validate()
        self._require_revision_reader()

        graph, revision_context = self._resolve_scope(query.scope)
        node = graph.node(query.node_id)
        if node is None:
            raise EntityNotFoundError(
                f"no entity {query.node_id!r} for tenant {query.scope.tenant.value!r}"
            )
        fact = attribute_at(graph, query.node_id, query.attribute, query.valid_at)
        return EntityHistoryResult(
            item=fact, revision_context=revision_context, classification=node.classification
        )

    def _resolve_scope(self, scope: GraphQueryScope) -> tuple[MemoryGraph, QueryRevisionContext]:
        """Resolve a ``GraphQueryScope`` into ``(graph, revision_context)``
        exactly per ADR-024 §9 step 2 / §11: current head via
        ``GraphStore.read()``, or one immutable historical revision via
        ``GraphRevisionReader.read_revision()``.

        A configured ``GraphRevisionReader`` is required for *both* paths
        (enforced by every caller's preceding ``_require_revision_reader()``
        call): ``QueryRevisionContext`` (ADR-024 §16) always carries a
        concrete ``revision_number``/``committed_at``, and
        ``GraphStore.read()`` alone exposes no revision identity at all —
        only ``GraphRevisionReader.list_revisions`` can supply it for the
        current head. This is a necessary consequence of ADR-024's own
        ``QueryRevisionContext`` shape, not a new architectural decision; it
        does not change the current-head *graph* read path, which still goes
        through ``GraphStore.read()`` exactly as ADR-024 §9 specifies (and so
        still benefits from Neo4j's current-head acceleration, ADR-024 §19).

        Known, accepted characteristic: the current-head graph read and the
        head-metadata read are two separate calls, not one atomic operation
        (no such combined read exists on either port, and adding one would
        require modifying ``GraphStore``/``GraphRevisionReader``, which
        Phase 2 forbids). A concurrent write between them could leave
        ``revision_context`` reporting a revision at most one commit behind
        the graph just read. This is a read-path best-effort characteristic,
        not a defect introduced here.

        If a tenant has never committed a revision, ``list_revisions(...,
        limit=1)`` returns empty; this is surfaced as ``RevisionNotFoundError``
        for the current-head path rather than inventing a sentinel
        ``revision_number`` — ADR-024 defines no meaning for
        "the current head of a tenant with zero revisions".

        ``is_current_head`` reflects which resolution *path* the caller
        selected (``scope.revision_number is None``), not whether the
        resolved revision happens to numerically equal the actual current
        head at read time: an explicit ``scope.revision_number`` is always
        reported as historical (``is_current_head=False``), even if it
        happens to name the same revision the current-head path would have
        resolved to.
        """
        assert self._revision_reader is not None  # guaranteed by _require_revision_reader()

        if scope.revision_number is None:
            heads = self._revision_reader.list_revisions(scope.tenant, limit=1)
            if not heads:
                raise RevisionNotFoundError(
                    f"tenant {scope.tenant.value!r} has no committed revision yet"
                )
            head = heads[0]
            graph = self._graph_store.read(scope.tenant)
            revision_context = QueryRevisionContext(
                revision_number=head.revision_number,
                committed_at=head.created_at,
                is_current_head=True,
            )
            return graph, revision_context

        try:
            historical = self._revision_reader.read_revision(scope.tenant, scope.revision_number)
        except _PlatformRevisionNotFoundError as exc:
            raise RevisionNotFoundError(
                f"no revision {scope.revision_number} for tenant {scope.tenant.value!r}"
            ) from exc
        revision_context = QueryRevisionContext(
            revision_number=historical.metadata.revision_number,
            committed_at=historical.metadata.created_at,
            is_current_head=False,
        )
        return historical.graph, revision_context

    def _require_revision_reader(self) -> None:
        if self._revision_reader is None:
            raise UnsupportedHistoryCapabilityError(
                "KnowledgeGraphApplication was constructed without a GraphRevisionReader"
            )
