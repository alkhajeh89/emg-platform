from datetime import timedelta

from emg_knowledge_graph_api.authn import settings_dependency
from emg_knowledge_graph_api.config import Settings, search_cursor_keys
from emg_knowledge_graph_api.dependencies import (
    knowledge_graph_application_dependency,
    policy_enforcement_point_dependency,
)
from emg_knowledge_graph_api.search_cursor import SearchCursorCodec
from emg_memory_graph import MemoryGraph
from emg_persistence import PersistenceError
from emg_platform_core import PrincipalRef
from emg_policy_engine import LocalPolicyEnforcementPoint
from emg_policy_engine.rules import PolicyConfig, PolicyRule

from .conftest import TENANT_A, make_node


def test_search_contract_has_no_totals_or_matched_alias(client):
    response = client.post("/v1/knowledge-graph/search", json={"q": "person", "limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert [item["entity"]["node_id"] for item in body["items"]] == [
        "person-1",
        "person-2",
    ]
    assert body["page_info"]["returned_count"] == 2
    assert body["page_info"]["has_more"] is True
    assert "total" not in str(body).lower()
    assert "alias" not in str(body).lower()


def test_cursor_pins_revision_across_graph_change(client, store):
    first = client.post("/v1/knowledge-graph/search", json={"q": "person", "limit": 1}).json()
    cursor = first["page_info"]["next_cursor"]
    original_revision = first["revision_context"]["revision_number"]
    store.write(
        TENANT_A,
        MemoryGraph(nodes=(*store.read(TENANT_A).nodes, make_node("person-0"))),
        principal=PrincipalRef.service("search-api-test"),
    )
    continuation = client.post(
        "/v1/knowledge-graph/search",
        json={"q": "person", "limit": 1, "cursor": cursor},
    )
    assert continuation.status_code == 200
    body = continuation.json()
    assert body["revision_context"]["revision_number"] == original_revision
    assert body["items"][0]["entity"]["node_id"] == "person-2"


def test_invalid_cursor_bindings_share_one_public_error(client):
    first = client.post("/v1/knowledge-graph/search", json={"q": "person", "limit": 1}).json()
    cursor = first["page_info"]["next_cursor"]
    wrong_query = client.post(
        "/v1/knowledge-graph/search",
        json={"q": "project", "limit": 1, "cursor": cursor},
    )
    increased_limit = client.post(
        "/v1/knowledge-graph/search",
        json={"q": "person", "limit": 2, "cursor": cursor},
    )
    assert wrong_query.status_code == increased_limit.status_code == 400
    assert wrong_query.json()["error"]["error_code"] == (
        "KNOWLEDGE_GRAPH_INVALID_SEARCH_CONTINUATION"
    )
    assert increased_limit.json()["error"]["error_code"] == (
        "KNOWLEDGE_GRAPH_INVALID_SEARCH_CONTINUATION"
    )


def test_malformed_search_uses_stable_400_envelope_without_query_logging(client, caplog):
    for payload in ({"q": "   "}, {"q": "person", "unknown": True}, {"limit": 1}):
        response = client.post("/v1/knowledge-graph/search", json=payload)
        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == ("KNOWLEDGE_GRAPH_INVALID_SEARCH_REQUEST")
    assert "person" not in caplog.text


def test_search_is_tenant_scoped(client):
    response = client.post("/v1/knowledge-graph/search", json={"q": "person-only-in-b"})
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_classification_is_pruned_before_page_metadata(client):
    policy = PolicyConfig(
        rules=[
            PolicyRule(
                rule_id="allow-entity-read",
                resource_type="knowledge-graph.entity",
                action="read",
                effect="allow",
                required_roles=["service-account"],
            ),
            PolicyRule(
                rule_id="deny-internal",
                resource_type="knowledge-graph.entity",
                action="read",
                effect="deny",
                required_roles=["service-account"],
                required_resource_attributes={"classification": ["INTERNAL"]},
            ),
        ]
    )
    client.app.dependency_overrides[policy_enforcement_point_dependency] = lambda: (
        LocalPolicyEnforcementPoint(policy)
    )
    response = client.post("/v1/knowledge-graph/search", json={"q": "person", "limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert [item["entity"]["node_id"] for item in body["items"]] == ["person-2"]
    assert body["page_info"] == {
        "limit": 1,
        "returned_count": 1,
        "next_cursor": None,
        "has_more": False,
    }


def test_missing_retained_representation_never_falls_forward_to_head(client):
    class UnavailableApplication:
        def search_entities(self, query):
            raise PersistenceError("representation unavailable")

    settings = Settings()
    codec = SearchCursorCodec(
        settings.search_cursor_active_key_id,
        search_cursor_keys(settings),
        timedelta(seconds=settings.search_cursor_default_ttl_seconds),
    )
    cursor = codec.encode(TENANT_A.value, "person", 1, 1, "person-1", 1)
    client.app.dependency_overrides[knowledge_graph_application_dependency] = UnavailableApplication
    response = client.post(
        "/v1/knowledge-graph/search",
        json={"q": "person", "limit": 1, "cursor": cursor},
    )
    assert response.status_code == 400
    assert response.json()["error"]["error_code"] == ("KNOWLEDGE_GRAPH_INVALID_SEARCH_CONTINUATION")


def test_candidate_work_ceiling_fails_whole_request_without_partial_metadata(client):
    policy = PolicyConfig(
        rules=[
            PolicyRule(
                rule_id="allow-entity-read",
                resource_type="knowledge-graph.entity",
                action="read",
                effect="allow",
                required_roles=["service-account"],
            ),
            PolicyRule(
                rule_id="deny-internal",
                resource_type="knowledge-graph.entity",
                action="read",
                effect="deny",
                required_roles=["service-account"],
                required_resource_attributes={"classification": ["INTERNAL"]},
            ),
        ]
    )
    client.app.dependency_overrides[policy_enforcement_point_dependency] = lambda: (
        LocalPolicyEnforcementPoint(policy)
    )
    client.app.dependency_overrides[settings_dependency] = lambda: Settings(
        search_candidate_batch_size=1,
        search_candidate_work_ceiling=1,
    )
    response = client.post("/v1/knowledge-graph/search", json={"q": "person", "limit": 1})
    assert response.status_code == 503
    assert response.json()["error"]["error_code"] == ("KNOWLEDGE_GRAPH_SEARCH_WORK_LIMIT_REACHED")
    assert "person-1" not in response.text
    assert "returned_count" not in response.text
