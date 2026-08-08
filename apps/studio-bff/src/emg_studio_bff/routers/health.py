"""Bounded, side-effect-free operational probes."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Response, status

from ..dependencies import SettingsDep

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "studio-bff"}


@router.get("/readyz")
async def readyz(response: Response, settings: SettingsDep) -> dict[str, object]:
    """Verify public metadata endpoints only; never authenticate or exchange a token."""
    endpoints = (
        f"{settings.keycloak_issuer}/.well-known/openid-configuration",
        settings.jwks_uri,
        f"{settings.knowledge_graph_base_url.rstrip('/')}/readyz",
    )
    try:
        async with httpx.AsyncClient(timeout=settings.readiness_timeout_seconds) as client:
            results = await asyncio.gather(*(client.get(endpoint) for endpoint in endpoints))
        if any(result.status_code // 100 != 2 for result in results):
            raise httpx.HTTPStatusError(
                "mandatory dependency unavailable", request=results[0].request, response=results[0]
            )
    except httpx.HTTPError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "service": "studio-bff"}
    return {"status": "ready", "service": "studio-bff"}
