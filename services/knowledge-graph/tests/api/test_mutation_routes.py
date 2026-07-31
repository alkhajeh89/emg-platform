"""Focused ADR-027 Revision 5 Phase 4A mutation-router tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
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
from emg_knowledge_graph_api.mutation_preparation import MutationRequestPreparer
from emg_knowledge_graph_api.mutation_response_mapping import mutation_response
from emg_platform_core import PrincipalRef, TenantId
from fastapi.testclient import TestClient

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
TENANT = TenantId.of("phase4a-tenant")
PRINCIPAL = PrincipalRef.service("phase4a-writer")
MUTATION_ID = UUID("11111111-1111-4111-8111-111111111111")
PUBLIC_FIELDS = {
    "tenant_id",
    "revision_number",
    "content_hash",
    "node_count",
    "edge_count",
    "revision_created",
    "nodes_created",
    "edges_created",
    "node_inputs_merged",
    "edge_inputs_merged",
    "mutation_id",
    "audit_reference",
    "replayed",
    "timestamp",
}
HEADERS = {
    "X-Idempotency-Key": "phase4a-key",
    "Preferred-Schema-Version": "1.2.3",
}


def _execution_result() -> MutationExecutionResult:
    result = MutationResult(
        tenant=TENANT,
        principal=PRINCIPAL,
        revision_number=7,
        content_hash="a" * 64,
        node_count=4,
        edge_count=2,
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
        replayed=False,
    )


def _evidence() -> dict[str, object]:
    return {
        "evidence_id": "evidence-1",
        "source": "manual_entry",
        "locator": "case-1",
        "source_principal": "phase4a-writer",
        "captured_at": NOW.isoformat(),
    }


def _node() -> dict[str, object]:
    return {
        "node_id": "entity-1",
        "node_type": "person",
        "label": "Entity One",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "source": "phase4a-writer",
        "confidence": 0.9,
        "classification": "INTERNAL",
        "owner": "phase4a-writer",
        "evidence": [_evidence()],
    }


def _edge() -> dict[str, object]:
    return {
        "edge_id": "relationship-1",
        "edge_type": "owns",
        "source_id": "entity-1",
        "target_id": "entity-2",
        "evidence": [_evidence()],
        "confidence": 0.9,
        "validity": {"valid_from": NOW.isoformat()},
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _create_payload() -> dict[str, object]:
    return {
        "entity": {
            "entity_id": "entity-1",
            "entity_type": "person",
            "classification": "INTERNAL",
            "trust_score": 0.9,
            "provenance_reference": {
                "source_principal": "phase4a-writer",
                "event_id": "event-1",
            },
            "effective_from": NOW.isoformat(),
        },
        "as_of": NOW.isoformat(),
    }


class _Negotiator:
    def __init__(self) -> None:
        self.requests: list[SchemaNegotiationRequest] = []

    def negotiate(self, request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        self.requests.append(request)
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


class _ApplicationSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def _result(self, operation: str, command: object) -> MutationExecutionResult:
        self.calls.append((operation, command))
        return _execution_result()

    def create_entity(self, command: CreateEntityCommand) -> MutationExecutionResult:
        return self._result("create_entity", command)

    def replace_entity(self, command: ReplaceEntityCommand) -> MutationExecutionResult:
        return self._result("replace_entity", command)

    def replace_relationship(self, command: ReplaceRelationshipCommand) -> MutationExecutionResult:
        return self._result("replace_relationship", command)

    def close_relationship(self, command: CloseRelationshipCommand) -> MutationExecutionResult:
        return self._result("close_relationship", command)

    def merge_entities(self, command: MergeEntitiesCommand) -> MutationExecutionResult:
        return self._result("merge_entities", command)


@pytest.fixture
def route_client() -> tuple[TestClient, _ApplicationSpy, _Negotiator]:
    application = _ApplicationSpy()
    negotiator = _Negotiator()
    preparer = MutationRequestPreparer(negotiator, _IdentityCompatibilityAdapters())
    app = create_app()
    app.dependency_overrides[require_tenant_context] = lambda: CallerContext(
        principal=ServicePrincipal(client_id="phase4a-writer"),
        tenant=TENANT,
    )
    app.dependency_overrides[mutation_request_preparer_dependency] = lambda: preparer
    app.dependency_overrides[mutation_knowledge_graph_application_dependency] = lambda: application
    return TestClient(app), application, negotiator


@pytest.mark.parametrize(
    ("method", "path", "payload", "status_code", "operation", "command_type"),
    [
        (
            "POST",
            "/api/v1/entities",
            _create_payload(),
            201,
            "create_entity",
            CreateEntityCommand,
        ),
        (
            "PUT",
            "/api/v1/entities/entity-1",
            {"replacement": _node(), "action": "update", "as_of": NOW.isoformat()},
            200,
            "replace_entity",
            ReplaceEntityCommand,
        ),
        (
            "PUT",
            "/api/v1/relationships/relationship-1",
            {"replacement": _edge(), "as_of": NOW.isoformat()},
            200,
            "replace_relationship",
            ReplaceRelationshipCommand,
        ),
        (
            "POST",
            "/api/v1/relationships/relationship-1/close",
            {
                "edge_id": "relationship-1",
                "as_of": NOW.isoformat(),
                "reason": "relationship ended",
            },
            200,
            "close_relationship",
            CloseRelationshipCommand,
        ),
        (
            "POST",
            "/api/v1/entities/entity-1/merge",
            {
                "survivor_id": "entity-1",
                "source_ids": ["entity-2"],
                "as_of": NOW.isoformat(),
                "reason": "duplicate records",
            },
            200,
            "merge_entities",
            MergeEntitiesCommand,
        ),
    ],
)
def test_mutation_routes_delegate_and_serialize_public_projection(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
    method: str,
    path: str,
    payload: dict[str, object],
    status_code: int,
    operation: str,
    command_type: type[object],
) -> None:
    client, application, negotiator = route_client

    response = client.request(method, path, json=payload, headers=HEADERS)

    assert response.status_code == status_code
    assert response.headers["effective-schema-version"] == "1.2.3"
    assert set(response.json()) == PUBLIC_FIELDS
    assert response.json()["mutation_id"] == str(MUTATION_ID)
    assert response.json()["audit_reference"] == f"audit:{MUTATION_ID}"
    assert "command_fingerprint" not in response.json()
    assert "audit_intents" not in response.json()
    assert negotiator.requests == [SchemaNegotiationRequest(preferred_version="1.2.3")]
    called_operation, command = application.calls[-1]
    assert called_operation == operation
    assert isinstance(command, command_type)
    assert command.tenant == TENANT  # type: ignore[union-attr]
    assert command.principal == PRINCIPAL  # type: ignore[union-attr]
    assert command.idempotency_key == "phase4a-key"  # type: ignore[union-attr]


def test_only_the_five_approved_mutation_routes_are_registered(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
) -> None:
    client, _, _ = route_client
    paths: dict[str, dict[str, Any]] = client.get("/openapi.json").json()["paths"]
    mutation_paths = {
        path: set(methods) & {"get", "post", "put", "patch", "delete"}
        for path, methods in paths.items()
        if path.startswith("/api/v1/")
    }
    assert mutation_paths == {
        "/api/v1/entities": {"post"},
        "/api/v1/entities/{entity_id}": {"put"},
        "/api/v1/relationships/{edge_id}": {"put"},
        "/api/v1/relationships/{edge_id}/close": {"post"},
        "/api/v1/entities/{survivor_id}/merge": {"post"},
    }


def test_openapi_documents_bearer_auth_and_effective_schema_header(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
) -> None:
    client, _, _ = route_client
    schema: dict[str, Any] = client.get("/openapi.json").json()

    assert schema["info"]["title"] == "EMG Knowledge Graph API"
    assert "Read-only" not in schema["info"]["description"]
    bearer = schema["components"]["securitySchemes"]["BearerAuth"]
    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    assert bearer["bearerFormat"] == "JWT"

    operations = (
        ("post", "/api/v1/entities", "201"),
        ("put", "/api/v1/entities/{entity_id}", "200"),
        ("put", "/api/v1/relationships/{edge_id}", "200"),
        ("post", "/api/v1/relationships/{edge_id}/close", "200"),
        ("post", "/api/v1/entities/{survivor_id}/merge", "200"),
    )
    for method, path, success_status in operations:
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"BearerAuth": []}]
        header_parameters = {
            parameter["name"].lower()
            for parameter in operation.get("parameters", [])
            if parameter["in"] == "header"
        }
        assert "authorization" not in header_parameters
        response_header = operation["responses"][success_status]["headers"][
            "Effective-Schema-Version"
        ]
        assert response_header["schema"] == {"type": "string"}


def test_mutation_response_mapping_is_pure_and_excludes_internal_state() -> None:
    mapped = mutation_response(_execution_result())

    assert set(mapped.model_dump()) == PUBLIC_FIELDS
    assert mapped.mutation_id == MUTATION_ID
    assert mapped.audit_reference == f"audit:{MUTATION_ID}"
    assert mapped.timestamp == NOW


def test_unknown_request_fields_are_rejected_before_delegation(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
) -> None:
    client, application, negotiator = route_client
    payload = _create_payload()
    payload["unknown"] = "rejected"

    response = client.post("/api/v1/entities", json=payload, headers=HEADERS)

    assert response.status_code == 422
    assert application.calls == []
    assert negotiator.requests == []


def test_server_controlled_owner_is_rejected_before_delegation(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
) -> None:
    client, application, negotiator = route_client
    payload = _create_payload()
    entity = payload["entity"]
    assert isinstance(entity, dict)
    entity["owner"] = "caller-controlled"

    response = client.post("/api/v1/entities", json=payload, headers=HEADERS)

    assert response.status_code == 422
    assert application.calls == []
    assert negotiator.requests == []


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "PUT",
            "/api/v1/entities/path-entity",
            {"replacement": _node(), "action": "update", "as_of": NOW.isoformat()},
        ),
        (
            "PUT",
            "/api/v1/relationships/path-relationship",
            {"replacement": _edge(), "as_of": NOW.isoformat()},
        ),
        (
            "POST",
            "/api/v1/relationships/path-relationship/close",
            {
                "edge_id": "relationship-1",
                "as_of": NOW.isoformat(),
                "reason": "relationship ended",
            },
        ),
        (
            "POST",
            "/api/v1/entities/path-entity/merge",
            {
                "survivor_id": "entity-1",
                "source_ids": ["entity-2"],
                "as_of": NOW.isoformat(),
                "reason": "duplicate records",
            },
        ),
    ],
)
def test_path_identifier_mismatch_is_rejected_before_preparation(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
    method: str,
    path: str,
    payload: dict[str, object],
) -> None:
    client, application, negotiator = route_client

    response = client.request(method, path, json=payload, headers=HEADERS)

    assert response.status_code == 400
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_INVALID_MUTATION_COMMAND"
    assert application.calls == []
    assert negotiator.requests == []


@pytest.mark.parametrize("missing_header", ["X-Idempotency-Key", "Preferred-Schema-Version"])
def test_required_mutation_headers_are_validated(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
    missing_header: str,
) -> None:
    client, application, negotiator = route_client
    headers = {key: value for key, value in HEADERS.items() if key != missing_header}

    response = client.post("/api/v1/entities", json=_create_payload(), headers=headers)

    assert response.status_code == 422
    assert application.calls == []
    assert negotiator.requests == []


def test_unsupported_schema_is_rejected_before_application_dispatch(
    route_client: tuple[TestClient, _ApplicationSpy, _Negotiator],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, application, negotiator = route_client

    def reject(request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        negotiator.requests.append(request)
        raise SchemaNegotiationError(
            "unknown schema",
            failure_code="UNKNOWN_SCHEMA",
        )

    monkeypatch.setattr(negotiator, "negotiate", reject)

    response = client.post(
        "/api/v1/entities",
        json=_create_payload(),
        headers={**HEADERS, "Preferred-Schema-Version": "9.9.9"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_SCHEMA_NEGOTIATION_FAILED"
    assert negotiator.requests == [SchemaNegotiationRequest(preferred_version="9.9.9")]
    assert application.calls == []
