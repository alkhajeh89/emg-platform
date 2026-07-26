from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_neighbors_incoming_direction(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/project-1/neighbors",
        params={"direction": "incoming"},
    )
    assert response.status_code == 200
    body = response.json()
    entity_ids = {item["entity"]["node_id"] for item in body["items"]}
    assert entity_ids == {"person-1", "person-2"}


def test_list_neighbors_outgoing_direction_is_empty(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/project-1/neighbors",
        params={"direction": "outgoing"},
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_neighbors_both_directions_from_person(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/person-1/neighbors",
        params={"direction": "both"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["entity"]["node_id"] for item in body["items"]] == ["project-1"]
    assert body["items"][0]["via_edge_id"] == "rel-1"


def test_list_neighbors_not_found_entity_is_404(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities/ghost/neighbors")
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"


def test_shortest_path_found(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "person-1", "to_node_id": "project-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["found"] is True
    assert body["item"]["node_ids"] == ["person-1", "project-1"]
    assert body["item"]["edge_ids"] == ["rel-1"]
    assert body["item"]["length"] == 1


def test_shortest_path_not_found(client: TestClient) -> None:
    # person-3 has no edges at all (see conftest.base_graph), so no path can
    # exist to it from any other node.
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "person-1", "to_node_id": "person-3"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["found"] is False
    assert body["item"]["node_ids"] == []
    assert body["item"]["edge_ids"] == []


def test_shortest_path_maximum_depth_validation(client: TestClient) -> None:
    # Below the floor (0) is a transport-shape 422 from the Query(ge=1) bound.
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "person-1", "to_node_id": "project-1", "maximum_depth": 0},
    )
    assert response.status_code == 422

    # Above MAX_TRAVERSAL_DEPTH (64) is also a 422, via the same Query(le=...)
    # transport-shape bound reusing the application's own constant.
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "person-1", "to_node_id": "project-1", "maximum_depth": 65},
    )
    assert response.status_code == 422
