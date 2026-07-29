"""FastAPI application factory for the EMG Knowledge Graph Query API
(Sprint 7.4).

Wires: correlation-ID propagation middleware (ADR-015, via emg_telemetry,
identical to `emg_audit_service.main`), the shared `emg_errors` ->
`emg_api_contracts` exception mapping every service uses, and the
`/v1/knowledge-graph` query router plus health/readiness.

Deliberately thin: all query logic lives in `emg_knowledge_graph`
(`KnowledgeGraphApplication`); this module and its routers contain none.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from emg_api_contracts import ApiError, ApiResponse, HttpRequestSecurityMiddleware
from emg_errors import EMGError
from emg_telemetry import get_logger, set_correlation_id
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .dependencies import validate_schema_runtime_configuration
from .errors import error_headers, error_status, public_error_message
from .routers.health import router as health_router
from .routers.knowledge_graph import router as knowledge_graph_router
from .routers.mutations import router as mutation_router

_log = get_logger("knowledge_graph.api")


def create_app() -> FastAPI:
    app = FastAPI(
        title="EMG Knowledge Graph Query API",
        description=(
            "Sprint 7.4: a typed HTTP boundary over the Sprint 7.1-7.3 "
            "Knowledge Graph Query Engine application service (ADR-022, "
            "ADR-023, ADR-024). Read-only: entity/edge lookup and listing, "
            "neighbor traversal, single-shortest-path search, and "
            "point-in-time attribute history, each against either the "
            "current graph head or one exact historical revision."
        ),
        version="0.1.0",
    )
    app.add_middleware(HttpRequestSecurityMiddleware)
    app.router.add_event_handler("startup", validate_schema_runtime_configuration)

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
        status_code = error_status(exc)
        _log.warning(
            "request failed: error_code=%s error_type=%s status_code=%d",
            exc.error_code,
            type(exc).__name__,
            status_code,
            extra={
                "module": "knowledge-graph",
                "action": "http_request",
                "outcome": "error",
            },
        )
        error = ApiError(error_code=exc.error_code, message=public_error_message(exc))
        envelope: ApiResponse[None] = ApiResponse(data=None, error=error)
        return JSONResponse(
            status_code=status_code,
            content=_envelope_dict(envelope),
            headers=error_headers(exc),
        )

    app.include_router(health_router)
    app.include_router(knowledge_graph_router)
    app.include_router(mutation_router)
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
