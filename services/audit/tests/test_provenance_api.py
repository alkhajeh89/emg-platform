"""HTTP-level tests for provenance-carrying ingestion (FEAT-04-2): an audit
event submitted with a provenance record is accepted, persisted as a
schema-version-2 event, and keeps the hash chain intact. Ingesting without
provenance stays a version-1 event (Sprint 6 behavior, unchanged)."""

from __future__ import annotations

import time

import jwt


def _token(settings, private_key, *, client_id="emg-svc-identity", scope="svc-identity") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iat": now,
            "exp": now + 300,
            "iss": settings.keycloak_issuer,
            "aud": settings.service_token_audience,
            "azp": client_id,
            "scope": scope,
        },
        private_key,
        algorithm="RS256",
    )


def _event_with_provenance(event_id="evt-prov") -> dict:
    return {
        "event_id": event_id,
        "actor": "dev.investigator",
        "actor_type": "human",
        "module": "identity",
        "action": "login",
        "outcome": "success",
        "correlation_id": "corr-1",
        "source_system": "identity",
        "provenance": {
            "source_system": "identity",
            "source_component": "login-handler",
            "originating_actor": "dev.investigator",
            "originating_principal": "emg-svc-identity",
            "correlation_id": "corr-1",
            "event_time": "2026-07-01T11:59:00+00:00",
            "ingest_time": "2026-07-01T12:00:00+00:00",
            "classification": "INTERNAL",
            "transformation_history": [{"step": "normalized", "detail": "lowercased"}],
            "parent_event_refs": [
                {"source_principal": "emg-svc-identity", "event_id": "evt-parent"}
            ],
            "evidence_origin": "sensor-A",
            "collection_method": "automated",
        },
    }


def test_ingest_with_provenance_persists_version_2(client, settings, rsa_keypair, store):
    private_key, _ = rsa_keypair
    ingest_h = {"Authorization": f"Bearer {_token(settings, private_key)}"}
    resp = client.post("/audit/events", json=_event_with_provenance("evt-prov"), headers=ingest_h)
    assert resp.status_code == 200
    persisted = store._events[0]  # type: ignore[attr-defined]
    assert persisted.schema_version == 2
    assert persisted.provenance is not None
    assert persisted.provenance.evidence_origin == "sensor-A"


def test_ingest_with_provenance_keeps_chain_intact(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    ingest_h = {"Authorization": f"Bearer {_token(settings, private_key)}"}
    reader = _token(settings, private_key, client_id="emg-svc-audit", scope="svc-audit")
    read_h = {"Authorization": f"Bearer {reader}"}
    # Mix a version-1 and a version-2 event; the chain must stay intact.
    client.post(
        "/audit/events",
        json={
            "event_id": "evt-v1",
            "actor": "a",
            "actor_type": "human",
            "module": "identity",
            "action": "login",
            "outcome": "success",
            "source_system": "identity",
        },
        headers=ingest_h,
    )
    client.post("/audit/events", json=_event_with_provenance("evt-v2"), headers=ingest_h)
    report = client.get("/audit/integrity", headers=read_h).json()
    assert report["intact"] is True
    assert report["checked_count"] == 2


def test_ingest_rejects_oversized_provenance(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    ingest_h = {"Authorization": f"Bearer {_token(settings, private_key)}"}
    payload = _event_with_provenance("evt-bad")
    payload["provenance"]["evidence_origin"] = "x" * 5000
    resp = client.post("/audit/events", json=payload, headers=ingest_h)
    assert resp.status_code == 400
    assert resp.json()["error"]["error_code"] == "AUDIT_PROVENANCE_VALUE_TOO_LONG"
