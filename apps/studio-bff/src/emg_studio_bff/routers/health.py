"""Bounded, side-effect-free operational probes."""

from __future__ import annotations

import asyncio

import httpx
from emg_telemetry.metrics import record_dependency_health, record_readiness
from fastapi import APIRouter, Response, status

from ..dependencies import SettingsDep

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "studio-bff"}


@router.get("/readyz")
async def readyz(response: Response, settings: SettingsDep) -> dict[str, object]:
    """Verify public metadata endpoints only; never authenticate or exchange a token."""
    dependencies = ("keycloak", "keycloak", "knowledge_graph")
    endpoints = (
        f"{settings.keycloak_issuer}/.well-known/openid-configuration",
        settings.jwks_uri,
        f"{settings.knowledge_graph_base_url.rstrip('/')}/readyz",
    )
    try:
        async with httpx.AsyncClient(timeout=settings.readiness_timeout_seconds) as client:
            results = await asyncio.gather(*(client.get(endpoint) for endpoint in endpoints))
        for dependency, result in zip(dependencies, results, strict=True):
            record_dependency_health(
                "studio-bff", dependency, healthy=result.status_code // 100 == 2
            )
        if any(result.status_code // 100 != 2 for result in results):
            raise httpx.HTTPStatusError(
                "mandatory dependency unavailable", request=results[0].request, response=results[0]
            )
    except httpx.HTTPError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        record_readiness("studio-bff", ready=False)
        return {"status": "unavailable", "service": "studio-bff"}
    record_readiness("studio-bff", ready=True)
    return {"status": "ready", "service": "studio-bff"}
