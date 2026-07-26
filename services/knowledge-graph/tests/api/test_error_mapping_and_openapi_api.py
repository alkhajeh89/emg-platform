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
from emg_knowledge_graph import (
    EdgeNotFoundError,
    EntityNotFoundError,
    InvalidQueryError,
    InvalidTemporalFilterError,
    PathDepthExceededError,
    QueryLimitExceededError,
    RevisionNotFoundError,
    UnsupportedHistoryCapabilityError,
)
from emg_knowledge_graph_api.authn import CallerContext, require_tenant_context
from emg_knowledge_graph_api.dependencies import knowledge_graph_application_dependency
from emg_knowledge_graph_api.main import create_app
from fastapi.testclient import TestClient


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
