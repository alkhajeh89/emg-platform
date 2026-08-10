from __future__ import annotations

from emg_telemetry.http_metrics import install_http_metrics, metrics_router, record_http_error
from emg_telemetry.metrics import MetricsRegistry
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app(registry: MetricsRegistry) -> FastAPI:
    app = FastAPI()
    install_http_metrics(app, service="test-service", registry=registry)
    app.include_router(metrics_router(registry=registry))

    @app.get("/entities/{entity_id}")
    async def get_entity(entity_id: str) -> dict[str, str]:
        return {"id": entity_id}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    return app


def test_metrics_endpoint_exposes_route_template_not_resolved_path():
    """Cardinality/tenant-safety requirement: the entity ID in the resolved
    path must never become (or appear inside) a label value -- only the
    route template does."""
    registry = MetricsRegistry()
    app = _build_app(registry)
    client = TestClient(app, raise_server_exceptions=False)

    client.get("/entities/8f2c9e5e-example-entity-id")

    text = client.get("/metrics").text

    assert 'route="/entities/{entity_id}"' in text
    assert "8f2c9e5e-example-entity-id" not in text


def test_metrics_endpoint_counts_status_classes():
    registry = MetricsRegistry()
    app = _build_app(registry)
    client = TestClient(app, raise_server_exceptions=False)

    client.get("/entities/x")
    client.get("/entities/x")
    client.get("/no-such-route")

    text = client.get("/metrics").text

    assert 'status_class="2xx"' in text
    assert 'route="unmatched"' in text


def test_metrics_endpoint_records_5xx_on_unhandled_exception():
    registry = MetricsRegistry()
    app = _build_app(registry)
    client = TestClient(app, raise_server_exceptions=False)

    client.get("/boom")

    text = client.get("/metrics").text

    assert 'route="/boom"' in text
    assert 'status_class="5xx"' in text


def test_record_http_error_increments_error_counter_by_service_and_code():
    registry = MetricsRegistry()
    app = _build_app(registry)

    record_http_error(app, "AUTHORIZATION_ERROR", 401)
    record_http_error(app, "AUTHORIZATION_ERROR", 401)

    text = registry.render()

    assert (
        'http_errors_total{service="test-service",error_code="AUTHORIZATION_ERROR",'
        'status_class="4xx"} 2.0' in text
    )


def test_record_http_error_is_a_safe_no_op_without_install_http_metrics():
    app = FastAPI()
    # Must not raise even though install_http_metrics() was never called.
    record_http_error(app, "VALIDATION_ERROR", 400)


def test_metrics_response_content_type_is_prometheus_text_format():
    registry = MetricsRegistry()
    app = _build_app(registry)
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
