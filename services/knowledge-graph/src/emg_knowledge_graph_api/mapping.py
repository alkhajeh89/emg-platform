"""Pure DTO -> HTTP response-schema mapping (Sprint 7.4).

Every function here is a field-for-field projection with no branching
business logic, no store/port access, and no query construction — the
routers call `KnowledgeGraphApplication` and pass its *return value*
straight into these functions. Keeping this mapping in one module (rather
than inline in each route) is what lets `routers/knowledge_graph.py` stay a
thin transport shell with no duplicated graph-query logic.
"""

from __future__ import annotations

from emg_knowledge_graph import (
    EdgeDetails,
    EdgeQueryResult,
    EntityDetails,
    EntityHistoryResult,
    EntityQueryResult,
    EntitySummary,
    NeighborResult,
    PagedEdgeResult,
    PagedEntityResult,
    PagedNeighborResult,
    PageInfo,
    PathQueryResult,
    QueryRevisionContext,
)
from emg_memory_graph import EvidenceRef, TemporalFact, TemporalHistory, TemporalValidity

from .schemas import (
    EdgeDetailsResponse,
    EdgeQueryResultResponse,
    EntityDetailsResponse,
    EntityHistoryResultResponse,
    EntityQueryResultResponse,
    EntitySummaryResponse,
    EvidenceRefResponse,
    NeighborResultResponse,
    PagedEdgeResultResponse,
    PagedEntityResultResponse,
    PagedNeighborResultResponse,
    PageInfoResponse,
    PathQueryResultResponse,
    PathResultResponse,
    QueryRevisionContextResponse,
    TemporalFactResponse,
    TemporalHistoryResponse,
    TemporalValidityResponse,
)


def _evidence_ref(ref: EvidenceRef) -> EvidenceRefResponse:
    return EvidenceRefResponse(
        evidence_id=ref.evidence_id,
        source=ref.source.value,
        locator=ref.locator,
        source_principal=ref.source_principal,
        captured_at=ref.captured_at,
        description=ref.description,
        event_id=ref.event_id,
        correlation_id=ref.correlation_id,
        metadata=ref.metadata.as_dict(),
    )


def _temporal_validity(validity: TemporalValidity) -> TemporalValidityResponse:
    return TemporalValidityResponse(
        valid_from=validity.valid_from, valid_until=validity.valid_until
    )


def _temporal_fact(fact: TemporalFact) -> TemporalFactResponse:
    return TemporalFactResponse(
        value=fact.value,
        validity=_temporal_validity(fact.validity),
        evidence=[_evidence_ref(ref) for ref in fact.evidence],
        recorded_at=fact.recorded_at,
        metadata=fact.metadata.as_dict(),
    )


def _temporal_history(history: TemporalHistory) -> TemporalHistoryResponse:
    return TemporalHistoryResponse(
        attribute=history.attribute, facts=[_temporal_fact(fact) for fact in history.facts]
    )


def entity_summary(summary: EntitySummary) -> EntitySummaryResponse:
    return EntitySummaryResponse(
        node_id=summary.node_id,
        node_type=summary.node_type,
        label=summary.label,
        confidence=summary.confidence,
        classification=summary.classification.value,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def entity_details(details: EntityDetails) -> EntityDetailsResponse:
    return EntityDetailsResponse(
        summary=entity_summary(details.summary),
        source=details.source,
        aliases=list(details.aliases),
        evidence=[_evidence_ref(ref) for ref in details.evidence],
        histories=[_temporal_history(history) for history in details.histories],
        metadata=details.metadata.as_dict(),
    )


def edge_details(edge: EdgeDetails) -> EdgeDetailsResponse:
    return EdgeDetailsResponse(
        edge_id=edge.edge_id,
        edge_type=edge.edge_type,
        source_id=edge.source_id,
        target_id=edge.target_id,
        direction=edge.direction.value,
        confidence=edge.confidence,
        validity=_temporal_validity(edge.validity),
        created_at=edge.created_at,
        updated_at=edge.updated_at,
        evidence=[_evidence_ref(ref) for ref in edge.evidence],
    )


def neighbor_result(neighbor: NeighborResult) -> NeighborResultResponse:
    return NeighborResultResponse(
        entity=entity_summary(neighbor.entity),
        via_edge_id=neighbor.via_edge_id,
        edge_type=neighbor.edge_type,
        confidence=neighbor.confidence,
        direction=neighbor.direction.value,
    )


def revision_context(context: QueryRevisionContext) -> QueryRevisionContextResponse:
    return QueryRevisionContextResponse(
        revision_number=context.revision_number,
        committed_at=context.committed_at,
        is_current_head=context.is_current_head,
    )


def page_info(info: PageInfo) -> PageInfoResponse:
    return PageInfoResponse(
        limit=info.limit,
        returned_count=info.returned_count,
        next_cursor=info.next_cursor,
        has_more=info.has_more,
    )


def entity_query_result(result: EntityQueryResult) -> EntityQueryResultResponse:
    return EntityQueryResultResponse(
        item=entity_details(result.item), revision_context=revision_context(result.revision_context)
    )


def paged_entity_result(result: PagedEntityResult) -> PagedEntityResultResponse:
    return PagedEntityResultResponse(
        items=[entity_summary(item) for item in result.items],
        page_info=page_info(result.page_info),
        revision_context=revision_context(result.revision_context),
    )


def edge_query_result(result: EdgeQueryResult) -> EdgeQueryResultResponse:
    return EdgeQueryResultResponse(
        item=edge_details(result.item), revision_context=revision_context(result.revision_context)
    )


def paged_edge_result(result: PagedEdgeResult) -> PagedEdgeResultResponse:
    return PagedEdgeResultResponse(
        items=[edge_details(item) for item in result.items],
        page_info=page_info(result.page_info),
        revision_context=revision_context(result.revision_context),
    )


def paged_neighbor_result(result: PagedNeighborResult) -> PagedNeighborResultResponse:
    return PagedNeighborResultResponse(
        items=[neighbor_result(item) for item in result.items],
        page_info=page_info(result.page_info),
        revision_context=revision_context(result.revision_context),
    )


def path_query_result(result: PathQueryResult) -> PathQueryResultResponse:
    return PathQueryResultResponse(
        item=PathResultResponse(
            node_ids=list(result.item.node_ids),
            edge_ids=list(result.item.edge_ids),
            length=result.item.length,
            found=result.item.found,
        ),
        revision_context=revision_context(result.revision_context),
    )


def entity_history_result(result: EntityHistoryResult) -> EntityHistoryResultResponse:
    return EntityHistoryResultResponse(
        item=_temporal_fact(result.item) if result.item is not None else None,
        revision_context=revision_context(result.revision_context),
    )
