"""Bounded, side-effect-free Identity readiness checks."""

from __future__ import annotations

import asyncio
import os

import httpx
from starlette.concurrency import run_in_threadpool

from .config import Settings


async def readiness(settings: Settings) -> dict[str, object]:
    from .dependencies import audit_delivery_status

    delivery = audit_delivery_status().snapshot()
    recovery_gate_ok = await _recovery_gate_ready(settings)
    if settings.deployment_environment != "production":
        return {
            "status": "degraded" if (delivery["degraded"] or not recovery_gate_ok) else "ready",
            "service": "identity",
            "audit_delivery": delivery,
            "recovery_gate_available": recovery_gate_ok,
        }
    keycloak_ok, postgres_ok = await asyncio.gather(
        _keycloak_ready(settings),
        _postgres_ready(settings),
    )
    spool_parent = settings.audit_spool_path.parent
    spool_ok = spool_parent.is_dir() and os.access(spool_parent, os.W_OK)
    audit_ok = await _audit_ready(settings)
    mandatory_ok = keycloak_ok and postgres_ok and spool_ok and recovery_gate_ok
    return {
        "status": "ready" if mandatory_ok else "unavailable",
        "service": "identity",
        "keycloak_available": keycloak_ok,
        "refresh_store_available": postgres_ok,
        "recovery_gate_available": recovery_gate_ok,
        "audit_spool_available": spool_ok,
        "audit_service_available": audit_ok,
        "audit_delivery": delivery,
        "degraded": mandatory_ok and (not audit_ok or bool(delivery["degraded"])),
    }


async def _recovery_gate_ready(settings: Settings) -> bool:
    """ADR-043 Amendment 1 A8: fail closed unless PostgreSQL's reconciled
    (generation, authority_revision) pair equals the externally materialized
    pair. Not applicable when the refresh-token store is not PostgreSQL --
    there is no durable recovery-state relation to compare against."""

    if settings.refresh_token_store_backend != "postgres":
        return True

    def probe() -> bool:
        from pathlib import Path

        from .recovery_gate import RecoveryGateDenied, evaluate_recovery_gate

        try:
            evaluate_recovery_gate(
                dsn=settings.refresh_token_postgres_dsn,
                authority_file=Path(settings.recovery_authority_file),
                timeout_seconds=settings.readiness_timeout_seconds,
            )
            return True
        except RecoveryGateDenied:
            return False

    try:
        return await asyncio.wait_for(
            run_in_threadpool(probe), timeout=settings.readiness_timeout_seconds
        )
    except TimeoutError:
        return False


async def _keycloak_ready(settings: Settings) -> bool:
    try:
        async with httpx.AsyncClient(timeout=settings.readiness_timeout_seconds) as client:
            response = await client.get(settings.jwks_uri)
        return response.status_code // 100 == 2
    except httpx.HTTPError:
        return False


async def _audit_ready(settings: Settings) -> bool:
    try:
        async with httpx.AsyncClient(timeout=settings.readiness_timeout_seconds) as client:
            response = await client.get(f"{settings.audit_service_base_url.rstrip('/')}/healthz")
        return response.status_code // 100 == 2
    except httpx.HTTPError:
        return False


async def _postgres_ready(settings: Settings) -> bool:
    def probe() -> bool:
        try:
            import psycopg

            with psycopg.connect(
                settings.refresh_token_postgres_dsn,
                connect_timeout=max(1, int(settings.readiness_timeout_seconds)),
            ) as connection:
                connection.read_only = True
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    return cursor.fetchone() == (1,)
        except Exception:
            return False

    try:
        return await asyncio.wait_for(
            run_in_threadpool(probe), timeout=settings.readiness_timeout_seconds
        )
    except TimeoutError:
        return False
