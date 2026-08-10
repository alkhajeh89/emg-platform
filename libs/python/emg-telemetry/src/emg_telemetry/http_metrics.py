"""FastAPI/Starlette glue for `emg_telemetry.metrics` (RC-C, ADR-015 Section 2).

Deliberately a separate module from `metrics.py`: `emg-telemetry` is a
dependency of every service including the non-HTTP `audit-projector` worker,
but only `fastapi`/`starlette` are guaranteed available in HTTP services.
Nothing in `emg_telemetry/__init__.py` imports this module, so importing
`emg_telemetry` itself never requires `fastapi` to be installed; a service
that wants HTTP metrics imports `emg_telemetry.http_metrics` explicitly,
exactly as it already imports `fastapi` itself.

Cardinality safety: the request-path middleware labels every HTTP metric
with the matched *route template* (e.g. `/v1/knowledge-graph/entities/{id}`),
never the resolved path (`/v1/knowledge-graph/entities/8f2c...`) or query
string, so per-entity/tenant identifiers never become label values. A
request that matches no route (404 with no route object) is labeled with
the fixed string `unmatched` rather than the raw path, so probing many
random paths cannot grow cardinality.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, FastAPI
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Match

from .metrics import MetricsRegistry, get_registry


def install_http_metrics(
    app: FastAPI, *, service: str, registry: MetricsRegistry | None = None
) -> None:
    """Register the request-count/duration middleware for `app`.

    Call once from each service's `create_app()`, alongside the existing
    `correlation_id_middleware`. Adds no new route; pair with
    `metrics_router()` to expose `GET /metrics`.
    """
    reg = registry or get_registry()
    requests_total = reg.counter(
        "http_requests_total",
        "Total HTTP requests handled, labeled by method, route template, and status class.",
        ("service", "method", "route", "status_class"),
    )
    duration_seconds = reg.histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds, labeled by method and route template.",
        ("service", "method", "route"),
    )

    @app.middleware("http")
    async def http_metrics_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        route_template = _route_template(request)
        started = time.monotonic()
        try:
            response = await call_next(request)
            status_class = f"{response.status_code // 100}xx"
            return response
        except Exception:
            status_class = "5xx"
            raise
        finally:
            duration = max(0.0, time.monotonic() - started)
            duration_seconds.observe(duration, labels=(service, request.method, route_template))
            requests_total.inc(labels=(service, request.method, route_template, status_class))

    def error_counter(error_code: str, status_code: int) -> None:
        """Called from a service's existing `emg_error_handler` so
        authentication/authorization/validation/upstream failures are
        counted without duplicating the exception-handling call sites."""
        errors_total = reg.counter(
            "http_errors_total",
            "EMGError-mapped HTTP failures, labeled by service, error_code, and status class.",
            ("service", "error_code", "status_class"),
        )
        errors_total.inc(labels=(service, error_code, f"{status_code // 100}xx"))

    app.state.emg_metrics_error_counter = error_counter


def record_http_error(app: FastAPI, error_code: str, status_code: int) -> None:
    """Increment `http_errors_total` for `app`. Safe no-op if
    `install_http_metrics` was never called (keeps error handlers simple)."""
    counter = getattr(app.state, "emg_metrics_error_counter", None)
    if counter is not None:
        counter(error_code, status_code)


def _route_template(request: Request) -> str:
    for route in request.app.routes:
        try:
            match, _ = route.matches(request.scope)
        except Exception:
            continue
        if match == Match.FULL:
            return getattr(route, "path", "unmatched")
    return "unmatched"


def metrics_router(*, registry: MetricsRegistry | None = None) -> APIRouter:
    """Return a FastAPI APIRouter exposing `GET /metrics` in Prometheus text
    exposition format. Unauthenticated, matching the existing `/healthz` and
    `/readyz` ops-route convention (see e.g.
    `emg_knowledge_graph_api.routers.health`); contains only aggregate
    counters/gauges/histograms with a fixed, code-controlled label
    vocabulary, never tenant, entity, principal, or query content."""
    reg = registry or get_registry()
    router = APIRouter(tags=["ops"])

    @router.get("/metrics")
    async def metrics() -> Response:
        return PlainTextResponse(
            reg.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    return router
