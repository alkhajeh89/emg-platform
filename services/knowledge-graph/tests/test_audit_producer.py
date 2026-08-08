"""Direct unit tests for `audit_producer.emit_delegated_audit_event`'s
outbound HTTP call shape — final correction-sprint Finding 7."""

from __future__ import annotations

import httpx
import pytest
from emg_auth_client import Principal
from emg_knowledge_graph_api import audit_producer
from emg_knowledge_graph_api.authn import CallerContext
from emg_knowledge_graph_api.config import Settings
from emg_platform_core import TenantId


class _RecordingAsyncClient:
    calls: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, json=None, headers=None, **kwargs):
        _RecordingAsyncClient.calls.append((url, {"json": json, "headers": headers or {}}))
        if "/audit/events" in url:
            return httpx.Response(200, json={"event_id": "evt-1", "accepted": True})
        return httpx.Response(200, json={"access_token": "producer-token", "expires_in": 300})


@pytest.fixture(autouse=True)
def _reset_calls():
    _RecordingAsyncClient.calls = []
    yield
    _RecordingAsyncClient.calls = []


@pytest.fixture
def settings() -> Settings:
    return Settings(
        keycloak_base_url="http://keycloak.test",
        keycloak_realm="emg-test",
        audit_service_base_url="http://audit.test",
    )


@pytest.fixture
def delegated_caller() -> CallerContext:
    return CallerContext(
        principal=Principal(
            subject="human-a", roles=(), attributes={"classification_clearance": "SECRET"}
        ),
        tenant=TenantId.of("tenant-a"),
        acting_service="emg-studio-bff",
    )


@pytest.mark.asyncio
async def test_correlation_id_header_matches_the_passed_value(
    monkeypatch, settings, delegated_caller
):
    monkeypatch.setattr(audit_producer.httpx, "AsyncClient", _RecordingAsyncClient)

    await audit_producer.emit_delegated_audit_event(
        settings,
        delegated_caller,
        resource_type="knowledge-graph.entity",
        resource_id="e1",
        correlation_id="corr-abc-123",
    )

    audit_call = next(c for c in _RecordingAsyncClient.calls if "/audit/events" in c[0])
    assert audit_call[1]["headers"]["x-correlation-id"] == "corr-abc-123"
    assert audit_call[1]["headers"]["Authorization"] == "Bearer producer-token"


@pytest.mark.asyncio
async def test_correlation_id_header_is_empty_string_when_none(
    monkeypatch, settings, delegated_caller
):
    """Never a literal `None` in the header value — matches the same
    `correlation_id or ""` convention `knowledge_graph_proxy.py` (BFF side)
    already established."""
    monkeypatch.setattr(audit_producer.httpx, "AsyncClient", _RecordingAsyncClient)

    await audit_producer.emit_delegated_audit_event(
        settings,
        delegated_caller,
        resource_type="knowledge-graph.entity",
        resource_id="e1",
        correlation_id=None,
    )

    audit_call = next(c for c in _RecordingAsyncClient.calls if "/audit/events" in c[0])
    assert audit_call[1]["headers"]["x-correlation-id"] == ""
