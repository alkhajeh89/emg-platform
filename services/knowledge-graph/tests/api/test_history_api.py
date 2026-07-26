from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from .conftest import T0, T1, T2


def test_entity_history_returns_value_valid_at_moment(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/person-1/history/owner",
        params={"valid_at": T0.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["value"] == "alice"
    assert body["revision_context"]["is_current_head"] is True


def test_entity_history_returns_later_value_after_transition(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/person-1/history/owner",
        params={"valid_at": T2.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["value"] == "bob"


def test_entity_history_before_any_fact_is_null_item(client: TestClient) -> None:
    before_creation = datetime(2020, 1, 1, tzinfo=timezone.utc)
    response = client.get(
        "/v1/knowledge-graph/entities/person-1/history/owner",
        params={"valid_at": before_creation.isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["item"] is None


def test_entity_history_historical_revision_parameter(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/person-1/history/owner",
        params={"valid_at": T0.isoformat(), "revision_number": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["revision_context"]["revision_number"] == 1


def test_entity_history_malformed_datetime_is_422(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/person-1/history/owner",
        params={"valid_at": "not-a-timestamp"},
    )
    assert response.status_code == 422


def test_entity_history_missing_valid_at_is_422(client: TestClient) -> None:
    response = client.get("/v1/knowledge-graph/entities/person-1/history/owner")
    assert response.status_code == 422


def test_entity_history_entity_not_found_is_404(client: TestClient) -> None:
    response = client.get(
        "/v1/knowledge-graph/entities/ghost/history/owner",
        params={"valid_at": T1.isoformat()},
    )
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"
