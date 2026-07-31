"""Error-to-HTTP mapping, real auth-rejection path, and OpenAPI registration.

Uses a minimal fake application-service stub (not `KnowledgeGraphApplication`
itself) to force each `emg_knowledge_graph` error type on demand, proving the
router's error translation is generic (driven by `ERROR_STATUS_MAP` against
the shared `EMGError` handler) rather than hand-mapped per endpoint. This is
HTTP-boundary testing throughout — only `TestClient` requests, never a direct
call into a router function.
"""

from __future__ import annotations

import pytest
from emg_errors import AuthorizationError, PermissionDeniedError
from emg_knowledge_graph import (
    EdgeNotFoundError,
    EntityNotFoundError,
    IdempotencyContentionError,
    IdempotencyMismatchError,
    InvalidMutationCommandError,
    InvalidQueryError,
    InvalidTemporalFilterError,
    LegacyIdempotencyConflictError,
    MutationBuildError,
    MutationReplayIntegrityError,
    MutationResourceMetadataError,
    PathDepthExceededError,
    QueryLimitExceededError,
    RevisionNotFoundError,
    SchemaNegotiationError,
    UnsupportedFingerprintVersionError,
    UnsupportedHistoryCapabilityError,
)
from emg_knowledge_graph_api.authn import CallerContext, require_tenant_context
from emg_knowledge_graph_api.dependencies import (
    knowledge_graph_application_dependency,
    policy_enforcement_point_dependency,
)
from emg_knowledge_graph_api.main import create_app
from emg_persistence import PersistenceConflictError
from emg_policy_engine import LocalPolicyEnforcementPoint, load_policy_config
from fastapi.testclient import TestClient

from .conftest import POLICY_CONFIG_PATH


def _real_policy_enforcement_point() -> LocalPolicyEnforcementPoint:
    return LocalPolicyEnforcementPoint(load_policy_config(POLICY_CONFIG_PATH))


class _RaisingApplication:
    """Stands in for `KnowledgeGraphApplication`: every query method raises
    the one error the test configures, letting each mapped error type be
    exercised at the HTTP boundary without needing a real graph fixture for
    each one."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def get_entity(self, query: object) -> object:
        raise self._error

    def list_entities(self, query: object) -> object:
        raise self._error

    def get_edge(self, query: object) -> object:
        raise self._error

    def list_edges(self, query: object) -> object:
        raise self._error

    def list_neighbors(self, query: object) -> object:
        raise self._error

    def find_shortest_path(self, query: object) -> object:
        raise self._error

    def get_entity_history(self, query: object) -> object:
        raise self._error


def _client_raising(error: Exception, *, caller_context: CallerContext) -> TestClient:
    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: _RaisingApplication(
        error
    )
    app.dependency_overrides[require_tenant_context] = lambda: caller_context
    app.dependency_overrides[policy_enforcement_point_dependency] = _real_policy_enforcement_point
    return TestClient(app)


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (EntityNotFoundError("no such entity"), 404, "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"),
        (EdgeNotFoundError("no such edge"), 404, "KNOWLEDGE_GRAPH_EDGE_NOT_FOUND"),
        (RevisionNotFoundError("no such revision"), 404, "KNOWLEDGE_GRAPH_REVISION_NOT_FOUND"),
        (InvalidQueryError("bad query"), 422, "KNOWLEDGE_GRAPH_INVALID_QUERY"),
        (QueryLimitExceededError("too many"), 422, "KNOWLEDGE_GRAPH_QUERY_LIMIT_EXCEEDED"),
        (PathDepthExceededError("too deep"), 422, "KNOWLEDGE_GRAPH_PATH_DEPTH_EXCEEDED"),
        (
            InvalidTemporalFilterError("bad valid_at"),
            422,
            "KNOWLEDGE_GRAPH_INVALID_TEMPORAL_FILTER",
        ),
        (
            UnsupportedHistoryCapabilityError("no revision reader configured"),
            501,
            "KNOWLEDGE_GRAPH_UNSUPPORTED_HISTORY_CAPABILITY",
        ),
    ],
)
def test_application_error_mapped_to_stable_http_response(
    error: Exception,
    expected_status: int,
    expected_code: str,
    caller_context_a: CallerContext,
) -> None:
    client = _client_raising(error, caller_context=caller_context_a)
    response = client.get("/v1/knowledge-graph/entities/whatever")
    assert response.status_code == expected_status
    body = response.json()
    assert body["error"]["error_code"] == expected_code
    assert body["data"] is None
    assert "correlation_id" in body
    # No stack trace or persistence detail leaks into the response.
    assert "Traceback" not in response.text
    assert "psycopg" not in response.text


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "retry_after"),
    [
        (
            InvalidMutationCommandError("invalid mutation"),
            400,
            "KNOWLEDGE_GRAPH_INVALID_MUTATION_COMMAND",
            None,
        ),
        (
            MutationResourceMetadataError("resource unavailable"),
            404,
            "KNOWLEDGE_GRAPH_MUTATION_RESOURCE_METADATA",
            None,
        ),
        (
            IdempotencyMismatchError("key mismatch"),
            409,
            "KNOWLEDGE_GRAPH_IDEMPOTENCY_MISMATCH",
            None,
        ),
        (
            LegacyIdempotencyConflictError("legacy key conflict"),
            409,
            "KNOWLEDGE_GRAPH_LEGACY_IDEMPOTENCY_CONFLICT",
            None,
        ),
        (
            PersistenceConflictError("head advanced"),
            409,
            "EMG_ERROR",
            None,
        ),
        (
            MutationBuildError("semantic mutation failure"),
            422,
            "KNOWLEDGE_GRAPH_MUTATION_BUILD_FAILED",
            None,
        ),
        (
            IdempotencyContentionError("claim timeout"),
            503,
            "KNOWLEDGE_GRAPH_IDEMPOTENCY_CONTENTION",
            "1",
        ),
        (
            UnsupportedFingerprintVersionError("reader unavailable"),
            503,
            "KNOWLEDGE_GRAPH_UNSUPPORTED_FINGERPRINT_VERSION",
            None,
        ),
        (
            MutationReplayIntegrityError("corrupt replay"),
            500,
            "KNOWLEDGE_GRAPH_MUTATION_REPLAY_INTEGRITY",
            None,
        ),
        (
            SchemaNegotiationError("unknown schema", failure_code="UNKNOWN_SCHEMA"),
            422,
            "KNOWLEDGE_GRAPH_SCHEMA_NEGOTIATION_FAILED",
            None,
        ),
        (
            SchemaNegotiationError("adapter failed", failure_code="ADAPTER_FAILURE"),
            500,
            "KNOWLEDGE_GRAPH_SCHEMA_NEGOTIATION_FAILED",
            None,
        ),
    ],
)
def test_mutation_error_mapped_to_stable_http_response(
    error: Exception,
    expected_status: int,
    expected_code: str,
    retry_after: str | None,
    caller_context_a: CallerContext,
) -> None:
    client = _client_raising(error, caller_context=caller_context_a)

    response = client.get("/v1/knowledge-graph/entities/whatever")

    assert response.status_code == expected_status
    assert response.json()["error"]["error_code"] == expected_code
    assert response.json()["data"] is None
    assert response.headers.get("retry-after") == retry_after


@pytest.mark.parametrize(
    ("error", "public_message", "sensitive_detail"),
    [
        (
            AuthorizationError("Invalid service token: Signature verification failed"),
            "Authentication failed",
            "Signature verification failed",
        ),
        (
            PermissionDeniedError("denied by secret-policy-rule-42"),
            "Access denied",
            "secret-policy-rule-42",
        ),
        (
            MutationReplayIntegrityError("ledger row 17 contains corrupt internal data"),
            "Internal server error",
            "ledger row 17",
        ),
    ],
)
def test_sensitive_error_details_are_not_exposed(
    error: Exception,
    public_message: str,
    sensitive_detail: str,
    caller_context_a: CallerContext,
) -> None:
    client = _client_raising(error, caller_context=caller_context_a)
    response = client.get("/v1/knowledge-graph/entities/whatever")

    assert response.json()["error"]["message"] == public_message
    assert sensitive_detail not in response.text


def test_missing_authorization_header_is_401(client_no_auth_override: TestClient) -> None:
    response = client_no_auth_override.get("/v1/knowledge-graph/entities/person-1")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["error_code"] == "AUTHORIZATION_ERROR"
    assert body["data"] is None


def test_malformed_authorization_header_is_401(client_no_auth_override: TestClient) -> None:
    response = client_no_auth_override.get(
        "/v1/knowledge-graph/entities/person-1",
        headers={"Authorization": "NotBearer sometoken"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["error_code"] == "AUTHORIZATION_ERROR"


def test_openapi_registers_all_seven_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    expected = {
        "/v1/knowledge-graph/entities/{entity_id}",
        "/v1/knowledge-graph/entities",
        "/v1/knowledge-graph/edges/{edge_id}",
        "/v1/knowledge-graph/edges",
        "/v1/knowledge-graph/entities/{entity_id}/neighbors",
        "/v1/knowledge-graph/paths/shortest",
        "/v1/knowledge-graph/entities/{entity_id}/history/{attribute_name}",
    }
    assert expected.issubset(paths.keys())
    for path in expected:
        assert "get" in paths[path]
