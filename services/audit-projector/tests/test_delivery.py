from __future__ import annotations

import json

import httpx
import jwt
import pytest
from audit_projector_helpers import ledger, settings
from emg_audit_projector.delivery import AuditDeliveryClient
from emg_audit_projector.errors import (
    CredentialMismatchError,
    RetryableDeliveryError,
    ShutdownRequested,
)
from emg_audit_projector.projection import project_audit_events


def _token(*, tenant_id: str = "tenant-a", client_id: str | None = None) -> str:
    return jwt.encode(
        {
            "tenant_id": tenant_id,
            "azp": client_id or "emg-svc-audit-projector-tenant-a",
        },
        "test-key",
        algorithm="HS256",
    )


def test_credential_tenant_mismatch_fails_closed_before_audit_delivery() -> None:
    audit_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal audit_calls
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": _token(tenant_id="tenant-b")})
        audit_calls += 1
        return httpx.Response(200)

    configured = settings()
    client = AuditDeliveryClient(
        configured,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CredentialMismatchError):
        client.deliver(
            project_audit_events(ledger()),
            credential=configured.tenant_credentials[0],
            shutdown_requested=lambda: False,
        )
    assert audit_calls == 0


def test_audit_outage_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": _token()})
        return httpx.Response(503)

    configured = settings()
    client = AuditDeliveryClient(
        configured,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RetryableDeliveryError):
        client.deliver(
            project_audit_events(ledger()),
            credential=configured.tenant_credentials[0],
            shutdown_requested=lambda: False,
        )


def test_partial_multi_intent_failure_replays_entire_mutation() -> None:
    delivered_ids: list[str] = []
    fail_second = True

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fail_second
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": _token()})
        event_id = json.loads(request.content)["event_id"]
        delivered_ids.append(event_id)
        if fail_second and event_id.endswith(":1"):
            fail_second = False
            return httpx.Response(503)
        return httpx.Response(200)

    configured = settings()
    client = AuditDeliveryClient(
        configured,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    events = project_audit_events(ledger(intent_count=2))

    with pytest.raises(RetryableDeliveryError):
        client.deliver(
            events,
            credential=configured.tenant_credentials[0],
            shutdown_requested=lambda: False,
        )
    client.deliver(
        events,
        credential=configured.tenant_credentials[0],
        shutdown_requested=lambda: False,
    )

    assert [event_id.rsplit(":", 1)[1] for event_id in delivered_ids] == ["0", "1", "0", "1"]


def test_shutdown_between_intents_stops_before_next_http_call() -> None:
    delivered = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delivered
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": _token()})
        delivered += 1
        return httpx.Response(200)

    configured = settings()
    client = AuditDeliveryClient(
        configured,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ShutdownRequested):
        client.deliver(
            project_audit_events(ledger(intent_count=2)),
            credential=configured.tenant_credentials[0],
            shutdown_requested=lambda: delivered == 1,
        )
    assert delivered == 1
