"""Audit chain integrity verification endpoint (FEAT-04-1).

`GET /audit/integrity` recomputes the hash chain over the whole store and
reports whether it is intact — the detection control for out-of-band mutation
(the honest limitation being that append-only role grants cannot stop a
database superuser from altering storage, only make it detectable). Restricted
to an `svc-audit` reader.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..authn import AuditReaderDep
from ..schemas import IntegrityResponse
from ..store import StoreDep

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/integrity", response_model=IntegrityResponse)
async def verify_integrity(reader: AuditReaderDep, store: StoreDep) -> IntegrityResponse:
    report = store.verify_integrity()
    return IntegrityResponse(
        intact=report.intact,
        checked_count=report.checked_count,
        first_broken_sequence=report.first_broken_sequence,
        detail=report.detail,
    )
