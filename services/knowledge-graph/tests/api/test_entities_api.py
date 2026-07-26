from __future__ import annotations

from emg_knowledge_graph import GetEntityQuery, GraphQueryScope, KnowledgeGraphApplication
from fastapi.testclient import TestClient

from .conftest import TENANT_B


def test_get_entity_success(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities/person-1")
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["summary"]["node_id"] == "person-1"
    assert body["item"]["summary"]["node_type"] == "person"
    assert body["item"]["summary"]["classification"] == "INTERNAL"
    assert body["item"]["metadata"] == {"team": "alpha"}
    assert body["item"]["histories"][0]["attribute"] == "owner"
    assert body["revision_context"]["is_current_head"] is True
    assert body["revision_context"]["revision_number"] == 1


def test_get_entity_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities/ghost")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["error_code"] == "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"
    assert body["data"] is None
    assert "correlation_id" in body


def test_get_entity_historical_revision_parameter(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities/person-1", params={"revision_number": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["revision_context"]["revision_number"] == 1
    assert body["revision_context"]["is_current_head"] is False


def test_list_entities_filters_by_type(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities", params={"node_type": "project"})
    assert response.status_code == 200
    body = response.json()
    assert [item["node_id"] for item in body["items"]] == ["project-1"]


def test_list_entities_filters_by_classification(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities", params={"classification": "CONFIDENTIAL"})
    assert response.status_code == 200
    body = response.json()
    assert [item["node_id"] for item in body["items"]] == ["person-2"]


def test_list_entities_metadata_predicate(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities", params={"metadata": "team=alpha"})
    assert response.status_code == 200
    body = response.json()
    assert [item["node_id"] for item in body["items"]] == ["person-1"]


def test_list_entities_malformed_metadata_predicate_is_422(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities", params={"metadata": "no-equals-sign"})
    assert response.status_code == 422


def test_list_entities_pagination(client: TestClient) -> None:
    first = client.get("/v1/knowledge-graph/entities", params={"limit": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["page_info"]["limit"] == 2
    assert first_body["page_info"]["returned_count"] == 2
    assert first_body["page_info"]["has_more"] is True
    cursor = first_body["page_info"]["next_cursor"]

    second = client.get(
        "/v1/knowledge-graph/entities", params={"limit": 2, "before_node_id": cursor}
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["page_info"]["has_more"] is False
    first_ids = {item["node_id"] for item in first_body["items"]}
    second_ids = {item["node_id"] for item in second_body["items"]}
    assert not first_ids & second_ids


def test_list_entities_invalid_limit_is_422(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 0})
    assert response.status_code == 422

    response = client.get("/v1/knowledge-graph/entities", params={"limit": 999})
    assert response.status_code == 422


def test_no_tenant_query_parameter_accepted(client: TestClient) -> None:
    """The route declares no `tenant_id`/`tenant` query parameter at all —
    tenant scoping comes only from the authenticated CallerContext. Passing
    one as an extra query param is simply ignored by FastAPI (unknown query
    params are not rejected by default), proving it can never override the
    resolved tenant."""
    response = client.get(
        "/v1/knowledge-graph/entities/person-only-in-b", params={"tenant_id": "tenant-b"}
    )
    assert response.status_code == 404


def test_tenant_context_propagation_isolates_data(
    client: TestClient, application: KnowledgeGraphApplication
) -> None:
    # caller_context_a resolves to TENANT_A; TENANT_B has its own separate
    # data (person-only-in-b) that must never be visible to a TENANT_A caller,
    # regardless of query parameters.
    response = client.get("/v1/knowledge-graph/entities/person-only-in-b")
    assert response.status_code == 404

    # Sanity: the data does exist, just for a different tenant.
    direct = application.get_entity(
        GetEntityQuery(scope=GraphQueryScope(tenant=TENANT_B), node_id="person-only-in-b")
    )
    assert direct.item.summary.node_id == "person-only-in-b"


def test_response_json_shape_is_stable(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities/person-1")
    body = response.json()
    assert set(body.keys()) == {"item", "revision_context"}
    assert set(body["item"].keys()) == {
        "summary",
        "source",
        "aliases",
        "evidence",
        "histories",
        "metadata",
    }
    assert set(body["revision_context"].keys()) == {
        "revision_number",
        "committed_at",
        "is_current_head",
    }
    # ISO-8601, timezone-aware.
    assert body["revision_context"]["committed_at"].count(":") >= 2
    assert "+" in body["revision_context"]["committed_at"] or body["revision_context"][
        "committed_at"
    ].endswith("Z")
