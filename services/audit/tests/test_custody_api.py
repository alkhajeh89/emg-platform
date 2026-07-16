"""HTTP-level tests for the chain-of-custody endpoints (FEAT-04-3):
least-privilege service-authenticated record/query/integrity, idempotency,
tamper detection, and route validation."""

from __future__ import annotations

import time

import jwt


def issue_service_token(
    settings,
    private_key,
    *,
    client_id: str = "emg-svc-audit",
    scope: str = "svc-audit",
    exp_delta: int = 300,
    audience: str | None = None,
    issuer: str | None = None,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iat": now,
            "exp": now + exp_delta,
            "iss": issuer if issuer is not None else settings.keycloak_issuer,
            "aud": audience if audience is not None else settings.service_token_audience,
            "azp": client_id,
            "scope": scope,
        },
        private_key,
        algorithm="RS256",
    )


def _custody_token(settings, rsa_keypair) -> str:
    private_key, _ = rsa_keypair
    return issue_service_token(settings, private_key, client_id="emg-svc-audit", scope="svc-audit")


def _custody_event(custody_event_id: str = "c-1", **overrides) -> dict:
    payload = {
        "custody_event_id": custody_event_id,
        "evidence_id": "E1",
        "custody_action": "acquire",
        "custodian": "alice",
        "transfer_reason": "seized at scene",
        "correlation_id": "corr-1",
    }
    payload.update(overrides)
    return payload


# --- authorization: least-privilege, svc-audit only ------------------------


def test_record_custody_requires_a_service_token(client):
    assert client.post("/audit/custody/events", json=_custody_event()).status_code == 401


def test_record_custody_denied_for_non_audit_principal(client, settings, rsa_keypair):
    """svc-identity may ingest audit events but must NOT record custody."""
    private_key, _ = rsa_keypair
    token = issue_service_token(
        settings, private_key, client_id="emg-svc-identity", scope="svc-identity"
    )
    resp = client.post(
        "/audit/custody/events", json=_custody_event(), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


def test_query_custody_denied_for_svc_authorization(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(
        settings, private_key, client_id="emg-svc-authorization", scope="svc-authorization"
    )
    assert (
        client.get(
            "/audit/custody/events", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )


def test_custody_integrity_denied_for_non_audit(client, settings, rsa_keypair):
    private_key, _ = rsa_keypair
    token = issue_service_token(
        settings, private_key, client_id="emg-svc-identity", scope="svc-identity"
    )
    assert (
        client.get(
            "/audit/custody/integrity", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )


# --- record + query roundtrip ----------------------------------------------


def test_record_and_query_custody_roundtrip(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_custody_token(settings, rsa_keypair)}"}
    r1 = client.post(
        "/audit/custody/events", json=_custody_event("c-1", custody_action="acquire"), headers=h
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["chain_sequence"] == 1
    assert body["custody_sequence"] == 1
    assert body["accepted"] is True
    assert len(body["event_hash"]) == 64

    r2 = client.post(
        "/audit/custody/events",
        json=_custody_event(
            "c-2", custody_action="transfer", custodian="bob", prior_custodian="alice"
        ),
        headers=h,
    )
    assert r2.json()["custody_sequence"] == 2  # same evidence item E1

    results = client.get("/audit/custody/events", params={"evidence_id": "E1"}, headers=h).json()
    assert [e["custody_event_id"] for e in results] == ["c-1", "c-2"]
    assert results[1]["prior_custodian"] == "alice"


def test_custody_duplicate_is_idempotent(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_custody_token(settings, rsa_keypair)}"}
    first = client.post("/audit/custody/events", json=_custody_event("dup"), headers=h).json()
    second = client.post(
        "/audit/custody/events", json=_custody_event("dup", custodian="someone-else"), headers=h
    ).json()
    assert first["event_hash"] == second["event_hash"]
    assert first["chain_sequence"] == second["chain_sequence"]
    assert len(client.get("/audit/custody/events", headers=h).json()) == 1


# --- schema / route validation ---------------------------------------------


def test_record_rejects_invalid_custody_action(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_custody_token(settings, rsa_keypair)}"}
    resp = client.post(
        "/audit/custody/events", json=_custody_event(custody_action="teleport"), headers=h
    )
    assert resp.status_code == 422


def test_record_rejects_oversized_reason(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_custody_token(settings, rsa_keypair)}"}
    resp = client.post(
        "/audit/custody/events", json=_custody_event(transfer_reason="x" * 5000), headers=h
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["error_code"] == "CUSTODY_REASON_TOO_LONG"


def test_custody_query_limit_out_of_range_returns_422(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_custody_token(settings, rsa_keypair)}"}
    assert client.get("/audit/custody/events", params={"limit": 0}, headers=h).status_code == 422
    assert (
        client.get("/audit/custody/events", params={"limit": 100000}, headers=h).status_code == 422
    )


# --- integrity / tamper ----------------------------------------------------


def test_custody_integrity_intact(client, settings, rsa_keypair):
    h = {"Authorization": f"Bearer {_custody_token(settings, rsa_keypair)}"}
    for i in range(3):
        client.post("/audit/custody/events", json=_custody_event(f"c-{i}"), headers=h)
    report = client.get("/audit/custody/integrity", headers=h).json()
    assert report["intact"] is True
    assert report["checked_count"] == 3


def test_custody_integrity_detects_tampering(client, settings, rsa_keypair, custody_store):
    h = {"Authorization": f"Bearer {_custody_token(settings, rsa_keypair)}"}
    for i in range(3):
        client.post("/audit/custody/events", json=_custody_event(f"c-{i}"), headers=h)
    original = custody_store._events[1]  # type: ignore[attr-defined]
    custody_store._unsafe_replace_for_tamper_test(
        1, original.model_copy(update={"custodian": "attacker"})
    )
    report = client.get("/audit/custody/integrity", headers=h).json()
    assert report["intact"] is False
    assert report["first_broken_sequence"] == 2
