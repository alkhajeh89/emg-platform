"""ADR-027 Revision 5 Stage 4 Phase 4B mutation observability tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from emg_errors import PermissionDeniedError
from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    MergeEntitiesCommand,
    MutationExecutionResult,
    MutationResult,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
    SchemaNegotiationError,
    SchemaNegotiationRequest,
    SchemaNegotiationResult,
)
from emg_knowledge_graph_api import mutation_observability
from emg_knowledge_graph_api.authn import (
    CallerContext,
    ServicePrincipal,
    require_tenant_context,
)
from emg_knowledge_graph_api.dependencies import (
    mutation_knowledge_graph_application_dependency,
    mutation_request_preparer_dependency,
)
from emg_knowledge_graph_api.main import create_app
from emg_knowledge_graph_api.mutation_observability import (
    MutationMetric,
    MutationOperation,
)
from emg_knowledge_graph_api.mutation_preparation import MutationRequestPreparer
from emg_platform_core import PrincipalRef, TenantId
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
TENANT_VALUE = "canary-tenant-secret"
PRINCIPAL_VALUE = "canary-principal-secret"
IDEMPOTENCY_VALUE = "canary-idempotency-secret"
SCHEMA_VALUE = "canary-schema-secret"
PAYLOAD_VALUE = "canary-payload-secret"
ENTITY_VALUE = "canary-entity-secret"
EDGE_VALUE = "canary-edge-secret"
REASON_VALUE = "canary-reason-secret"
POLICY_VALUE = "canary-policy-reason"
TENANT = TenantId.of(TENANT_VALUE)
PRINCIPAL = PrincipalRef.service(PRINCIPAL_VALUE)
MUTATION_ID = UUID("22222222-2222-4222-8222-222222222222")
HEADERS = {
    "X-Idempotency-Key": IDEMPOTENCY_VALUE,
    "Preferred-Schema-Version": SCHEMA_VALUE,
    "X-Correlation-ID": "phase4b-correlation",
}


class _LogSpy:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.extras: list[dict[str, str]] = []

    def info(self, message: str, *, extra: dict[str, str]) -> None:
        self.messages.append(message)
        self.extras.append(extra)


class _RaisingLog:
    def info(self, message: str, *, extra: dict[str, str]) -> None:
        raise RuntimeError("telemetry sink unavailable")


class _Negotiator:
    def __init__(self, error: SchemaNegotiationError | None = None) -> None:
        self.error = error
        self.requests: list[SchemaNegotiationRequest] = []

    def negotiate(self, request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return SchemaNegotiationResult(effective_version=request.preferred_version)


class _IdentityCompatibilityAdapters:
    def normalize(
        self,
        request: Any,
        *,
        source_version: str,
        target_version: str | None = None,
    ) -> Any:
        return request


class _Application:
    def __init__(
        self,
        *,
        replayed: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.replayed = replayed
        self.error = error
        self.calls: list[str] = []

    def _execute(self, operation: str) -> MutationExecutionResult:
        self.calls.append(operation)
        if self.error is not None:
            raise self.error
        return _execution_result(replayed=self.replayed)

    def create_entity(self, command: CreateEntityCommand) -> MutationExecutionResult:
        return self._execute("create_entity")

    def replace_entity(self, command: ReplaceEntityCommand) -> MutationExecutionResult:
        return self._execute("replace_entity")

    def replace_relationship(self, command: ReplaceRelationshipCommand) -> MutationExecutionResult:
        return self._execute("replace_relationship")

    def close_relationship(self, command: CloseRelationshipCommand) -> MutationExecutionResult:
        return self._execute("close_relationship")

    def merge_entities(self, command: MergeEntitiesCommand) -> MutationExecutionResult:
        return self._execute("merge_entities")


def _execution_result(*, replayed: bool) -> MutationExecutionResult:
    result = MutationResult(
        tenant=TENANT,
        principal=PRINCIPAL,
        revision_number=11,
        content_hash="b" * 64,
        node_count=3,
        edge_count=1,
        revision_created=True,
        nodes_created=1,
        edges_created=0,
        node_inputs_merged=0,
        edge_inputs_merged=0,
        audit_intents=(),
    )
    return MutationExecutionResult.from_mutation(
        result,
        mutation_id=MUTATION_ID,
        ledger_completed_at=NOW,
        replayed=replayed,
    )


def _evidence() -> dict[str, object]:
    return {
        "evidence_id": "canary-evidence-secret",
        "source": "manual_entry",
        "locator": PAYLOAD_VALUE,
        "source_principal": PRINCIPAL_VALUE,
        "captured_at": NOW.isoformat(),
    }


def _node() -> dict[str, object]:
    return {
        "node_id": ENTITY_VALUE,
        "node_type": PAYLOAD_VALUE,
        "label": PAYLOAD_VALUE,
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "source": PRINCIPAL_VALUE,
        "confidence": 0.9,
        "classification": "SECRET",
        "owner": PRINCIPAL_VALUE,
        "evidence": [_evidence()],
    }


def _edge() -> dict[str, object]:
    return {
        "edge_id": EDGE_VALUE,
        "edge_type": PAYLOAD_VALUE,
        "source_id": ENTITY_VALUE,
        "target_id": "canary-target-secret",
        "evidence": [_evidence()],
        "confidence": 0.9,
        "validity": {"valid_from": NOW.isoformat()},
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "classification": "SECRET",
    }


def _create_payload() -> dict[str, object]:
    return {
        "entity": {
            "entity_id": ENTITY_VALUE,
            "entity_type": PAYLOAD_VALUE,
            "classification": "SECRET",
            "trust_score": 0.9,
            "provenance_reference": {
                "source_principal": PRINCIPAL_VALUE,
                "event_id": "canary-event-secret",
            },
            "effective_from": NOW.isoformat(),
        },
        "as_of": NOW.isoformat(),
    }


ROUTES: tuple[tuple[str, str, dict[str, object], int, MutationOperation], ...] = (
    ("POST", "/api/v1/entities", _create_payload(), 201, MutationOperation.CREATE_ENTITY),
    (
        "PUT",
        f"/api/v1/entities/{ENTITY_VALUE}",
        {"replacement": _node(), "action": "update", "as_of": NOW.isoformat()},
        200,
        MutationOperation.REPLACE_ENTITY,
    ),
    (
        "PUT",
        f"/api/v1/relationships/{EDGE_VALUE}",
        {"replacement": _edge(), "as_of": NOW.isoformat()},
        200,
        MutationOperation.REPLACE_RELATIONSHIP,
    ),
    (
        "POST",
        f"/api/v1/relationships/{EDGE_VALUE}/close",
        {"edge_id": EDGE_VALUE, "as_of": NOW.isoformat(), "reason": REASON_VALUE},
        200,
        MutationOperation.CLOSE_RELATIONSHIP,
    ),
    (
        "POST",
        f"/api/v1/entities/{ENTITY_VALUE}/merge",
        {
            "survivor_id": ENTITY_VALUE,
            "source_ids": ["canary-source-secret"],
            "as_of": NOW.isoformat(),
            "reason": REASON_VALUE,
        },
        200,
        MutationOperation.MERGE_ENTITIES,
    ),
)


def _events(log: _LogSpy) -> list[dict[str, object]]:
    return [json.loads(message) for message in log.messages]


def _metric_events(log: _LogSpy, metric: MutationMetric) -> list[dict[str, object]]:
    return [event for event in _events(log) if event.get("metric_name") == metric.value]


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    replayed: bool = False,
    application_error: Exception | None = None,
    negotiation_error: SchemaNegotiationError | None = None,
    authenticate: bool = True,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, _Application, _LogSpy]:
    log = _LogSpy()
    monkeypatch.setattr(mutation_observability, "_log", log)
    application = _Application(replayed=replayed, error=application_error)
    preparer = MutationRequestPreparer(
        _Negotiator(negotiation_error),
        _IdentityCompatibilityAdapters(),
    )
    app = create_app()
    if authenticate:
        app.dependency_overrides[require_tenant_context] = lambda: CallerContext(
            principal=ServicePrincipal(
                client_id=PRINCIPAL_VALUE,
                roles=("canary-role-secret",),
                scopes=("canary-scope-secret",),
            ),
            tenant=TENANT,
        )
    app.dependency_overrides[mutation_request_preparer_dependency] = lambda: preparer
    app.dependency_overrides[mutation_knowledge_graph_application_dependency] = lambda: application
    return (
        TestClient(app, raise_server_exceptions=raise_server_exceptions),
        application,
        log,
    )


@pytest.mark.parametrize(("method", "path", "payload", "status", "operation"), ROUTES)
def test_all_five_routes_emit_request_and_latency_observations(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, object],
    status: int,
    operation: MutationOperation,
) -> None:
    client, application, log = _client(monkeypatch)

    response = client.request(method, path, json=payload, headers=HEADERS)

    assert response.status_code == status
    assert application.calls == [operation.value]
    request_events = _metric_events(log, MutationMetric.REQUESTS)
    latency_events = _metric_events(log, MutationMetric.LATENCY)
    assert request_events == [
        {
            "event": "mutation_metric",
            "metric_name": "mutation_requests_total",
            "metric_type": "counter",
            "metric_value": 1,
            "operation": operation.value,
            "outcome": "success",
        }
    ]
    assert len(latency_events) == 1
    assert latency_events[0]["operation"] == operation.value
    assert latency_events[0]["outcome"] == "success"
    assert isinstance(latency_events[0]["metric_value"], float)
    assert latency_events[0]["metric_value"] >= 0.0


def test_operation_and_outcome_vocabularies_are_fixed() -> None:
    assert {operation.value for operation in MutationOperation} == {
        "create_entity",
        "replace_entity",
        "replace_relationship",
        "close_relationship",
        "merge_entities",
    }
    assert {outcome.value for outcome in mutation_observability.MutationOutcome} == {
        "success",
        "rejected",
        "failure",
    }
    assert {metric.value for metric in MutationMetric} == {
        "mutation_requests_total",
        "mutation_latency_seconds",
        "idempotency_hits_total",
        "authorization_denials_total",
    }


@pytest.mark.parametrize("replayed", [False, True])
def test_only_replayed_result_emits_idempotency_hit(
    monkeypatch: pytest.MonkeyPatch,
    replayed: bool,
) -> None:
    client, _, log = _client(monkeypatch, replayed=replayed)

    response = client.post("/api/v1/entities", json=_create_payload(), headers=HEADERS)

    assert response.status_code == 201
    hits = _metric_events(log, MutationMetric.IDEMPOTENCY_HITS)
    assert len(hits) == int(replayed)
    if replayed:
        assert hits[0]["operation"] == "create_entity"
        assert hits[0]["outcome"] == "success"


@pytest.mark.parametrize("rejection", ["validation", "schema", "path"])
def test_transport_rejections_emit_rejected_outcome(
    monkeypatch: pytest.MonkeyPatch,
    rejection: str,
) -> None:
    negotiation_error = (
        SchemaNegotiationError("canary schema detail", failure_code="UNKNOWN_SCHEMA")
        if rejection == "schema"
        else None
    )
    client, application, log = _client(monkeypatch, negotiation_error=negotiation_error)
    payload = _create_payload()
    path = "/api/v1/entities"
    expected_status = 422
    if rejection == "validation":
        payload["canary_unknown_field"] = PAYLOAD_VALUE
    elif rejection == "path":
        path = "/api/v1/entities/different-path-entity"
        payload = {"replacement": _node(), "action": "update", "as_of": NOW.isoformat()}
        expected_status = 400

    response = client.request(
        "POST" if rejection != "path" else "PUT",
        path,
        json=payload,
        headers=HEADERS,
    )

    assert response.status_code == expected_status
    assert application.calls == []
    assert _metric_events(log, MutationMetric.REQUESTS)[0]["outcome"] == "rejected"
    assert _metric_events(log, MutationMetric.LATENCY)[0]["outcome"] == "rejected"


def test_application_failure_emits_failure_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, application, log = _client(
        monkeypatch,
        application_error=RuntimeError("canary application detail"),
        raise_server_exceptions=False,
    )

    response = client.post("/api/v1/entities", json=_create_payload(), headers=HEADERS)

    assert response.status_code == 500
    assert application.calls == ["create_entity"]
    assert _metric_events(log, MutationMetric.REQUESTS)[0]["outcome"] == "failure"
    assert _metric_events(log, MutationMetric.LATENCY)[0]["outcome"] == "failure"


def test_permission_denial_emits_once_and_preserves_403_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, application, log = _client(
        monkeypatch,
        application_error=PermissionDeniedError(POLICY_VALUE),
    )

    response = client.post("/api/v1/entities", json=_create_payload(), headers=HEADERS)

    assert response.status_code == 403
    assert response.json()["error"] == {
        "error_code": "PERMISSION_DENIED",
        "message": "Access denied",
    }
    assert application.calls == ["create_entity"]
    denials = _metric_events(log, MutationMetric.AUTHORIZATION_DENIALS)
    assert len(denials) == 1
    assert denials[0]["operation"] == "create_entity"
    assert denials[0]["outcome"] == "rejected"


def test_authentication_failure_is_not_an_authorization_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, application, log = _client(monkeypatch, authenticate=False)

    response = client.post("/api/v1/entities", json=_create_payload(), headers=HEADERS)

    assert response.status_code == 401
    assert application.calls == []
    assert _metric_events(log, MutationMetric.AUTHORIZATION_DENIALS) == []
    assert _metric_events(log, MutationMetric.REQUESTS)[0]["outcome"] == "rejected"


def test_read_only_route_emits_no_mutation_observations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _LogSpy()
    monkeypatch.setattr(mutation_observability, "_log", log)

    response = client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code == 200
    assert log.messages == []


def test_unknown_route_and_method_mismatch_emit_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, application, log = _client(monkeypatch)

    unknown = client.get("/api/v1/not-a-mutation")
    wrong_method = client.delete("/api/v1/entities")

    assert unknown.status_code == 404
    assert wrong_method.status_code == 405
    assert application.calls == []
    assert log.messages == []


def test_latency_helper_uses_injected_clock_and_never_returns_negative() -> None:
    assert mutation_observability._elapsed_seconds(10.0, clock=lambda: 10.25) == 0.25
    assert mutation_observability._elapsed_seconds(10.0, clock=lambda: 9.75) == 0.0


def test_serialized_telemetry_is_allowlisted_and_contains_no_canaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, application, log = _client(monkeypatch)
    create_response = client.post(
        "/api/v1/entities",
        json=_create_payload(),
        headers=HEADERS,
    )
    merge_response = client.post(
        f"/api/v1/entities/{ENTITY_VALUE}/merge",
        json={
            "survivor_id": ENTITY_VALUE,
            "source_ids": ["canary-source-secret"],
            "as_of": NOW.isoformat(),
            "reason": REASON_VALUE,
        },
        headers=HEADERS,
    )
    assert create_response.status_code == 201
    assert merge_response.status_code == 200
    application.error = PermissionDeniedError(POLICY_VALUE)
    denied_response = client.post(
        "/api/v1/entities",
        json=_create_payload(),
        headers=HEADERS,
    )
    assert denied_response.status_code == 403

    metric_keys = {
        "event",
        "metric_name",
        "metric_type",
        "metric_value",
        "operation",
        "outcome",
    }
    completion_keys = {
        "event",
        "operation",
        "outcome",
        "status_code",
        "duration_seconds",
    }
    for event in _events(log):
        expected = metric_keys if event["event"] == "mutation_metric" else completion_keys
        assert set(event) == expected
    assert all(set(extra) == {"actor", "module", "action", "outcome"} for extra in log.extras)

    serialized = "\n".join((*log.messages, *(json.dumps(extra) for extra in log.extras)))
    prohibited = {
        TENANT_VALUE,
        PRINCIPAL_VALUE,
        "canary-role-secret",
        "canary-scope-secret",
        IDEMPOTENCY_VALUE,
        SCHEMA_VALUE,
        PAYLOAD_VALUE,
        ENTITY_VALUE,
        EDGE_VALUE,
        REASON_VALUE,
        POLICY_VALUE,
        "SECRET",
        str(MUTATION_ID),
        f"audit:{MUTATION_ID}",
    }
    assert all(value not in serialized for value in prohibited)


def test_emitter_failure_does_not_change_response_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_client, control_application, _ = _client(monkeypatch)
    control = control_client.post("/api/v1/entities", json=_create_payload(), headers=HEADERS)

    monkeypatch.setattr(mutation_observability, "_log", _RaisingLog())
    application = _Application()
    preparer = MutationRequestPreparer(_Negotiator(), _IdentityCompatibilityAdapters())
    app = create_app()
    app.dependency_overrides[require_tenant_context] = lambda: CallerContext(
        principal=ServicePrincipal(client_id=PRINCIPAL_VALUE),
        tenant=TENANT,
    )
    app.dependency_overrides[mutation_request_preparer_dependency] = lambda: preparer
    app.dependency_overrides[mutation_knowledge_graph_application_dependency] = lambda: application
    failed_emitter = TestClient(app).post(
        "/api/v1/entities",
        json=_create_payload(),
        headers=HEADERS,
    )

    assert failed_emitter.status_code == control.status_code == 201
    assert failed_emitter.json() == control.json()
    assert dict(failed_emitter.headers) == dict(control.headers)
    assert control_application.calls == application.calls == ["create_entity"]
