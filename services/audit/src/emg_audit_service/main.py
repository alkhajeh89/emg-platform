"""FastAPI application factory for the EMG Audit Service (Module 6, FEAT-04-1).

Wires: correlation-ID propagation middleware (ADR-015, via emg_telemetry), the
shared emg_errors -> emg_api_contracts exception mapping every service uses,
and the /audit ingest/query/integrity routers plus health/readiness.

Deliberately thin: all audit logic lives in emg-audit-client /
emg-audit-pipeline. See docs/engineering/sprint-6-design.md.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from emg_api_contracts import ApiError, ApiResponse
from emg_errors import AuthorizationError, EMGError, UpstreamServiceError, ValidationError
from emg_telemetry import set_correlation_id
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .routers.custody import router as custody_router
from .routers.events import router as events_router
from .routers.health import router as health_router
from .routers.integrity import router as integrity_router

_ERROR_STATUS_MAP: dict[type[EMGError], int] = {
    ValidationError: 400,
    AuthorizationError: 401,
    UpstreamServiceError: 502,
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="EMG Audit Service",
        description=(
            "Module 6 — Audit, Provenance & Digital Evidence Platform. "
            "FEAT-04-1 (Audit Event Pipeline, Sprint 6): append-only store, "
            "authenticated ingestion, minimal US-04 query, integrity verification. "
            "FEAT-04-2 (Provenance Record Model) + FEAT-04-3 (Digital Evidence "
            "Chain-of-Custody, Sprint 7): versioned provenance on audit events and "
            "a separate append-only custody ledger. Thin shell over the shared "
            "emg-audit-client / emg-audit-pipeline libraries."
        ),
        version="0.2.0",
    )

    @app.middleware("http")
    async def correlation_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-correlation-id")
        correlation_id = set_correlation_id(incoming)
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        return response

    @app.exception_handler(EMGError)
    async def emg_error_handler(request: Request, exc: EMGError) -> JSONResponse:
        status_code = _ERROR_STATUS_MAP.get(type(exc), 500)
        error = ApiError(error_code=exc.error_code, message=exc.message)
        envelope: ApiResponse[None] = ApiResponse(data=None, error=error)
        return JSONResponse(status_code=status_code, content=_envelope_dict(envelope))

    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(integrity_router)
    app.include_router(custody_router)
    return app


def _envelope_dict(envelope: ApiResponse[None]) -> dict[str, object]:
    return {
        "data": envelope.data,
        "error": (
            None
            if envelope.error is None
            else {"error_code": envelope.error.error_code, "message": envelope.error.message}
        ),
        "correlation_id": envelope.correlation_id,
    }


app = create_app()
