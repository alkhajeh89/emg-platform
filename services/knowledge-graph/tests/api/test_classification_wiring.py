"""HTTP-level integration tests for Group D9 (ADR-026 Revision 2): wiring the
Group D8 `classification` module into the seven Knowledge Graph Query API
routes.

Uses a dedicated small graph and a dedicated `PolicyConfig` (rather than
`conftest.py`'s shared `base_graph`/`policy.example.yaml`) so classification
outcomes are unambiguous and independent of Batch 1's own fixtures. The
policy mirrors the real, production-shaped combining pattern ADR-026
Revision 2 Amendment 1 is built on: a broad, role-only `allow` rule per
resource_type/action (what makes route-level `require_permission` pass —
its request carries no `resource_attributes`) plus a narrower `deny` rule
conditioned on `required_resource_attributes={"classification": [...]}`
(deny-overrides, evaluated only on the second, per-object PEP call
`classification.py` makes). This is deliberately *not* a synthetic
allow-list-only policy: it is the shape a real deployment would use to add
classification enforcement on top of an existing operation-level-only
policy without touching that policy's own rules — exactly what the Batch 1
report's finding (old tests are unaffected because the real
`policy.example.yaml` has no classification-conditioned rule at all) implies
is the compatible path.

Graph:
- alice (INTERNAL), carol (INTERNAL), diana (INTERNAL): visible to the
  "clearance-internal" caller.
- bob (SECRET), eve (SECRET): denied.
- e1: alice->bob, edge classification INTERNAL (edge cleared, target entity
  denied).
- e2: alice->carol, edge classification INTERNAL (both cleared).
- e4: alice->diana, edge classification SECRET (edge denied, target entity
  cleared).

This isolates entity-only denial (bob via e1), edge-only denial (diana via
e4), and the fully-visible case (carol via e2) for the neighbor and path
tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from emg_common_types import Classification
from emg_knowledge_graph import KnowledgeGraphApplication
from emg_knowledge_graph_api.authn import (
    CallerContext,
    ServicePrincipal,
    require_authenticated_caller,
    require_tenant_context,
)
from emg_knowledge_graph_api.dependencies import (
    knowledge_graph_application_dependency,
    policy_enforcement_point_dependency,
)
from emg_knowledge_graph_api.main import create_app
from emg_knowledge_graph_api.routers.knowledge_graph import (
    RESOURCE_EDGE,
    RESOURCE_ENTITY,
    RESOURCE_HISTORY,
    RESOURCE_NEIGHBORS,
    RESOURCE_PATH,
)
from emg_memory_graph import (
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    MemoryEdge,
    MemoryGraph,
    MemoryNode,
    Metadata,
    TemporalFact,
    TemporalHistory,
    TemporalValidity,
)
from emg_platform_core import InMemoryGraphStore, PrincipalRef, TenantId
from emg_policy_engine import LocalPolicyEnforcementPoint
from emg_policy_engine.rules import PolicyConfig, PolicyRule
from fastapi.testclient import TestClient

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
TENANT = TenantId.of("classification-wiring-tenant")
PRINCIPAL = PrincipalRef.service("classification-wiring-tests")
_CLEARED_ROLE = "clearance-internal"
_DENIED_CLASSIFICATIONS = ["SECRET", "CONFIDENTIAL"]


def _evidence(locator: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef.create(
            source=EvidenceSource.MANUAL_ENTRY,
            locator=locator,
            source_principal="tester",
            captured_at=T0,
        ),
    )


def _node(
    node_id: str, classification: str, *, histories: tuple[TemporalHistory, ...] = ()
) -> MemoryNode:
    return MemoryNode(
        node_id=node_id,
        node_type="person",
        label=node_id,
        created_at=T0,
        updated_at=T0,
        source="tester",
        confidence=0.9,
        classification=Classification(classification),
        evidence=_evidence(node_id),
        metadata=Metadata(),
        histories=histories,
    )


def _edge(edge_id: str, source_id: str, target_id: str, classification: str) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        edge_type="knows",
        source_id=source_id,
        target_id=target_id,
        direction=EdgeDirection.DIRECTED,
        evidence=_evidence(edge_id),
        confidence=0.9,
        validity=TemporalValidity(valid_from=T0, valid_until=None),
        created_at=T0,
        updated_at=T0,
        classification=Classification(classification),
    )


def _role_history(value: str) -> TemporalHistory:
    return TemporalHistory(
        attribute="role",
        facts=(
            TemporalFact(
                value=value,
                validity=TemporalValidity(valid_from=T0, valid_until=None),
                evidence=_evidence(f"role-{value}"),
                recorded_at=T0,
            ),
        ),
    )


def _graph() -> MemoryGraph:
    alice = _node("alice", "INTERNAL", histories=(_role_history("engineer"),))
    bob = _node("bob", "SECRET")
    carol = _node("carol", "INTERNAL")
    diana = _node("diana", "INTERNAL")
    eve = _node("eve", "SECRET", histories=(_role_history("secret-agent"),))
    e1 = _edge("e1", "alice", "bob", "INTERNAL")
    e2 = _edge("e2", "alice", "carol", "INTERNAL")
    e4 = _edge("e4", "alice", "diana", "SECRET")
    return MemoryGraph(nodes=(alice, bob, carol, diana, eve), edges=(e1, e2, e4))


def _policy_config() -> PolicyConfig:
    rules: list[PolicyRule] = []
    for resource_type in (
        RESOURCE_ENTITY,
        RESOURCE_EDGE,
        RESOURCE_NEIGHBORS,
        RESOURCE_PATH,
        RESOURCE_HISTORY,
    ):
        rules.append(
            PolicyRule(
                rule_id=f"{resource_type}-grant",
                resource_type=resource_type,
                action="read",
                effect="allow",
                required_roles=[_CLEARED_ROLE],
            )
        )
        rules.append(
            PolicyRule(
                rule_id=f"{resource_type}-deny-above-clearance",
                resource_type=resource_type,
                action="read",
                effect="deny",
                required_roles=[_CLEARED_ROLE],
                required_resource_attributes={"classification": _DENIED_CLASSIFICATIONS},
            )
        )
    return PolicyConfig(rules=rules)


def _client_for_graph(graph: MemoryGraph, tenant: TenantId) -> TestClient:
    store = InMemoryGraphStore()
    store.write(tenant, graph, principal=PRINCIPAL)
    application = KnowledgeGraphApplication(graph_store=store, revision_reader=store)
    caller = CallerContext(
        principal=ServicePrincipal(client_id="svc-cleared", roles=(_CLEARED_ROLE,)),
        tenant=tenant,
    )
    pep = LocalPolicyEnforcementPoint(_policy_config())

    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: application
    app.dependency_overrides[require_tenant_context] = lambda: caller
    app.dependency_overrides[require_authenticated_caller] = lambda: caller
    app.dependency_overrides[policy_enforcement_point_dependency] = lambda: pep
    return TestClient(app)


def _client() -> TestClient:
    return _client_for_graph(_graph(), TENANT)


# --- entity: authorized visible / unauthorized hidden -----------------------


def test_authorized_entity_is_visible() -> None:
    client = _client()
    response = client.get("/v1/knowledge-graph/entities/alice")
    assert response.status_code == 200
    assert response.json()["item"]["summary"]["node_id"] == "alice"


def test_unauthorized_entity_is_hidden_as_not_found() -> None:
    client = _client()
    response = client.get("/v1/knowledge-graph/entities/bob")
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"


# --- edge: authorized visible / unauthorized hidden --------------------------


def test_authorized_edge_is_visible() -> None:
    client = _client()
    response = client.get("/v1/knowledge-graph/edges/e1")
    assert response.status_code == 200
    assert response.json()["item"]["edge_id"] == "e1"


def test_unauthorized_edge_is_hidden_as_not_found() -> None:
    client = _client()
    response = client.get("/v1/knowledge-graph/edges/e4")
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_EDGE_NOT_FOUND"


# --- neighbors: entity-denial and edge-denial both prune ---------------------


def test_neighbor_endpoint_filters_entity_and_edge_denials() -> None:
    client = _client()
    response = client.get(
        "/v1/knowledge-graph/entities/alice/neighbors", params={"direction": "outgoing"}
    )
    assert response.status_code == 200
    body = response.json()
    # bob hidden (entity denied via e1), diana hidden (edge e4 denied),
    # carol visible (both entity and edge cleared via e2).
    assert [item["entity"]["node_id"] for item in body["items"]] == ["carol"]


# --- path: not-found if any node or any edge on it is denied -----------------


def test_path_not_found_when_target_node_denied() -> None:
    client = _client()
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "alice", "to_node_id": "bob"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["found"] is False
    assert body["item"]["node_ids"] == []
    assert body["item"]["edge_ids"] == []


def test_path_not_found_when_edge_denied() -> None:
    client = _client()
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "alice", "to_node_id": "diana"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["found"] is False


def test_path_found_when_fully_cleared() -> None:
    client = _client()
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "alice", "to_node_id": "carol"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["found"] is True
    assert body["item"]["node_ids"] == ["alice", "carol"]


# --- history: filters classified facts ---------------------------------------


def test_history_endpoint_returns_fact_for_cleared_node() -> None:
    client = _client()
    response = client.get(
        "/v1/knowledge-graph/entities/alice/history/role",
        params={"valid_at": "2026-06-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["item"]["value"] == "engineer"


def test_history_endpoint_hides_fact_for_denied_node() -> None:
    client = _client()
    response = client.get(
        "/v1/knowledge-graph/entities/eve/history/role",
        params={"valid_at": "2026-06-01T00:00:00Z"},
    )
    # eve exists (no 404) but her classification is denied -- the fact is
    # hidden using the same shape as "no value at that time" (item: null),
    # never a distinct error (ADR-026 Revision 2 §8.5).
    assert response.status_code == 200
    assert response.json()["item"] is None


# --- pagination stability + no information leakage ---------------------------


def test_list_entities_returned_count_matches_filtered_items_not_leaking_hidden_count() -> None:
    client = _client()
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    visible_ids = [item["node_id"] for item in body["items"]]
    # 5 nodes exist (alice, bob, carol, diana, eve); bob and eve are denied.
    assert visible_ids == ["alice", "carol", "diana"]
    # returned_count must match what was actually returned, not the
    # pre-filter page size -- otherwise the count itself would leak that
    # denied items exist.
    assert body["page_info"]["returned_count"] == len(body["items"]) == 3
    assert body["page_info"]["has_more"] is False


def test_list_entities_pagination_remains_stable_after_filtering() -> None:
    client = _client()
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # generous upper bound; loop breaks on has_more=False
        params = {"limit": 2}
        if cursor is not None:
            params["before_node_id"] = cursor
        response = client.get("/v1/knowledge-graph/entities", params=params)
        assert response.status_code == 200
        body = response.json()
        # Every page's own returned_count matches its own items length, even
        # though some underlying pages contain a denied node.
        assert body["page_info"]["returned_count"] == len(body["items"])
        seen.extend(item["node_id"] for item in body["items"])
        if not body["page_info"]["has_more"]:
            break
        cursor = body["page_info"]["next_cursor"]
    else:
        raise AssertionError("pagination did not terminate")

    # Every visible node was reached exactly once across however many pages
    # cursor-based continuation took, with no duplicates or gaps, and no
    # denied node ever appeared.
    assert seen == ["alice", "carol", "diana"]


def test_list_edges_filters_denied_edge_with_stable_count() -> None:
    client = _client()
    response = client.get("/v1/knowledge-graph/edges", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    edge_ids = [item["edge_id"] for item in body["items"]]
    assert edge_ids == ["e1", "e2"]
    assert body["page_info"]["returned_count"] == 2


# --- Batch 2 remediation regression tests -----------------------------------
#
# FIX 1 (pagination metadata leak): `has_more`/`next_cursor` previously came
# from the raw, unfiltered application-layer page, so a client could infer a
# hidden object's existence (most directly: `next_cursor` could literally be
# a denied object's own id). These tests use a dedicated 6-node graph
# ("n01".."n06", ascending, matching cursor ordering) deliberately arranged
# so that a `limit=2` page's raw window is *entirely* denied objects while
# more authorized objects exist further along -- the exact shape that would
# have produced a leaking `has_more`/`next_cursor` (or a falsely-empty page)
# before the HTTP-layer look-ahead fix.
_PAGINATION_TENANT = TenantId.of("classification-pagination-tenant")


def _pagination_graph() -> MemoryGraph:
    # n01 INTERNAL (visible), n02+n03 SECRET (denied, consecutive - fills an
    # entire raw limit=2 page with nothing authorized), n04 INTERNAL
    # (visible), n05 SECRET (denied), n06 INTERNAL (visible).
    nodes = [
        _node("n01", "INTERNAL"),
        _node("n02", "SECRET"),
        _node("n03", "SECRET"),
        _node("n04", "INTERNAL"),
        _node("n05", "SECRET"),
        _node("n06", "INTERNAL"),
    ]
    return MemoryGraph(nodes=tuple(nodes), edges=())


def _all_denied_graph() -> MemoryGraph:
    return MemoryGraph(nodes=(_node("s01", "SECRET"), _node("s02", "SECRET")), edges=())


def test_empty_filtered_page_reveals_no_hidden_objects() -> None:
    """A tenant whose entire dataset is denied must look identical to a
    tenant with no data at all: an empty list, has_more=False, no cursor --
    nothing suggesting any object exists."""
    client = _client_for_graph(_all_denied_graph(), TenantId.of("all-denied-tenant"))
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["page_info"]["returned_count"] == 0
    assert body["page_info"]["has_more"] is False
    assert body["page_info"]["next_cursor"] is None


def test_has_more_cannot_reveal_hidden_objects_within_a_page_window() -> None:
    """A raw page window that is entirely denied objects (n02, n03) must not
    cause a falsely-empty page or a `has_more`/count mismatch -- look-ahead
    must keep fetching until authorized data proves or disproves more
    exists. Also proves `has_more` correctly becomes False once the true
    end of *authorized* data is reached, not merely the end of one raw
    page."""
    client = _client_for_graph(_pagination_graph(), _PAGINATION_TENANT)

    first = client.get("/v1/knowledge-graph/entities", params={"limit": 2})
    assert first.status_code == 200
    first_body = first.json()
    assert [item["node_id"] for item in first_body["items"]] == ["n01", "n04"]
    assert first_body["page_info"]["returned_count"] == 2
    assert first_body["page_info"]["has_more"] is True

    second = client.get(
        "/v1/knowledge-graph/entities",
        params={"limit": 2, "before_node_id": first_body["page_info"]["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert [item["node_id"] for item in second_body["items"]] == ["n06"]
    assert second_body["page_info"]["returned_count"] == 1
    # n06 is the last authorized item and the last node in the graph -- no
    # more authorized (or raw) data remains.
    assert second_body["page_info"]["has_more"] is False
    assert second_body["page_info"]["next_cursor"] is None


def test_next_cursor_is_never_a_denied_objects_id() -> None:
    """`next_cursor` must always identify an item the caller actually saw --
    never one of the denied ids (n02, n03, n05) that fell inside a raw page
    window."""
    client = _client_for_graph(_pagination_graph(), _PAGINATION_TENANT)
    denied_ids = {"n02", "n03", "n05"}

    cursor: str | None = None
    for _ in range(10):
        params: dict[str, object] = {"limit": 2}
        if cursor is not None:
            params["before_node_id"] = cursor
        response = client.get("/v1/knowledge-graph/entities", params=params)
        assert response.status_code == 200
        body = response.json()
        next_cursor = body["page_info"]["next_cursor"]
        if next_cursor is not None:
            assert next_cursor not in denied_ids
            # The cursor must also be the id of an item actually present in
            # this page's own `items` (never a denied lookahead artifact).
            assert next_cursor == body["items"][-1]["node_id"]
        if not body["page_info"]["has_more"]:
            break
        cursor = next_cursor
    else:
        raise AssertionError("pagination did not terminate")


def test_pagination_metadata_derived_only_from_authorized_items() -> None:
    """Collecting every page end-to-end must yield exactly the authorized
    set (n01, n04, n06), never a denied id, and `returned_count` must equal
    `len(items)` on every single page -- proving `PageInfo` reflects only
    what `classification.py`/`PolicyEnforcementPoint` actually authorized."""
    client = _client_for_graph(_pagination_graph(), _PAGINATION_TENANT)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, object] = {"limit": 2}
        if cursor is not None:
            params["before_node_id"] = cursor
        response = client.get("/v1/knowledge-graph/entities", params=params)
        body = response.json()
        assert body["page_info"]["returned_count"] == len(body["items"])
        seen.extend(item["node_id"] for item in body["items"])
        if not body["page_info"]["has_more"]:
            break
        cursor = body["page_info"]["next_cursor"]
    else:
        raise AssertionError("pagination did not terminate")

    assert seen == ["n01", "n04", "n06"]


# FIX 2 (denied history classification leak): `gate_history_fact` must never
# hand back the real classification once access is denied, and the HTTP
# response for a denial must be indistinguishable from the pre-existing
# "no value at this moment" response.


def test_denied_history_never_serializes_classification() -> None:
    client = _client()
    response = client.get(
        "/v1/knowledge-graph/entities/eve/history/role",
        params={"valid_at": "2026-06-01T00:00:00Z"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "classification" not in body
    assert "classification" not in str(body.keys())
    assert set(body.keys()) == {"item", "revision_context"}


def test_denied_history_indistinguishable_from_existing_no_value_response() -> None:
    client = _client()
    # alice is cleared, but her "role" history only starts at T0
    # (2026-01-01); querying before that moment is the pre-existing,
    # unrelated "no value yet" case (not a classification denial).
    no_value_response = client.get(
        "/v1/knowledge-graph/entities/alice/history/role",
        params={"valid_at": "2025-01-01T00:00:00Z"},
    )
    # eve is denied outright (SECRET); her fact is hidden regardless of
    # `valid_at`.
    denied_response = client.get(
        "/v1/knowledge-graph/entities/eve/history/role",
        params={"valid_at": "2026-06-01T00:00:00Z"},
    )
    assert no_value_response.status_code == denied_response.status_code == 200
    no_value_body = no_value_response.json()
    denied_body = denied_response.json()
    assert no_value_body["item"] is None
    assert denied_body["item"] is None
    # Identical shape: same keys, both null `item`, both a normal
    # `revision_context` -- no distinguishing field anywhere.
    assert set(no_value_body.keys()) == set(denied_body.keys()) == {"item", "revision_context"}
