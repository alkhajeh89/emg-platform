"""Liveness and readiness endpoints (FEAT-04-1, Sprint 6 Decision C).

`GET /healthz` — liveness (the process is up).
`GET /readyz` — readiness: reports whether the append-only store is reachable.
A `postgres` store that cannot reach the database reports `status="degraded"`
with `store_available=False`, so audit degradation is visible operationally
rather than hidden.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..authn import SettingsDep
from ..schemas import ReadinessResponse
from ..store import StoreDep, store_health

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "audit"}


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(store: StoreDep, settings: SettingsDep) -> ReadinessResponse:
    health = store_health(store, settings)
    return ReadinessResponse(
        status="ready" if health.available else "degraded",
        store_backend=health.backend,
        store_available=health.available,
        detail=health.detail,
    )
