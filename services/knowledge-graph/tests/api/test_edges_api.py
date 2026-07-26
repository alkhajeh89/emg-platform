from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import T0, T2


def test_get_edge_success(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/edges/rel-1")
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["edge_id"] == "rel-1"
    assert body["item"]["edge_type"] == "owns"
    assert body["item"]["source_id"] == "person-1"
    assert body["item"]["target_id"] == "project-1"
    assert body["item"]["direction"] == "directed"
    assert body["item"]["validity"]["valid_until"] is None
    assert body["revision_context"]["is_current_head"] is True


def test_get_edge_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/edges/ghost-edge")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["error_code"] == "KNOWLEDGE_GRAPH_EDGE_NOT_FOUND"
    assert body["data"] is None


def test_list_edges_returns_all_by_default(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/edges")
    assert response.status_code == 200
    body = response.json()
    edge_ids = {item["edge_id"] for item in body["items"]}
    assert edge_ids == {"rel-1", "rel-2"}


def test_list_edges_filters_by_edge_type(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/edges", params={"edge_type": "owns"})
    assert response.status_code == 200
    body = response.json()
    assert {item["edge_id"] for item in body["items"]} == {"rel-1", "rel-2"}

    response = client.get("/v1/knowledge-graph/edges", params={"edge_type": "manages"})
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_edges_valid_at_excludes_closed_edge(client: TestClient) -> None:
    # rel-2 closes at T1 (valid_until=T1); at T2 only rel-1 remains valid.
    response = client.get("/v1/knowledge-graph/edges", params={"valid_at": T2.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert {item["edge_id"] for item in body["items"]} == {"rel-1"}


def test_list_edges_valid_at_includes_both_before_closure(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/edges", params={"valid_at": T0.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert {item["edge_id"] for item in body["items"]} == {"rel-1", "rel-2"}


def test_list_edges_malformed_valid_at_is_422(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/edges", params={"valid_at": "not-a-datetime"})
    assert response.status_code == 422


def test_list_edges_pagination(client: TestClient) -> None:
    first = client.get("/v1/knowledge-graph/edges", params={"limit": 1})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["page_info"]["returned_count"] == 1
    assert first_body["page_info"]["has_more"] is True
    cursor = first_body["page_info"]["next_cursor"]

    second = client.get("/v1/knowledge-graph/edges", params={"limit": 1, "before_edge_id": cursor})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["page_info"]["has_more"] is False
    first_ids = {item["edge_id"] for item in first_body["items"]}
    second_ids = {item["edge_id"] for item in second_body["items"]}
    assert not first_ids & second_ids
