"""FastAPI application factory for the EMG Identity Service.

Wires: correlation-ID propagation middleware (ADR-015 Section 3, via
emg_telemetry — scaffolded Sprint 1), the emg_errors -> emg_api_contracts
exception mapping every service shares, and the /auth router (FEAT-02-1,
FEAT-02-2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from emg_api_contracts import ApiError, ApiResponse
from emg_errors import AuthorizationError, EMGError, UpstreamServiceError, ValidationError
from emg_telemetry import set_correlation_id
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .routers.auth import router as auth_router

_ERROR_STATUS_MAP: dict[type[EMGError], int] = {
    ValidationError: 400,
    AuthorizationError: 401,
    UpstreamServiceError: 502,
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="EMG Identity Service",
        description="Module 4 — Identity & Authentication (Sprint 2: FEAT-02-1, FEAT-02-2)",
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

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "identity"}

    app.include_router(auth_router)
    return app


def _envelope_dict(envelope: ApiResponse[None]) -> dict[str, object]:
    return {
        "data": envelope.data,
        "error": None
        if envelope.error is None
        else {"error_code": envelope.error.error_code, "message": envelope.error.message},
        "correlation_id": envelope.correlation_id,
    }


app = create_app()
