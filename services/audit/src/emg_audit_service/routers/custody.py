"""Digital Evidence Chain-of-Custody endpoints (FEAT-04-3, Sprint 7).

`POST /audit/custody/events` — record a custody transfer (append-only). The
store assigns the global `chain_sequence`, the per-evidence `custody_sequence`,
timing, and the hash-chain link; `source_principal` is assigned from the
authenticated token, never producer content. Idempotent by
`(source_principal, custody_event_id)`.

`GET /audit/custody/events` — retrieve a custody chain by evidence id /
custodian / time range.

`GET /audit/custody/integrity` — verify the custody hash chain and per-evidence
sequence contiguity (tamper / deletion / gap detection); returns an explicit
result, never a 500.

All three endpoints are least-privilege and service-authenticated, restricted
to the existing `svc-audit` role — no new role, no human/UI access (that is
FEAT-04-4, a later sprint).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from emg_audit_client import CustodyEvent, CustodyQuery, SubmittedCustodyEvent
from emg_audit_pipeline import encode_cursor
from emg_common_types import Classification
from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse

from ..authn import AuditCustodianDep, AuditReaderDep
from ..reporting import CUSTODY_CSV_COLUMNS, iter_custody_views, stream_csv, stream_json
from ..schemas import (
    CustodyEventPage,
    CustodyEventView,
    CustodyIngestResponse,
    IntegrityResponse,
)
from ..store import CustodyStoreDep

router = APIRouter(prefix="/audit/custody", tags=["audit-custody"])


def _to_view(event: CustodyEvent) -> CustodyEventView:
    return CustodyEventView(
        custody_event_id=event.custody_event_id,
        source_principal=event.source_principal,
        chain_sequence=event.chain_sequence,
        custody_sequence=event.custody_sequence,
        transfer_timestamp=event.transfer_timestamp,
        evidence_id=event.evidence_id,
        custody_action=event.custody_action,
        custodian=event.custodian,
        prior_custodian=event.prior_custodian,
        transfer_reason=event.transfer_reason,
        classification=event.classification.value,
        correlation_id=event.correlation_id,
    )


@router.post("/events", response_model=CustodyIngestResponse)
def record_custody_event(
    event: SubmittedCustodyEvent,
    principal: AuditCustodianDep,
    store: CustodyStoreDep,
) -> CustodyIngestResponse:
    # source_principal is assigned from the authenticated token, never producer
    # content (mirrors the Sprint 6 P5 trust boundary).
    persisted = store.append(event, source_principal=principal.client_id)
    return CustodyIngestResponse(
        custody_event_id=persisted.custody_event_id,
        chain_sequence=persisted.chain_sequence,
        custody_sequence=persisted.custody_sequence,
        event_hash=persisted.event_hash,
        accepted=True,
    )


def _build_query(
    *,
    evidence_id: str | None,
    custodian: str | None,
    classification: Classification | None,
    start_time: datetime | None,
    end_time: datetime | None,
    cursor: str | None,
    limit: int,
) -> CustodyQuery:
    return CustodyQuery(
        evidence_id=evidence_id,
        custodian=custodian,
        classification=classification,
        start_time=start_time,
        end_time=end_time,
        cursor=cursor,
        limit=limit,
    )


@router.get("/events", response_model=list[CustodyEventView])
def query_custody_events(
    reader: AuditReaderDep,
    store: CustodyStoreDep,
    evidence_id: str | None = None,
    custodian: str | None = None,
    classification: Classification | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CustodyEventView]:
    query = _build_query(
        evidence_id=evidence_id,
        custodian=custodian,
        classification=classification,
        start_time=start_time,
        end_time=end_time,
        cursor=None,
        limit=limit,
    )
    return [_to_view(event) for event in store.query(query)]


@router.get("/events/page", response_model=CustodyEventPage)
def query_custody_events_page(
    reader: AuditReaderDep,
    store: CustodyStoreDep,
    evidence_id: str | None = None,
    custodian: str | None = None,
    classification: Classification | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> CustodyEventPage:
    query = _build_query(
        evidence_id=evidence_id,
        custodian=custodian,
        classification=classification,
        start_time=start_time,
        end_time=end_time,
        cursor=cursor,
        limit=limit,
    )
    events = store.query(query)
    next_cursor = encode_cursor(events[-1].chain_sequence) if len(events) == limit else None
    return CustodyEventPage(
        items=[_to_view(event) for event in events],
        next_cursor=next_cursor,
        count=len(events),
    )


@router.get("/export", response_model=None)
def export_custody_events(
    reader: AuditReaderDep,
    store: CustodyStoreDep,
    format: Literal["json", "csv"] = "json",
    evidence_id: str | None = None,
    custodian: str | None = None,
    classification: Classification | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> Response:
    base = _build_query(
        evidence_id=evidence_id,
        custodian=custodian,
        classification=classification,
        start_time=start_time,
        end_time=end_time,
        cursor=None,
        limit=100,
    )
    views = iter_custody_views(store, base, _to_view)
    if format == "csv":
        return StreamingResponse(
            stream_csv(views, CUSTODY_CSV_COLUMNS),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="custody_events.csv"'},
        )
    return StreamingResponse(stream_json(views), media_type="application/json")


@router.get("/integrity", response_model=IntegrityResponse)
def verify_custody_integrity(reader: AuditReaderDep, store: CustodyStoreDep) -> IntegrityResponse:
    report = store.verify_integrity()
    return IntegrityResponse(
        intact=report.intact,
        checked_count=report.checked_count,
        first_broken_sequence=report.first_broken_sequence,
        detail=report.detail,
    )
