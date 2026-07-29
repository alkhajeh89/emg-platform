"""Liveness and readiness endpoints, mirroring
`emg_audit_service.routers.health` exactly: `GET /healthz` is liveness (the
process is up); `GET /readyz` actually probes the configured `GraphStore`
(`store_health`) and reports `status="degraded"` with `store_available=False`
if it is unreachable, rather than unconditionally claiming readiness."""

from __future__ import annotations

from fastapi import APIRouter

from ..authn import SettingsDep
from ..dependencies import SchemaRuntimeHealthDep
from ..schemas import ReadinessResponse
from ..store import GraphStoreDep, store_health

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "knowledge-graph-query-api"}


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(
    store: GraphStoreDep,
    settings: SettingsDep,
    schema_runtime: SchemaRuntimeHealthDep,
) -> ReadinessResponse:
    health = store_health(store, settings)
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
