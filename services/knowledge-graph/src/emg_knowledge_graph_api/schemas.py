"""HTTP response schemas for the Knowledge Graph Query API (Sprint 7.4).

Explicit Pydantic transport models — routers never return `emg_knowledge_graph`
result dataclasses or `emg_memory_graph` domain objects directly. Every field
here is a 1:1 projection of the corresponding application DTO field (ADR-024
§16); nothing is renamed, dropped, or reshaped, so a `curl` of any endpoint
gives a complete accounting of what the application service actually
returned. Datetimes are plain `datetime` fields — FastAPI/Pydantic serialize
a timezone-aware `datetime` as ISO-8601 with its offset (e.g.
`"2026-01-01T00:00:00+00:00"`) by default, which is exactly what's required;
no custom encoder is added because the underlying domain model already
guarantees (or, for `valid_at`, the command layer's own validation already
requires) timezone-aware values wherever one is expected.

Field ordering mirrors `emg_knowledge_graph.results` exactly for easy
side-by-side comparison during review.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class EvidenceRefResponse(BaseModel):
    evidence_id: str
    source: str
    locator: str
    source_principal: str
    captured_at: datetime
    description: str | None = None
    event_id: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, str] = {}


class TemporalValidityResponse(BaseModel):
    valid_from: datetime
    valid_until: datetime | None = None


class TemporalFactResponse(BaseModel):
    value: str
    validity: TemporalValidityResponse
    evidence: list[EvidenceRefResponse]
    recorded_at: datetime
    metadata: dict[str, str] = {}


class TemporalHistoryResponse(BaseModel):
    attribute: str
    facts: list[TemporalFactResponse]


class EntitySummaryResponse(BaseModel):
    node_id: str
    node_type: str
    label: str
    confidence: float
    classification: str
    created_at: datetime
    updated_at: datetime


class EntityDetailsResponse(BaseModel):
    summary: EntitySummaryResponse
    source: str
    aliases: list[str]
    evidence: list[EvidenceRefResponse]
    histories: list[TemporalHistoryResponse]
    metadata: dict[str, str] = {}


class EdgeDetailsResponse(BaseModel):
    edge_id: str
    edge_type: str
    source_id: str
    target_id: str
    direction: str
    confidence: float
    validity: TemporalValidityResponse
    created_at: datetime
    updated_at: datetime
    evidence: list[EvidenceRefResponse]


class NeighborResultResponse(BaseModel):
    entity: EntitySummaryResponse
    via_edge_id: str
    edge_type: str
    confidence: float
    direction: str


class PathResultResponse(BaseModel):
    node_ids: list[str]
    edge_ids: list[str]
    length: int
    found: bool


class QueryRevisionContextResponse(BaseModel):
    revision_number: int
    committed_at: datetime
    is_current_head: bool


class PageInfoResponse(BaseModel):
    """Mirrors `emg_knowledge_graph.PageInfo` exactly (ADR-024 §14, §16).

    Deliberately not `emg_api_contracts.PaginatedResponse` (page/page_size/
    total_items): that shared envelope is offset-pagination-shaped, and
    ADR-024 §14 explicitly adopts cursor pagination and explicitly rejects
    offset pagination. Forcing the offset shape onto a cursor-paginated
    result would either fabricate a `total_items` the underlying `MemoryGraph`
    scan does not cheaply provide, or silently misrepresent the pagination
    model. See the Sprint 7.4 final report's architectural-ambiguity note.
    """

    limit: int
    returned_count: int
    next_cursor: str | None
    has_more: bool


class EntityQueryResultResponse(BaseModel):
    item: EntityDetailsResponse
    revision_context: QueryRevisionContextResponse


class PagedEntityResultResponse(BaseModel):
    items: list[EntitySummaryResponse]
    page_info: PageInfoResponse
    revision_context: QueryRevisionContextResponse


class EdgeQueryResultResponse(BaseModel):
    item: EdgeDetailsResponse
    revision_context: QueryRevisionContextResponse


class PagedEdgeResultResponse(BaseModel):
    items: list[EdgeDetailsResponse]
    page_info: PageInfoResponse
    revision_context: QueryRevisionContextResponse


class PagedNeighborResultResponse(BaseModel):
    items: list[NeighborResultResponse]
    page_info: PageInfoResponse
    revision_context: QueryRevisionContextResponse


class PathQueryResultResponse(BaseModel):
    item: PathResultResponse
    revision_context: QueryRevisionContextResponse


class EntityHistoryResultResponse(BaseModel):
    item: TemporalFactResponse | None
    revision_context: QueryRevisionContextResponse


class ReadinessResponse(BaseModel):
    status: str
    store_backend: str
    store_available: bool
    detail: str
