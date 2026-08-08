"""Liveness endpoint, matching every other service's `/healthz` convention."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "studio-bff"}
