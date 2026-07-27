"""Knowledge Graph Query REST API routes (Sprint 7.4; ADR-025 Group C6
authorization wiring).

Every route: (1) validates transport shape only (path/query parameter types,
plus the same numeric ceilings the command layer already defines, reused
here — never redefined — purely to fail fast with 422 instead of a 500 from
downstream validation, exactly the precedent `emg_audit_service`'s
`query_events` route already sets for its own `limit` parameter); (2)
authorizes the request via `require_permission` (`authorization.py`),
evaluated *after* tenant resolution and *before* the query executes
(ADR-025 §8.8); (3) constructs the existing Phase 1 command object, always
scoped to the authenticated caller's own tenant (`TenantContextDep`) — never
a client-supplied tenant; (4) calls the one matching
`KnowledgeGraphApplication` method; (5) maps the returned application DTO
into a response schema via `mapping.py`. No filtering, pagination, temporal,
or path-search logic is implemented here — every one of those rules lives in
`emg_knowledge_graph` and is exercised, not reimplemented.

`resource_type` per route follows ADR-025 §8.5's mapping table exactly:
`knowledge-graph.entity` (get/list entities), `knowledge-graph.edge`
(get/list edges), `knowledge-graph.neighbors`, `knowledge-graph.path`,
`knowledge-graph.history` — each a separate resource type so a policy can
grant plain entity/edge lookup without also granting traversal or temporal
history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from emg_common_types import Classification
from emg_knowledge_graph import (
    MAX_QUERY_PAGE_SIZE,
    MAX_TRAVERSAL_DEPTH,
    EntityAttributeHistoryQuery,
    GetEdgeQuery,
    GetEntityQuery,
    GraphQueryScope,
    InvalidQueryError,
    ListEdgesQuery,
    ListEntitiesQuery,
    ListNeighborsQuery,
    MetadataPredicate,
    NeighborDirection,
    ShortestPathQuery,
)
from emg_memory_graph import EdgeDirection
from fastapi import APIRouter, Depends, Query

from .. import mapping
from ..authn import TenantContextDep
from ..authorization import require_permission
from ..dependencies import KnowledgeGraphApplicationDep
from ..schemas import (
    EdgeQueryResultResponse,
    EntityHistoryResultResponse,
    EntityQueryResultResponse,
    PagedEdgeResultResponse,
    PagedEntityResultResponse,
    PagedNeighborResultResponse,
    PathQueryResultResponse,
)

router = APIRouter(prefix="/v1/knowledge-graph", tags=["knowledge-graph"])

# ADR-025 §8.5 resource_type constants — one per distinct disclosure profile.
RESOURCE_ENTITY = "knowledge-graph.entity"
RESOURCE_EDGE = "knowledge-graph.edge"
RESOURCE_NEIGHBORS = "knowledge-graph.neighbors"
RESOURCE_PATH = "knowledge-graph.path"
RESOURCE_HISTORY = "knowledge-graph.history"

# Repeated `metadata=key=value` query parameters (ADR-024 §12 exact
# key/value matching). HTTP query strings have no native repeated key/value
# map shape, so this is the transport-shape adapter; the key/value pair
# themselves are handed to `MetadataPredicate` unvalidated here — its own
# `validate()`, invoked inside `ListEntitiesQuery.validate()`, remains the
# sole business-validation authority (no second validation system).
_METADATA_PARAM_DESCRIPTION = (
    'Exact metadata key/value match, formatted "key=value". Repeat the '
    "parameter for multiple predicates."
)


def _parse_metadata_predicates(raw: list[str]) -> tuple[MetadataPredicate, ...]:
    predicates: list[MetadataPredicate] = []
    for entry in raw:
        if "=" not in entry:
            # Raised as an application-domain error (not a raw
            # fastapi.HTTPException) so this failure passes through the same
            # centralized EMGError handler / ApiResponse envelope every other
            # 4xx in this API uses, rather than FastAPI's default
            # `{"detail": ...}` shape.
            raise InvalidQueryError(f"metadata predicate {entry!r} must be formatted 'key=value'")
        key, _, value = entry.partition("=")
        predicates.append(MetadataPredicate(key=key, value=value))
    return tuple(predicates)


@router.get("/entities/{entity_id}", response_model=EntityQueryResultResponse)
async def get_entity(
    entity_id: str,
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_ENTITY))],
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> EntityQueryResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    result = app.get_entity(GetEntityQuery(scope=scope, node_id=entity_id))
    return mapping.entity_query_result(result)


@router.get("/entities", response_model=PagedEntityResultResponse)
async def list_entities(
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_ENTITY))],
    node_type: str | None = None,
    source: str | None = None,
    confidence: float | None = None,
    classification: Classification | None = None,
    metadata: Annotated[
        list[str], Query(description=_METADATA_PARAM_DESCRIPTION)
    ] = [],  # noqa: B006
    limit: Annotated[int, Query(ge=1, le=MAX_QUERY_PAGE_SIZE)] = MAX_QUERY_PAGE_SIZE,
    before_node_id: str | None = None,
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> PagedEntityResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    query = ListEntitiesQuery(
        scope=scope,
        node_type=node_type,
        source=source,
        confidence=confidence,
        classification=classification,
        metadata_predicates=_parse_metadata_predicates(metadata),
        limit=limit,
        before_node_id=before_node_id,
    )
    result = app.list_entities(query)
    return mapping.paged_entity_result(result)


@router.get("/edges/{edge_id}", response_model=EdgeQueryResultResponse)
async def get_edge(
    edge_id: str,
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_EDGE))],
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> EdgeQueryResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    result = app.get_edge(GetEdgeQuery(scope=scope, edge_id=edge_id))
    return mapping.edge_query_result(result)


@router.get("/edges", response_model=PagedEdgeResultResponse)
async def list_edges(
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_EDGE))],
    edge_type: str | None = None,
    direction: EdgeDirection | None = None,
    valid_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_QUERY_PAGE_SIZE)] = MAX_QUERY_PAGE_SIZE,
    before_edge_id: str | None = None,
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> PagedEdgeResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    query = ListEdgesQuery(
        scope=scope,
        edge_type=edge_type,
        direction=direction,
        valid_at=valid_at,
        limit=limit,
        before_edge_id=before_edge_id,
    )
    result = app.list_edges(query)
    return mapping.paged_edge_result(result)


@router.get("/entities/{entity_id}/neighbors", response_model=PagedNeighborResultResponse)
async def list_neighbors(
    entity_id: str,
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_NEIGHBORS))],
    direction: NeighborDirection = NeighborDirection.BOTH,
    valid_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_QUERY_PAGE_SIZE)] = MAX_QUERY_PAGE_SIZE,
    before_edge_id: str | None = None,
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> PagedNeighborResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    query = ListNeighborsQuery(
        scope=scope,
        node_id=entity_id,
        direction=direction,
        valid_at=valid_at,
        limit=limit,
        before_edge_id=before_edge_id,
    )
    result = app.list_neighbors(query)
    return mapping.paged_neighbor_result(result)


@router.get("/paths/shortest", response_model=PathQueryResultResponse)
async def find_shortest_path(
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_PATH))],
    from_node_id: str,
    to_node_id: str,
    maximum_depth: Annotated[int, Query(ge=1, le=MAX_TRAVERSAL_DEPTH)] = MAX_TRAVERSAL_DEPTH,
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> PathQueryResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    query = ShortestPathQuery(
        scope=scope,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        maximum_depth=maximum_depth,
    )
    result = app.find_shortest_path(query)
    return mapping.path_query_result(result)


@router.get(
    "/entities/{entity_id}/history/{attribute_name}",
    response_model=EntityHistoryResultResponse,
)
async def get_entity_history(
    entity_id: str,
    attribute_name: str,
    valid_at: datetime,
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_HISTORY))],
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> EntityHistoryResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    query = EntityAttributeHistoryQuery(
        scope=scope, node_id=entity_id, attribute=attribute_name, valid_at=valid_at
    )
    result = app.get_entity_history(query)
    return mapping.entity_history_result(result)
