from __future__ import annotations

import time
from typing import Any, cast

import httpx
import jwt
from audit_projector_helpers import ledger, settings
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_audit_client import AuditQuery
from emg_audit_pipeline import InMemoryAuditEventStore, InMemoryCustodyEventStore
from emg_audit_projector.delivery import AuditDeliveryClient
from emg_audit_projector.projection import project_audit_events
from emg_audit_service.authn import (
    ServiceTokenValidator,
    service_token_validator_dependency,
    settings_dependency,
)
from emg_audit_service.config import Settings as AuditSettings
from emg_audit_service.main import create_app
from emg_audit_service.store import custody_store_dependency, store_dependency
from fastapi.testclient import TestClient


class _AuditBridge:
    def __init__(self, audit: TestClient, token: str, token_endpoint: str) -> None:
        self.audit = audit
        self.token = token
        self.token_endpoint = token_endpoint

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        if url == self.token_endpoint:
            return httpx.Response(200, json={"access_token": self.token})
        response = self.audit.post("/audit/events", **kwargs)
        return httpx.Response(response.status_code, json=response.json())

    def close(self) -> None:
        return None


def test_projector_delivers_to_real_audit_api_and_duplicate_replay_is_idempotent() -> None:
    configured = settings()
    credential = configured.tenant_credentials[0]
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": "http://keycloak.test/realms/emg-test",
            "aud": "emg-internal-services",
            "azp": credential.client_id,
            "tenant_id": credential.tenant_id,
            "realm_access": {"roles": ["service-account", "svc-audit-projector"]},
        },
        private_key,
        algorithm="RS256",
    )
    audit_settings = AuditSettings(
        store_backend="memory",
        keycloak_base_url="http://keycloak.test",
        keycloak_realm="emg-test",
        projector_client_ids=(credential.client_id,),
    )
    store = InMemoryAuditEventStore()
    app = create_app()
    app.dependency_overrides[settings_dependency] = lambda: audit_settings
    app.dependency_overrides[service_token_validator_dependency] = lambda: (
        ServiceTokenValidator(
            audit_settings, signing_key_resolver=lambda supplied: private_key.public_key()
        )
    )
    app.dependency_overrides[store_dependency] = lambda: store
    app.dependency_overrides[custody_store_dependency] = lambda: InMemoryCustodyEventStore()

    audit = TestClient(app)
    bridge = _AuditBridge(audit, token, configured.token_endpoint)
    delivery = AuditDeliveryClient(configured, client=cast(Any, bridge))
    events = project_audit_events(ledger(intent_count=2))
    delivery.deliver(events, credential=credential, shutdown_requested=lambda: False)
    delivery.deliver(events, credential=credential, shutdown_requested=lambda: False)

    persisted = store.query(AuditQuery(tenant_id="tenant-a"))
    assert [event.event_id for event in persisted] == [
        events[0].event_id,
        events[1].event_id,
    ]
    assert all(event.source_principal == credential.client_id for event in persisted)
