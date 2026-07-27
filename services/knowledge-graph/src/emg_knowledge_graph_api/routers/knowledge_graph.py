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

**Group D9 (ADR-026 Revision 2):** every route additionally passes its
already-built application-layer result through the Group D8
`classification` module before mapping it to a response. Each route calls
exactly one `classification.filter_*`/`gate_*` function — never a second
authorization mechanism, never an inline clearance comparison. The flow for
every route is: HTTP route -> `classification.py` -> the same
`PolicyEnforcementPointDep`/`PolicyEngine` `require_permission` already
uses for operation-level authorization (ADR-025 Group C5, C6), evaluated
once more per returned object. `classification.py` remains the sole place
that decision is made; routes only (a) call it and (b) apply its result
using their own pre-existing not-found/empty shape (`EntityNotFoundError`/
`EdgeNotFoundError`, an empty/pruned list, `PathResult(found=False)`,
`EntityHistoryResult(item=None)`) — the same uniform-denial shapes Group D8
was built against (ADR-026 Revision 2 §8.5).

**Batch 2 remediation fix (pagination metadata leak):** paginated listings
(`list_entities`, `list_edges`, `list_neighbors`) no longer derive
`PageInfo` from the raw, unfiltered application-layer page at all. An
audited finding showed that preserving the raw page's `has_more`/
`next_cursor` let a client infer that classification-denied objects exist
(most directly: `next_cursor` could literally be a denied object's own id).
`_authorized_page` below instead re-derives `returned_count`, `has_more`,
and `next_cursor` *entirely* from the authorized (post-filter) item
sequence. Because a single raw page may contain fewer authorized items than
requested (some pruned), this requires fetching additional raw pages —
look-ahead — until either more than `limit` authorized items have been
accumulated (proof that a further page exists) or the underlying raw data
is exhausted. This look-ahead lives entirely in this HTTP adapter layer: it
only calls the existing `KnowledgeGraphApplication` methods and the
existing Group D8 `classification.filter_*` functions (which in turn call
`PolicyEnforcementPointDep`/`PolicyEngine` per object, exactly as before) —
no classification comparison, ranking, or new authorization mechanism is
introduced. A raw page's `revision_number` is pinned after the first
look-ahead call so every subsequent internal page is read from the same
snapshot, keeping the loop consistent even when the original request asked
for the "current head" (a moving target across multiple internal calls
otherwise).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Annotated, TypeVar

from emg_common_types import Classification
from emg_knowledge_graph import (
    MAX_QUERY_PAGE_SIZE,
    MAX_TRAVERSAL_DEPTH,
    EdgeDetails,
    EdgeNotFoundError,
    EdgeQueryResult,
    EntityAttributeHistoryQuery,
    EntityNotFoundError,
    EntityQueryResult,
    EntitySummary,
    GetEdgeQuery,
    GetEntityQuery,
    GraphQueryScope,
    InvalidQueryError,
    ListEdgesQuery,
    ListEntitiesQuery,
    ListNeighborsQuery,
    MetadataPredicate,
    NeighborDirection,
    NeighborResult,
    PagedEdgeResult,
    PagedEntityResult,
    PagedNeighborResult,
    PageInfo,
    PathQueryResult,
    QueryRevisionContext,
    ShortestPathQuery,
)
from emg_memory_graph import EdgeDirection
from fastapi import APIRouter, Depends, Query

from .. import classification as classification_gate
from .. import mapping
from ..authn import TenantContextDep
from ..authorization import require_permission
from ..dependencies import KnowledgeGraphApplicationDep, PolicyEnforcementPointDep
from ..schemas import (
    EdgeQueryResultResponse,
    EntityHistoryResultResponse,
    EntityQueryResultResponse,
    PagedEdgeResultResponse,
    PagedEntityResultResponse,
    PagedNeighborResultResponse,
    PathQueryResultResponse,
)

_Item = TypeVar("_Item")
_Q = TypeVar("_Q")


def _authorized_page(
    *,
    limit: int,
    initial_query: _Q,
    run_page: Callable[[_Q], tuple[Sequence[_Item], PageInfo, QueryRevisionContext]],
    advance: Callable[[_Q, str, int], _Q],
    authorize: Callable[[Sequence[_Item]], tuple[_Item, ...]],
    id_of: Callable[[_Item], str],
) -> tuple[tuple[_Item, ...], PageInfo, QueryRevisionContext]:
    """Fetch and filter raw pages via `run_page`/`authorize` until either
    more than `limit` authorized items are known to exist or the underlying
    raw data is exhausted, then return exactly `limit` authorized items with
    a `PageInfo` derived only from that authorized set (Batch 2 remediation
    — see module docstring). `advance` builds the next raw query from the
    current one, the raw page's own cursor, and the revision number pinned
    from the first raw page's `QueryRevisionContext`."""
    accumulated: list[_Item] = []
    query = initial_query
    revision_context: QueryRevisionContext | None = None
    pinned_revision: int | None = None
    raw_has_more = True

    while len(accumulated) <= limit and raw_has_more:
        raw_items, raw_page_info, revision_context = run_page(query)
        if pinned_revision is None:
            pinned_revision = revision_context.revision_number
        accumulated.extend(authorize(raw_items))
        raw_has_more = raw_page_info.has_more
        if raw_has_more:
            # `next_cursor` is guaranteed non-None whenever has_more is True
            # (`_paginate_by_id`'s own invariant).
            assert raw_page_info.next_cursor is not None
            query = advance(query, raw_page_info.next_cursor, pinned_revision)

    assert revision_context is not None  # loop always runs at least once (limit >= 1)

    has_more = len(accumulated) > limit
    page = tuple(accumulated[:limit])
    next_cursor = id_of(page[-1]) if page and has_more else None
    page_info = PageInfo(
        limit=limit, returned_count=len(page), next_cursor=next_cursor, has_more=has_more
    )
    return page, page_info, revision_context


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
    pep: PolicyEnforcementPointDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_ENTITY))],
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> EntityQueryResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    result = app.get_entity(GetEntityQuery(scope=scope, node_id=entity_id))
    gated_item = classification_gate.gate_entity(
        pep, caller.principal, RESOURCE_ENTITY, result.item
    )
    if gated_item is None:
        # Same not-found message shape the application layer itself raises
        # (service.py) — a classification denial must be indistinguishable
        # from a real not-found (ADR-026 Revision 2 §8.5).
        raise EntityNotFoundError(f"no entity {entity_id!r} for tenant {caller.tenant.value!r}")
    result = EntityQueryResult(item=gated_item, revision_context=result.revision_context)
    return mapping.entity_query_result(result)


@router.get("/entities", response_model=PagedEntityResultResponse)
async def list_entities(
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    pep: PolicyEnforcementPointDep,
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

    def _run(
        q: ListEntitiesQuery,
    ) -> tuple[Sequence[EntitySummary], PageInfo, QueryRevisionContext]:
        raw = app.list_entities(q)
        return raw.items, raw.page_info, raw.revision_context

    def _advance(q: ListEntitiesQuery, cursor: str, pinned_revision: int) -> ListEntitiesQuery:
        return replace(
            q,
            before_node_id=cursor,
            scope=replace(q.scope, revision_number=pinned_revision),
        )

    items, page_info, revision_context = _authorized_page(
        limit=limit,
        initial_query=query,
        run_page=_run,
        advance=_advance,
        authorize=lambda raw_items: classification_gate.filter_entities(
            pep, caller.principal, RESOURCE_ENTITY, raw_items
        ),
        id_of=lambda item: item.node_id,
    )
    result = PagedEntityResult(items=items, page_info=page_info, revision_context=revision_context)
    return mapping.paged_entity_result(result)


@router.get("/edges/{edge_id}", response_model=EdgeQueryResultResponse)
async def get_edge(
    edge_id: str,
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    pep: PolicyEnforcementPointDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_EDGE))],
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> EdgeQueryResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    result = app.get_edge(GetEdgeQuery(scope=scope, edge_id=edge_id))
    gated_item = classification_gate.gate_edge(pep, caller.principal, RESOURCE_EDGE, result.item)
    if gated_item is None:
        raise EdgeNotFoundError(f"no edge {edge_id!r} for tenant {caller.tenant.value!r}")
    result = EdgeQueryResult(item=gated_item, revision_context=result.revision_context)
    return mapping.edge_query_result(result)


@router.get("/edges", response_model=PagedEdgeResultResponse)
async def list_edges(
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    pep: PolicyEnforcementPointDep,
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

    def _run(q: ListEdgesQuery) -> tuple[Sequence[EdgeDetails], PageInfo, QueryRevisionContext]:
        raw = app.list_edges(q)
        return raw.items, raw.page_info, raw.revision_context

    def _advance(q: ListEdgesQuery, cursor: str, pinned_revision: int) -> ListEdgesQuery:
        return replace(
            q,
            before_edge_id=cursor,
            scope=replace(q.scope, revision_number=pinned_revision),
        )

    items, page_info, revision_context = _authorized_page(
        limit=limit,
        initial_query=query,
        run_page=_run,
        advance=_advance,
        authorize=lambda raw_items: classification_gate.filter_edges(
            pep, caller.principal, RESOURCE_EDGE, raw_items
        ),
        id_of=lambda item: item.edge_id,
    )
    result = PagedEdgeResult(items=items, page_info=page_info, revision_context=revision_context)
    return mapping.paged_edge_result(result)


@router.get("/entities/{entity_id}/neighbors", response_model=PagedNeighborResultResponse)
async def list_neighbors(
    entity_id: str,
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    pep: PolicyEnforcementPointDep,
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

    def _run(
        q: ListNeighborsQuery,
    ) -> tuple[Sequence[NeighborResult], PageInfo, QueryRevisionContext]:
        raw = app.list_neighbors(q)
        return raw.items, raw.page_info, raw.revision_context

    def _advance(q: ListNeighborsQuery, cursor: str, pinned_revision: int) -> ListNeighborsQuery:
        return replace(
            q,
            before_edge_id=cursor,
            scope=replace(q.scope, revision_number=pinned_revision),
        )

    items, page_info, revision_context = _authorized_page(
        limit=limit,
        initial_query=query,
        run_page=_run,
        advance=_advance,
        authorize=lambda raw_items: classification_gate.filter_neighbors(
            pep, caller.principal, RESOURCE_NEIGHBORS, raw_items
        ),
        id_of=lambda item: item.via_edge_id,
    )
    result = PagedNeighborResult(
        items=items, page_info=page_info, revision_context=revision_context
    )
    return mapping.paged_neighbor_result(result)


@router.get("/paths/shortest", response_model=PathQueryResultResponse)
async def find_shortest_path(
    caller: TenantContextDep,
    app: KnowledgeGraphApplicationDep,
    pep: PolicyEnforcementPointDep,
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
    gated_path = classification_gate.gate_path(pep, caller.principal, RESOURCE_PATH, result.item)
    result = PathQueryResult(item=gated_path, revision_context=result.revision_context)
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
    pep: PolicyEnforcementPointDep,
    _authorization: Annotated[None, Depends(require_permission(RESOURCE_HISTORY))],
    revision_number: Annotated[int | None, Query(ge=1)] = None,
) -> EntityHistoryResultResponse:
    scope = GraphQueryScope(tenant=caller.tenant, revision_number=revision_number)
    query = EntityAttributeHistoryQuery(
        scope=scope, node_id=entity_id, attribute=attribute_name, valid_at=valid_at
    )
    result = app.get_entity_history(query)
    result = classification_gate.gate_history_fact(pep, caller.principal, RESOURCE_HISTORY, result)
    return mapping.entity_history_result(result)
