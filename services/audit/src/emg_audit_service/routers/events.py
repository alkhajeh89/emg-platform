"""Audit event ingestion and the minimal US-04 query surface (FEAT-04-1).

`POST /audit/events` — authenticated ingestion by any recognized EMG service
principal. The store assigns the central sequence number and hash-chain link
(producers never do), and ingestion is idempotent by `event_id`.

`GET /audit/events` — authenticated minimal query (by actor, time range,
correlation id), restricted to an `svc-audit` reader. This is the minimal
capability US-04 requires ("queryable by actor, time range, and correlation
identifier"); the richer reporting interface is FEAT-04-4, a later sprint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from emg_audit_client import AuditEvent, AuditQuery, SubmittedAuditEvent
from fastapi import APIRouter, Query

from ..authn import AuditReaderDep, ServicePrincipalDep
from ..schemas import AuditEventView, IngestResponse
from ..store import StoreDep

router = APIRouter(prefix="/audit", tags=["audit"])


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


@router.get("/events", response_model=list[AuditEventView])
async def query_events(
    reader: AuditReaderDep,
    store: StoreDep,
    actor: str | None = None,
    correlation_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    # Bound the limit at the route boundary so an out-of-range value returns
    # HTTP 422, not a 500 from downstream model validation (Sprint 6
    # security-review fix, Priority 6). Mirrors AuditQuery's ge=1/le=1000.
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[AuditEventView]:
    query = AuditQuery(
        actor=actor,
        correlation_id=correlation_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return [_to_view(event) for event in store.query(query)]
