"""Group D11 (ADR-026 Revision 2): the full classification-enforcement test
suite, exercised end-to-end through the real HTTP routes against the
*actual, shipped* `services/knowledge-graph/config/policy.example.yaml`
(Group D6) — not a synthetic test-only policy.

This complements, rather than duplicates, the existing classification test
files:

- `test_classification.py` (Group D8): unit tests of the pure
  `classification.py` functions against a minimal synthetic policy.
- `test_classification_wiring.py` (Group D9 + Batch 2 remediation): HTTP
  wiring/leakage-fix tests against a synthetic policy shaped like
  production but with simplified role-only rules.

Neither of those exercises the *real*, enumerated D6 policy data (which
conditions its deny rules on the principal's own `classification_clearance`
attribute via `required_attributes`, not a role) end-to-end through the
seven routes. That is this file's job, and is exactly Group D11's
requirement: "Per-endpoint pruning tests (list/neighbors), shortest-path-
blocked tests, history-blocked tests, get_entity/get_edge 404-on-
classification tests, dominance-boundary tests, default-UNCLASSIFIED-for-
unresolved-clearance tests, and a regression test confirming ADR-025's 403
still fires before any classification logic runs for an unauthorized
caller."

Graph (all edges directed, sourced from `hub`):
- hub: INTERNAL, has a `role` history fact.
- u1: UNCLASSIFIED, reached via `e_u` (classification UNCLASSIFIED).
- i1: INTERNAL, reached via `e_i` (classification INTERNAL).
- c1: CONFIDENTIAL, reached via `e_c` (classification CONFIDENTIAL), has a
  `role` history fact.
- s1: SECRET, reached via `e_s` (classification SECRET).

Per `policy.example.yaml`'s own documented deny-rule set: a caller cleared
to UNCLASSIFIED sees only UNCLASSIFIED objects; INTERNAL clearance adds
INTERNAL; CONFIDENTIAL clearance adds CONFIDENTIAL; SECRET clearance sees
everything (no deny rule targets a SECRET-cleared caller at all, since
nothing exceeds SECRET).
"""

from __future__ import annotations

from datetime import datetime, timezone

from emg_common_types import Classification
from emg_knowledge_graph import KnowledgeGraphApplication
from emg_knowledge_graph_api.authn import CallerContext, ServicePrincipal, require_tenant_context
from emg_knowledge_graph_api.dependencies import (
    knowledge_graph_application_dependency,
    policy_enforcement_point_dependency,
)
from emg_knowledge_graph_api.main import create_app
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
from emg_policy_engine import LocalPolicyEnforcementPoint, load_policy_config
from fastapi.testclient import TestClient

from .conftest import POLICY_CONFIG_PATH

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
TENANT = TenantId.of("d11-scenario-tenant")
PRINCIPAL = PrincipalRef.service("d11-scenario-tests")

# The four roles the real policy's operation-level "*-read" allow rules
# grant (see policy.example.yaml's role-catalog comment).
_GRANTED_ROLE = "investigator"


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
    hub = _node("hub", "INTERNAL", histories=(_role_history("engineer"),))
    u1 = _node("u1", "UNCLASSIFIED")
    i1 = _node("i1", "INTERNAL")
    c1 = _node("c1", "CONFIDENTIAL", histories=(_role_history("classified-role"),))
    s1 = _node("s1", "SECRET")
    e_u = _edge("e_u", "hub", "u1", "UNCLASSIFIED")
    e_i = _edge("e_i", "hub", "i1", "INTERNAL")
    e_c = _edge("e_c", "hub", "c1", "CONFIDENTIAL")
    e_s = _edge("e_s", "hub", "s1", "SECRET")
    return MemoryGraph(nodes=(hub, u1, i1, c1, s1), edges=(e_u, e_i, e_c, e_s))


def _real_pep() -> LocalPolicyEnforcementPoint:
    return LocalPolicyEnforcementPoint(load_policy_config(POLICY_CONFIG_PATH))


def _caller(*, clearance: str | None, roles: tuple[str, ...] = (_GRANTED_ROLE,)) -> CallerContext:
    attributes = {"classification_clearance": clearance} if clearance is not None else {}
    return CallerContext(
        principal=ServicePrincipal(client_id="svc-d11", roles=roles, attributes=attributes),
        tenant=TENANT,
    )


def _client(caller: CallerContext) -> TestClient:
    store = InMemoryGraphStore()
    store.write(TENANT, _graph(), principal=PRINCIPAL)
    application = KnowledgeGraphApplication(graph_store=store, revision_reader=store)

    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: application
    app.dependency_overrides[require_tenant_context] = lambda: caller
    app.dependency_overrides[policy_enforcement_point_dependency] = _real_pep
    return TestClient(app)


# --- per-endpoint pruning (list/neighbors) ----------------------------------


def test_list_entities_prunes_by_dominance_with_internal_clearance() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 10})
    assert response.status_code == 200
    ids = {item["node_id"] for item in response.json()["items"]}
    assert ids == {"hub", "i1", "u1"}


def test_list_edges_prunes_by_dominance_with_internal_clearance() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get("/v1/knowledge-graph/edges", params={"limit": 10})
    assert response.status_code == 200
    ids = {item["edge_id"] for item in response.json()["items"]}
    assert ids == {"e_u", "e_i"}


def test_list_neighbors_prunes_by_dominance_with_internal_clearance() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get(
        "/v1/knowledge-graph/entities/hub/neighbors", params={"direction": "outgoing", "limit": 10}
    )
    assert response.status_code == 200
    ids = {item["entity"]["node_id"] for item in response.json()["items"]}
    assert ids == {"u1", "i1"}


# --- shortest-path-blocked ----------------------------------------------------


def test_shortest_path_blocked_by_dominance() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "hub", "to_node_id": "c1"},
    )
    assert response.status_code == 200
    assert response.json()["item"]["found"] is False


def test_shortest_path_allowed_at_matching_clearance() -> None:
    client = _client(_caller(clearance="CONFIDENTIAL"))
    response = client.get(
        "/v1/knowledge-graph/paths/shortest",
        params={"from_node_id": "hub", "to_node_id": "c1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["found"] is True
    assert body["item"]["node_ids"] == ["hub", "c1"]


# --- history-blocked -----------------------------------------------------------


def test_history_blocked_by_dominance() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get(
        "/v1/knowledge-graph/entities/c1/history/role",
        params={"valid_at": "2026-06-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["item"] is None


def test_history_allowed_at_matching_clearance() -> None:
    client = _client(_caller(clearance="CONFIDENTIAL"))
    response = client.get(
        "/v1/knowledge-graph/entities/c1/history/role",
        params={"valid_at": "2026-06-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json()["item"]["value"] == "classified-role"


# --- get_entity/get_edge 404-on-classification ---------------------------------


def test_get_entity_404_on_classification_denial() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get("/v1/knowledge-graph/entities/c1")
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"


def test_get_entity_200_at_matching_clearance() -> None:
    client = _client(_caller(clearance="CONFIDENTIAL"))
    response = client.get("/v1/knowledge-graph/entities/c1")
    assert response.status_code == 200
    assert response.json()["item"]["summary"]["node_id"] == "c1"


def test_get_edge_404_on_classification_denial() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get("/v1/knowledge-graph/edges/e_c")
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_EDGE_NOT_FOUND"


def test_get_edge_200_at_matching_clearance() -> None:
    client = _client(_caller(clearance="CONFIDENTIAL"))
    response = client.get("/v1/knowledge-graph/edges/e_c")
    assert response.status_code == 200
    assert response.json()["item"]["edge_id"] == "e_c"


# --- dominance-boundary (exact tier boundaries, all four clearances) -----------


def test_dominance_boundary_unclassified_clearance_sees_only_unclassified() -> None:
    client = _client(_caller(clearance="UNCLASSIFIED"))
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 10})
    ids = {item["node_id"] for item in response.json()["items"]}
    assert ids == {"u1"}


def test_dominance_boundary_internal_clearance_sees_unclassified_and_internal() -> None:
    client = _client(_caller(clearance="INTERNAL"))
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 10})
    ids = {item["node_id"] for item in response.json()["items"]}
    assert ids == {"u1", "i1", "hub"}


def test_dominance_boundary_confidential_clearance_adds_confidential() -> None:
    client = _client(_caller(clearance="CONFIDENTIAL"))
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 10})
    ids = {item["node_id"] for item in response.json()["items"]}
    assert ids == {"u1", "i1", "hub", "c1"}


def test_dominance_boundary_secret_clearance_sees_everything() -> None:
    """Per policy.example.yaml's own documented rationale: only three deny
    rules exist per resource_type (unclassified/internal/confidential
    clearance) -- a SECRET-cleared caller has nothing above it to be denied
    for, so it sees every classification level."""
    client = _client(_caller(clearance="SECRET"))
    response = client.get("/v1/knowledge-graph/entities", params={"limit": 10})
    ids = {item["node_id"] for item in response.json()["items"]}
    assert ids == {"u1", "i1", "hub", "c1", "s1"}


# --- default-UNCLASSIFIED-for-unresolved-clearance -----------------------------


def test_default_unclassified_clearance_is_denied_exactly_like_explicit_unclassified() -> None:
    """ADR-026 Revision 2 §8.4's fail-closed guarantee is implemented at
    claim-extraction time (Group D5,
    `emg_knowledge_graph_api.authn._extract_attributes`), which *always*
    populates `classification_clearance` with a real string -- literally
    `"UNCLASSIFIED"` for a missing or malformed claim, never an absent key
    (unit-tested in `test_authn.py`). `PolicyEngine` itself has no
    "attribute absent" special case (an absent key satisfies no rule at
    all, allow or deny) -- so the fail-closed guarantee depends entirely on
    that upstream normalization already having run before a caller's
    `ServicePrincipal`/`Principal` is ever constructed.

    This test proves the other half end-to-end: once a caller's clearance
    has been normalized to `"UNCLASSIFIED"` (whether because that was the
    real claim value or because D5 defaulted it), the real D6 policy denies
    it identically -- there is no special-cased "default" path through the
    policy itself, just the same enumerated deny rule any other
    UNCLASSIFIED-cleared caller matches."""
    client = _client(_caller(clearance="UNCLASSIFIED"))
    response = client.get("/v1/knowledge-graph/entities/hub")
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"


# --- regression: ADR-025's 403 still fires before any classification logic ----

_ROUTES: list[tuple[str, str]] = [
    ("GET", "/v1/knowledge-graph/entities/hub"),
    ("GET", "/v1/knowledge-graph/entities"),
    ("GET", "/v1/knowledge-graph/edges/e_u"),
    ("GET", "/v1/knowledge-graph/edges"),
    ("GET", "/v1/knowledge-graph/entities/hub/neighbors"),
    ("GET", "/v1/knowledge-graph/paths/shortest?from_node_id=hub&to_node_id=u1"),
    (
        "GET",
        "/v1/knowledge-graph/entities/hub/history/role?valid_at=2026-06-01T00:00:00Z",
    ),
]


def test_403_fires_before_classification_logic_for_ungranted_role() -> None:
    """A caller with SECRET clearance (would see *everything* if
    classification were the only gate) but no role the operation-level
    policy grants must still be denied with 403 on every route -- proving
    ADR-025's `require_permission` dependency (evaluated before the route
    body / classification.py ever runs) is never bypassed or shadowed by
    the classification-enforcement layer added on top of it."""
    client = _client(_caller(clearance="SECRET", roles=("some-other-role",)))
    for method, path in _ROUTES:
        response = client.request(method, path)
        assert response.status_code == 403, f"{method} {path} was not denied by ADR-025"
        assert response.json()["error"]["error_code"] == "PERMISSION_DENIED"


def test_403_fires_before_classification_logic_for_no_roles_at_all() -> None:
    client = _client(_caller(clearance="SECRET", roles=()))
    for method, path in _ROUTES:
        response = client.request(method, path)
        assert response.status_code == 403, f"{method} {path} was not denied by ADR-025"
        assert response.json()["error"]["error_code"] == "PERMISSION_DENIED"
