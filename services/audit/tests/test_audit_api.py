"""HTTP-level tests for the audit service (FEAT-04-1): authenticated ingest,
schema rejection, minimal US-04 query, integrity/tamper, duplicate
idempotency, correlation propagation, redaction, and endpoint authorization."""

from __future__ import annotations

import time

import jwt


def issue_service_token(
    settings,
    private_key,
    *,
    client_id: str = "emg-svc-identity",
    scope: str = "svc-identity",
    exp_delta: int = 300,
    audience: str | None = None,
    issuer: str | None = None,
) -> str:
    now = int(time.time())
    role = scope
    return jwt.encode(
        {
            "iat": now,
            "exp": now + exp_delta,
            "iss": issuer if issuer is not None else settings.keycloak_issuer,
            "aud": audience if audience is not None else settings.service_token_audience,
            "azp": client_id,
            "scope": scope,
            "tenant_id": "tenant-a",
            "classification_clearance": "SECRET",
            "realm_access": {"roles": ["service-account", role]},
        },
        private_key,
        algorithm="RS256",
    )


def _tamper_signature(token: str) -> str:
    """Flip a character in the JWT signature segment so the RS256 signature no
    longer verifies (without changing the header/payload)."""
    header, payload, signature = token.split(".")
    flipped = ("B" if signature[0] != "B" else "C") + signature[1:]
    return f"{header}.{payload}.{flipped}"


def _valid_event(event_id: str = "evt-1", **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "actor": "dev.investigator",
        "actor_type": "human",
        "module": "identity",
        "action": "login",
        "outcome": "success",
        "correlation_id": "corr-1",
        "source_system": "identity",
    }
    payload.update(overrides)
    return payload


# --- authentication / authorization ---------------------------------------


def test_ingest_requires_a_service_token(client):
    response = client.post("/audit/events", json=_valid_event())
    assert response.status_code == 401


def test_ingest_rejects_unrecognized_client(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(settings, private_key, client_id="emg-svc-unknown")
    response = client.post(
        "/audit/events", json=_valid_event(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_query_requires_svc_audit_role(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    # emg-svc-identity may ingest but must NOT be able to read audit records.
    token = issue_service_token(settings, private_key, client_id="emg-svc-identity")
    response = client.get("/audit/events", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_integrity_requires_svc_audit_role(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(settings, private_key, client_id="emg-svc-identity")
    response = client.get("/audit/integrity", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --- adversarial token validation (Sprint 6 security-review fix, Priority 2) --
# The audit service validates inbound service tokens with its own local
# ServiceTokenValidator (duplicated from services/identity — documented as
# technical debt). These negatives exercise that validator directly.


def test_ingest_rejects_expired_token(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(settings, private_key, exp_delta=-100)
    response = client.post(
        "/audit/events", json=_valid_event(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_ingest_rejects_wrong_audience(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(settings, private_key, audience="some-other-audience")
    response = client.post(
        "/audit/events", json=_valid_event(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_ingest_rejects_wrong_issuer(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(settings, private_key, issuer="https://evil.example/realms/emg")
    response = client.post(
        "/audit/events", json=_valid_event(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_ingest_rejects_tampered_signature(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = _tamper_signature(issue_service_token(settings, private_key))
    response = client.post(
        "/audit/events", json=_valid_event(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Authentication failed"
    assert "Signature verification failed" not in response.text


def test_query_denied_for_svc_authorization(client, settings, rsa_keypair):
    """A recognized service that lacks the svc-audit role (svc-authorization)
    is denied audit reads — least-privilege breadth beyond svc-identity."""
    private_key, _ = rsa_keypair
    token = issue_service_token(
        settings, private_key, client_id="emg-svc-authorization", scope="svc-authorization"
    )
    response = client.get("/audit/events", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_integrity_denied_for_svc_authorization(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(
        settings, private_key, client_id="emg-svc-authorization", scope="svc-authorization"
    )
    response = client.get("/audit/integrity", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def _ingest_token(settings, rsa_keypair) -> str:
    private_key, _ = rsa_keypair
    return issue_service_token(settings, private_key, client_id="emg-svc-identity")


def _audit_reader_token(settings, rsa_keypair) -> str:
    private_key, _ = rsa_keypair
    return issue_service_token(settings, private_key, client_id="emg-svc-audit", scope="svc-audit")


# --- positive ingestion + query -------------------------------------------


def test_ingest_and_query_roundtrip(client, settings, rsa_keypair):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}

    resp = client.post("/audit/events", json=_valid_event("evt-1"), headers=ingest_h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["sequence_number"] == 1
    assert body["accepted"] is True
    assert len(body["event_hash"]) == 64

    results = client.get("/audit/events", params={"actor": "dev.investigator"}, headers=read_h)
    assert results.status_code == 200
    events = results.json()
    assert [e["event_id"] for e in events] == ["evt-1"]
    assert events[0]["correlation_id"] == "corr-1"


def test_query_by_correlation_id(client, settings, rsa_keypair):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}
    client.post("/audit/events", json=_valid_event("evt-1", correlation_id="A"), headers=ingest_h)
    client.post("/audit/events", json=_valid_event("evt-2", correlation_id="B"), headers=ingest_h)

    results = client.get("/audit/events", params={"correlation_id": "B"}, headers=read_h)
    assert [e["event_id"] for e in results.json()] == ["evt-2"]


# --- schema rejection ------------------------------------------------------


def test_ingest_rejects_malformed_event(client, settings, rsa_keypair):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    bad = _valid_event()
    del bad["outcome"]  # required field missing
    response = client.post("/audit/events", json=bad, headers=ingest_h)
    assert response.status_code == 422


def test_ingest_rejects_invalid_outcome(client, settings, rsa_keypair):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    response = client.post("/audit/events", json=_valid_event(outcome="maybe"), headers=ingest_h)
    assert response.status_code == 422


def test_ingest_rejects_sensitive_metadata_key(client, settings, rsa_keypair):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    response = client.post(
        "/audit/events",
        json=_valid_event(metadata={"password": "hunter2"}),
        headers=ingest_h,
    )
    assert response.status_code == 400
    assert response.json()["error"]["error_code"] == "AUDIT_METADATA_SENSITIVE_KEY"


# --- duplicate idempotency -------------------------------------------------


def test_duplicate_event_id_from_same_principal_is_idempotent(client, settings, rsa_keypair):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}
    first = client.post("/audit/events", json=_valid_event("dup"), headers=ingest_h).json()
    second = client.post(
        "/audit/events", json=_valid_event("dup", actor="someone-else"), headers=ingest_h
    ).json()
    assert first["event_hash"] == second["event_hash"]
    assert first["sequence_number"] == second["sequence_number"]
    events = client.get("/audit/events", headers=read_h).json()
    assert len(events) == 1


def test_same_event_id_from_different_principals_is_not_suppressed(client, settings, rsa_keypair):
    """Priority 5: source_principal is assigned server-side from the token, and
    idempotency is scoped to (source_principal, event_id). A second producer
    reusing the first's event_id must create a distinct event, not suppress it."""
    private_key, _ = rsa_keypair
    identity_token = issue_service_token(
        settings, private_key, client_id="emg-svc-identity", scope="svc-identity"
    )
    # svc-audit is also a recognized service and may ingest.
    audit_token = issue_service_token(
        settings, private_key, client_id="emg-svc-audit", scope="svc-audit"
    )
    identity_h = {"Authorization": f"Bearer {identity_token}"}
    audit_h = {"Authorization": f"Bearer {audit_token}"}
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}

    first = client.post("/audit/events", json=_valid_event("shared"), headers=identity_h).json()
    second = client.post(
        "/audit/events", json=_valid_event("shared", actor="other"), headers=audit_h
    ).json()

    assert first["sequence_number"] != second["sequence_number"]
    assert first["event_hash"] != second["event_hash"]
    events = client.get("/audit/events", headers=read_h).json()
    # Both events survive; the reused event_id did not suppress the first, and
    # the two carry the distinct server-assigned source_principals.
    principals = {e["source_principal"] for e in events if e["event_id"] == "shared"}
    assert principals == {"emg-svc-identity", "emg-svc-audit"}


def test_query_limit_out_of_range_returns_422(client, settings, rsa_keypair):
    """Priority 6: an out-of-range limit is rejected at the route boundary with
    HTTP 422, not a 500 from downstream model validation."""
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}
    assert client.get("/audit/events", params={"limit": 0}, headers=read_h).status_code == 422
    assert client.get("/audit/events", params={"limit": 100000}, headers=read_h).status_code == 422


# --- redaction ------------------------------------------------------------


def test_bearer_token_in_reason_is_redacted(client, settings, rsa_keypair):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}
    client.post(
        "/audit/events",
        json=_valid_event("evt-1", reason="echo: Authorization: Bearer super.secret.jwt"),
        headers=ingest_h,
    )
    events = client.get("/audit/events", headers=read_h).json()
    assert "super.secret.jwt" not in events[0]["reason"]
    assert "REDACTED" in events[0]["reason"]


# --- integrity / tamper ----------------------------------------------------


def test_integrity_intact_after_ingestion(client, settings, rsa_keypair, store):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}
    for i in range(3):
        client.post("/audit/events", json=_valid_event(f"evt-{i}"), headers=ingest_h)
    report = client.get("/audit/integrity", headers=read_h).json()
    assert report["intact"] is True
    assert report["checked_count"] == 3


def test_integrity_detects_tampering(client, settings, rsa_keypair, store):
    ingest_h = {"Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}"}
    read_h = {"Authorization": f"Bearer {_audit_reader_token(settings, rsa_keypair)}"}
    for i in range(3):
        client.post("/audit/events", json=_valid_event(f"evt-{i}"), headers=ingest_h)

    # Simulate out-of-band mutation of the stored record.
    original = store._events[1]  # type: ignore[attr-defined]
    store._unsafe_replace_for_tamper_test(1, original.model_copy(update={"actor": "attacker"}))

    report = client.get("/audit/integrity", headers=read_h).json()
    assert report["intact"] is False
    assert report["first_broken_sequence"] == 2


# --- correlation propagation ----------------------------------------------


def test_correlation_id_header_is_echoed(client, settings, rsa_keypair):
    ingest_h = {
        "Authorization": f"Bearer {_ingest_token(settings, rsa_keypair)}",
        "X-Correlation-Id": "trace-xyz",
    }
    response = client.post("/audit/events", json=_valid_event(), headers=ingest_h)
    assert response.headers["x-correlation-id"] == "trace-xyz"


# --- health / readiness ----------------------------------------------------


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok", "service": "audit"}


def test_readyz_reports_ready_for_memory_store(client):
    body = client.get("/readyz").json()
    assert body["status"] == "ready"
    assert body["store_backend"] == "memory"
    assert body["store_available"] is True
