"""Liveness and readiness endpoints, mirroring
`emg_audit_service.routers.health` exactly: `GET /healthz` is liveness (the
process is up); `GET /readyz` actually probes the configured `GraphStore`
(`store_health`) and reports `status="degraded"` with `store_available=False`
if it is unreachable, rather than unconditionally claiming readiness."""

from __future__ import annotations

import asyncio

import httpx
from emg_telemetry.metrics import record_dependency_health, record_readiness
from fastapi import APIRouter, Response, status
from starlette.concurrency import run_in_threadpool

from ..authn import SettingsDep
from ..dependencies import SchemaRuntimeHealthDep
from ..schemas import ReadinessResponse
from ..store import GraphStoreDep, StoreHealth, store_health

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "knowledge-graph-query-api"}


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(
    response: Response,
    store: GraphStoreDep,
    settings: SettingsDep,
    schema_runtime: SchemaRuntimeHealthDep,
) -> ReadinessResponse:
    try:
        health = await asyncio.wait_for(
            run_in_threadpool(store_health, store, settings),
            timeout=settings.readiness_timeout_seconds,
        )
        if settings.deployment_environment == "production":
            async with httpx.AsyncClient(timeout=settings.readiness_timeout_seconds) as client:
                jwks_response, audit_response = await asyncio.gather(
                    client.get(settings.jwks_uri),
                    client.get(f"{settings.audit_service_base_url.rstrip('/')}/healthz"),
                )
                jwks_response.raise_for_status()
                audit_response.raise_for_status()
    except (TimeoutError, httpx.HTTPError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        health = store_health_unavailable(settings.store_backend)
    if not health.available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    record_readiness("knowledge-graph", ready=health.available)
    record_dependency_health("knowledge-graph", health.backend, healthy=health.available)
    return ReadinessResponse(
        status="ready" if health.available else "degraded",
        store_backend=health.backend,
        store_available=health.available,
        detail=health.detail,
        schema_runtime_configured=schema_runtime.configured,
        schema_placeholder_active=schema_runtime.placeholder_active,
        canonical_schema_version=schema_runtime.canonical_version,
        schema_catalog_generation=schema_runtime.catalog_generation,
    )


def store_health_unavailable(backend: str) -> StoreHealth:
    """Build a safe readiness result without exposing upstream details."""
    return StoreHealth(backend=backend, available=False, detail="mandatory dependency unavailable")
