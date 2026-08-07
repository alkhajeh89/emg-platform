"""AC-11 / property 10 -- complete audit attribution, exercised against the
real, unmodified `emg_audit_service` app (see audit_harness.py for why this
harness shape was chosen instead of the shared running emg-audit container).

Also proves the emg_audit_service._RECOGNIZED_CLIENTS constraint the
approved plan called out explicitly: `emg-svc-knowledge-graph-writer` is a
hardcoded, reviewed allowlist entry in production code that this
verification may not modify (no production service-code changes). This
isolated realm deliberately reuses that exact client-id STRING (own random
secret, nothing else shared with production -- see
docs/security/adr-038/04_FINDINGS_AND_EXTERNAL_CONCERNS.md) so the real,
unmodified ingest code path can be exercised end-to-end rather than mocked
around.
"""

from __future__ import annotations

import uuid

import keycloak_client as kc
from audit_harness import build_audit_client
from claim_adapter import to_delegated_credential
from downstream_validator import DownstreamAudienceValidator


def _issuer(env: dict) -> str:
    return f"{env['base_url']}/realms/{env['realm']}"


def test_audit_event_attributes_both_human_principal_and_acting_service(verification_env):
    env = verification_env

    # Real Delegated Credential: Human Principal A, exchanged via the
    # authorized Acting Service, for Audience A.
    human_resp = kc.ropc_login(
        env["base_url"],
        env["realm"],
        "emg-verification-ropc",
        env["EMG_VERIFICATION_ROPC_SECRET"],
        "human-principal-a",
        env["EMG_VERIFICATION_HUMAN_A_PASSWORD"],
    )
    assert human_resp.status == 200, human_resp.body

    exchange_resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        human_resp.body["access_token"],
        "emg-verification-audience-a",
    )
    assert exchange_resp.status == 200, exchange_resp.body

    validator = DownstreamAudienceValidator(
        issuer=_issuer(env),
        audience="emg-verification-audience-a",
        jwks_uri=f"{_issuer(env)}/protocol/openid-connect/certs",
    )
    credential = to_delegated_credential(validator.validate(exchange_resp.body["access_token"]))
    assert credential.human_subject is not None
    assert credential.acting_service is not None

    # The audit PRODUCER credential is a separate, ordinary service-to-service
    # token (ADR-034), authenticated as the recognized emg-svc-knowledge-graph-writer
    # client -- audit ingestion is not itself part of the delegation chain,
    # exactly as production's emg_knowledge_graph_api would call audit using
    # its own service identity, carrying the delegated context in the event body.
    producer_resp = kc.client_credentials(
        env["base_url"],
        env["realm"],
        "emg-svc-knowledge-graph-writer",
        env["EMG_VERIFICATION_KG_WRITER_SECRET"],
    )
    assert producer_resp.status == 200, producer_resp.body

    client, store = build_audit_client(env)
    event_id = f"adr038-verification-{uuid.uuid4()}"
    resp = client.post(
        "/audit/events",
        json={
            "event_id": event_id,
            "actor": credential.human_subject,
            "actor_type": "human",
            "module": "adr-038-verification",
            "action": "delegated-read",
            "outcome": "success",
            "correlation_id": credential.jti,
            "source_system": "adr-038-verification-harness",
            "metadata": {
                "acting_service": credential.acting_service,
                "audience": ",".join(credential.audience),
                "tenant_id": credential.tenant_id or "",
                "classification": credential.classification_clearance or "",
            },
        },
        headers={"Authorization": f"Bearer {producer_resp.body['access_token']}"},
    )
    assert resp.status_code == 200, resp.text

    persisted = [e for e in store._events if e.event_id == event_id]  # type: ignore[attr-defined]
    assert len(persisted) == 1
    event = persisted[0]

    # source_principal is server-assigned from the AUTHENTICATED PRODUCER
    # token -- i.e. the Acting Service's own service identity -- never from
    # producer-supplied content (Sprint 6 security-review fix this repo
    # already made; verified here, not re-implemented).
    assert event.source_principal == "emg-svc-knowledge-graph-writer"
    # actor/actor_type carry the Human Principal, independently.
    assert event.actor == credential.human_subject
    assert event.actor_type == "human"
    assert event.metadata["acting_service"] == credential.acting_service
    assert event.source_principal != event.actor
