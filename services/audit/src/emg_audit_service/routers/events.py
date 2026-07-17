"""Audit event ingestion, query, and the Audit Query & Reporting Interface.

`POST /audit/events` — authenticated ingestion by any recognized EMG service
principal. The store assigns the central sequence number and hash-chain link
(producers never do), and ingestion is idempotent by `event_id`.

`GET /audit/events` — authenticated query (FEAT-04-1 minimal US-04 surface,
extended in FEAT-04-4 with richer filters), restricted to an `svc-audit`
reader. Returns a plain list, unchanged in shape from Sprint 6 (backward
compatible).

Sprint 8 (FEAT-04-4, Audit Query & Reporting Interface) adds:

- `GET /audit/events/page` — the same filters with stable opaque-cursor keyset
  pagination (deterministic ordering, no duplicates, no skipped records).
- `GET /audit/events/export` — a backend report of the full filtered result set
  in JSON or CSV (no HTML, no UI).

All read endpoints are restricted to the `svc-audit` reader — no new role.
`classification` is a *filter* dimension only, not clearance-based access
enforcement (a documented follow-up; see docs/engineering/security-limitations.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from emg_audit_client import AuditEvent, AuditQuery, SubmittedAuditEvent
from emg_audit_pipeline import encode_cursor
from emg_common_types import Classification
from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from ..authn import AuditReaderDep, ServicePrincipalDep
from ..reporting import audit_events_to_csv, collect_all_audit
from ..schemas import AuditEventPage, AuditEventView, IngestResponse
from ..store import StoreDep

router = APIRouter(prefix="/audit", tags=["audit"])

# Shared type aliases for the audit read filters (FEAT-04-4), so the query,
# page, and export endpoints expose an identical filter surface.
AuditOutcomeParam = Literal["success", "denied", "error"]


def _to_view(event: AuditEvent) -> AuditEventView:
    return AuditEventView(
        event_id=event.event_id,
        source_principal=event.source_principal,
        sequence_number=event.sequence_number,
        timestamp=event.timestamp,
        correlation_id=event.correlation_id,
        actor=event.actor,
        actor_type=event.actor_type,
        module=event.module,
        action=event.action,
        outcome=event.outcome,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        classification=event.classification.value,
        source_system=event.source_system,
        reason=event.reason,
    )


@router.post("/events", response_model=IngestResponse)
async def ingest_event(
    event: SubmittedAuditEvent,
    principal: ServicePrincipalDep,
    store: StoreDep,
) -> IngestResponse:
    # source_principal is assigned from the authenticated token, never from
    # producer content (Sprint 6 security-review fix, Priority 5).
    persisted = store.append(event, source_principal=principal.client_id)
    return IngestResponse(
        event_id=persisted.event_id,
        sequence_number=persisted.sequence_number,
        event_hash=persisted.event_hash,
        accepted=True,
    )


def _build_query(
    *,
    actor: str | None,
    correlation_id: str | None,
    module: str | None,
    action: str | None,
    outcome: AuditOutcomeParam | None,
    source_system: str | None,
    classification: Classification | None,
    has_provenance: bool | None,
    start_time: datetime | None,
    end_time: datetime | None,
    cursor: str | None,
    limit: int,
) -> AuditQuery:
    return AuditQuery(
        actor=actor,
        correlation_id=correlation_id,
        module=module,
        action=action,
        outcome=outcome,
        source_system=source_system,
        classification=classification,
        has_provenance=has_provenance,
        start_time=start_time,
        end_time=end_time,
        cursor=cursor,
        limit=limit,
    )


@router.get("/events", response_model=list[AuditEventView])
async def query_events(
    reader: AuditReaderDep,
    store: StoreDep,
    actor: str | None = None,
    correlation_id: str | None = None,
    module: str | None = None,
    action: str | None = None,
    outcome: AuditOutcomeParam | None = None,
    source_system: str | None = None,
    classification: Classification | None = None,
    has_provenance: bool | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    # Bound the limit at the route boundary so an out-of-range value returns
    # HTTP 422, not a 500 from downstream model validation (Sprint 6
    # security-review fix, Priority 6). Mirrors AuditQuery's ge=1/le=1000.
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[AuditEventView]:
    query = _build_query(
        actor=actor,
        correlation_id=correlation_id,
        module=module,
        action=action,
        outcome=outcome,
        source_system=source_system,
        classification=classification,
        has_provenance=has_provenance,
        start_time=start_time,
        end_time=end_time,
        cursor=None,
        limit=limit,
    )
    return [_to_view(event) for event in store.query(query)]


@router.get("/events/page", response_model=AuditEventPage)
async def query_events_page(
    reader: AuditReaderDep,
    store: StoreDep,
    actor: str | None = None,
    correlation_id: str | None = None,
    module: str | None = None,
    action: str | None = None,
    outcome: AuditOutcomeParam | None = None,
    source_system: str | None = None,
    classification: Classification | None = None,
    has_provenance: bool | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> AuditEventPage:
    query = _build_query(
        actor=actor,
        correlation_id=correlation_id,
        module=module,
        action=action,
        outcome=outcome,
        source_system=source_system,
        classification=classification,
        has_provenance=has_provenance,
        start_time=start_time,
        end_time=end_time,
        cursor=cursor,
        limit=limit,
    )
    events = store.query(query)
    # A full page implies there may be more; the next cursor is the last row's
    # sequence. A short page is the end of the result set (next_cursor = None).
    next_cursor = encode_cursor(events[-1].sequence_number) if len(events) == limit else None
    return AuditEventPage(
        items=[_to_view(event) for event in events],
        next_cursor=next_cursor,
        count=len(events),
    )


@router.get("/events/export", response_model=None)
async def export_events(
    reader: AuditReaderDep,
    store: StoreDep,
    format: Literal["json", "csv"] = "json",
    actor: str | None = None,
    correlation_id: str | None = None,
    module: str | None = None,
    action: str | None = None,
    outcome: AuditOutcomeParam | None = None,
    source_system: str | None = None,
    classification: Classification | None = None,
    has_provenance: bool | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> Response:
    base = _build_query(
        actor=actor,
        correlation_id=correlation_id,
        module=module,
        action=action,
        outcome=outcome,
        source_system=source_system,
        classification=classification,
        has_provenance=has_provenance,
        start_time=start_time,
        end_time=end_time,
        cursor=None,
        limit=100,
    )
    # Single store query per page (keyset), never per row — not N+1.
    views = collect_all_audit(store, base, _to_view)
    if format == "csv":
        return PlainTextResponse(
            audit_events_to_csv(views),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="audit_events.csv"'},
        )
    return JSONResponse(content=[view.model_dump(mode="json") for view in views])
