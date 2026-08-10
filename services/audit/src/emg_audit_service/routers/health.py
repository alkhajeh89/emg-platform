"""Liveness and readiness endpoints (FEAT-04-1, Sprint 6 Decision C).

`GET /healthz` — liveness (the process is up).
`GET /readyz` — readiness: reports whether the append-only store is reachable.
A `postgres` store that cannot reach the database reports `status="degraded"`
with `store_available=False`, so audit degradation is visible operationally
rather than hidden.
"""

from __future__ import annotations

import asyncio

from emg_telemetry.metrics import record_dependency_health, record_readiness
from fastapi import APIRouter, Response, status
from starlette.concurrency import run_in_threadpool

from ..authn import SettingsDep
from ..schemas import ReadinessResponse
from ..store import StoreDep, store_health

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "audit"}


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(response: Response, store: StoreDep, settings: SettingsDep) -> ReadinessResponse:
    try:
        health = await asyncio.wait_for(
            run_in_threadpool(store_health, store, settings),
            timeout=settings.readiness_timeout_seconds,
        )
    except TimeoutError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        record_readiness("audit", ready=False)
        record_dependency_health("audit", "postgres", healthy=False)
        return ReadinessResponse(
            status="unavailable",
            store_backend=settings.store_backend,
            store_available=False,
            detail="store readiness check timed out",
        )
    if not health.available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    record_readiness("audit", ready=health.available)
    record_dependency_health("audit", "postgres", healthy=health.available)
    return ReadinessResponse(
        status="ready" if health.available else "degraded",
        store_backend=health.backend,
        store_available=health.available,
        detail=health.detail,
    )
