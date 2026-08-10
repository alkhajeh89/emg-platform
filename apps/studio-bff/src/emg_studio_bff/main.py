"""FastAPI application factory for the EMG Studio BFF (Phase 2B).

Mirrors `emg_audit_service.main.create_app()` / `emg_knowledge_graph_api.main`
exactly: shared `HttpRequestSecurityMiddleware`, the same `emg_errors` ->
HTTP status mapping convention, correlation-ID propagation. No second
error-handling mechanism is introduced.

ADR-036 D-8: every response from this application defaults to
`Cache-Control: private, no-store` — added here, once, as a response-header
middleware, rather than repeated per route. This batch implements no
historical-revision caching path (deferred), so there is currently no
exception to this default anywhere in the application.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from emg_api_contracts import ApiError, ApiResponse, HttpRequestSecurityMiddleware
from emg_errors import AuthorizationError, EMGError, UpstreamServiceError, ValidationError
from emg_telemetry import get_logger, set_correlation_id
from emg_telemetry.http_metrics import install_http_metrics, metrics_router, record_http_error
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from .config import get_settings, validate_runtime_configuration
from .routers.auth import router as auth_router
from .routers.health import router as health_router
from .routers.knowledge_graph_proxy import router as kg_proxy_router

_log = get_logger("studio-bff.api")

_ERROR_STATUS_MAP: dict[type[EMGError], int] = {
    ValidationError: 400,
    AuthorizationError: 401,
    UpstreamServiceError: 502,
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="EMG Studio BFF",
        description=(
            "Phase 2B — the mandatory Backend-for-Frontend (ADR-036 D-1). "
            "Terminates OIDC Authorization Code + PKCE S256 (ADR-035) for "
            "human browser sessions and performs OAuth 2.0 Token Exchange "
            "(ADR-038) to obtain audience-scoped Delegated Credentials for "
            "downstream Platform Services. Not a Policy Enforcement Point "
            "(ADR-036 D-4); holds no direct datastore access."
        ),
        version="0.1.0",
    )
    app.add_middleware(HttpRequestSecurityMiddleware)
    install_http_metrics(app, service="studio-bff")

    def validate_startup() -> None:
        validate_runtime_configuration(get_settings())

    app.router.add_event_handler("startup", validate_startup)

    @app.middleware("http")
    async def correlation_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-correlation-id")
        correlation_id = set_correlation_id(incoming)
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        return response

    @app.middleware("http")
    async def no_store_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """ADR-036 D-8: every response defaults to private, no-store. This
        batch implements no cacheable path, so this is unconditional."""
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.exception_handler(EMGError)
    async def emg_error_handler(request: Request, exc: EMGError) -> JSONResponse | RedirectResponse:
        status_code = _ERROR_STATUS_MAP.get(type(exc), 500)
        _log.warning(
            "request failed: error_code=%s error_type=%s status_code=%d",
            exc.error_code,
            type(exc).__name__,
            status_code,
            extra={"module": "studio-bff", "action": "http_request", "outcome": "error"},
        )
        record_http_error(app, exc.error_code, status_code)
        error = ApiError(error_code=exc.error_code, message=_public_error_message(exc, status_code))
        envelope: ApiResponse[None] = ApiResponse(data=None, error=error)
        response = JSONResponse(status_code=status_code, content=_envelope_dict(envelope))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(kg_proxy_router)
    app.include_router(metrics_router())
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


def _public_error_message(exc: EMGError, status_code: int) -> str:
    """Never a stack trace, internal identifier, or upstream payload
    fragment (ADR-036 D-9). AuthorizationError's own message is already
    generic (see oidc.py's OidcError -> AuthorizationError mapping in
    routers/auth.py), so it is safe to pass through unlike other services'
    stricter override — kept consistent with that existing convention
    rather than inventing a new one."""
    if isinstance(exc, AuthorizationError):
        return "Authentication failed"
    if isinstance(exc, UpstreamServiceError):
        return "Upstream service unavailable"
    if status_code >= 500:
        return "Internal server error"
    return exc.message


app = create_app()
