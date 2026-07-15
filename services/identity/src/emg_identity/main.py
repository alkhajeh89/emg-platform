"""FastAPI application factory for the EMG Identity Service.

Wires: correlation-ID propagation middleware (ADR-015 Section 3, via
emg_telemetry — scaffolded Sprint 1), the emg_errors -> emg_api_contracts
exception mapping every service shares, and the /auth, /federation, /authz
routers.

Sprint 3 (FEAT-02-3, FEAT-02-4) and Sprint 4 (FEAT-03-1, FEAT-03-2)
additions are called out inline; every Sprint 1/2/3 route, middleware, and
exception mapping is unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from emg_api_contracts import ApiError, ApiResponse
from emg_errors import AuthorizationError, EMGError, UpstreamServiceError, ValidationError
from emg_telemetry import set_correlation_id
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .rate_limit import RateLimitedError
from .routers.auth import router as auth_router
from .routers.authz import router as authz_router
from .routers.federation import router as federation_router
from .routers.service_auth import router as service_auth_router

_ERROR_STATUS_MAP: dict[type[EMGError], int] = {
    ValidationError: 400,
    AuthorizationError: 401,
    UpstreamServiceError: 502,
    RateLimitedError: 429,
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="EMG Identity Service",
        description=(
            "Module 4 — Identity & Authentication (FEAT-02-1..02-4), plus a "
            "reference integration of Module 5's Policy Enforcement Point "
            "(FEAT-03-1, FEAT-03-2, Sprint 4)."
        ),
        version="0.4.0",
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
    app.include_router(service_auth_router)
    app.include_router(federation_router)
    app.include_router(authz_router)
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
