"""Test fixtures for the Knowledge Graph Query API (Sprint 7.4; ADR-025
Group C9 authorization wiring).

Overrides `KnowledgeGraphApplicationDep` with a real `KnowledgeGraphApplication`
backed by `InMemoryGraphStore` (seeded directly, bypassing the ontology/
builder layer for full control over metadata/histories/temporal validity —
the same approach `test_query_engine_service.py` uses), overrides
`TenantContextDep` with a fixed `CallerContext`, and overrides
`policy_enforcement_point_dependency` with a `LocalPolicyEnforcementPoint`
loaded from the real `config/policy.example.yaml` (resolved relative to
this file, not the process cwd, so tests are not sensitive to how pytest is
invoked — mirroring `services/identity/tests/test_authz_router.py`'s
`_POLICY_CONFIG_PATH` convention exactly), so the bulk of API tests exercise
the full HTTP -> authn -> authorization -> command -> application-service ->
DTO -> response path without needing a live Keycloak/JWKS server.
`caller_context_a`'s `service-account` role is granted `read` on every
`knowledge-graph.*` resource type in the real policy file, so every
pre-existing route test continues to receive its previously-expected
response for this authorized caller. One test module
(`test_error_mapping_and_openapi_api.py`) additionally exercises the *real*
`require_tenant_context` dependency (no override) to prove the auth wiring
itself, using only "no/malformed Authorization header" cases — this needs
no live JWKS server either, since those requests are rejected before any
token is decoded. `test_authorization.py` exercises the authorization gate
itself (allowed/denied/missing-policy/missing-role/missing-scope/default-deny)
with its own, dedicated policy-enforcement-point overrides.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
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

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=30)
T2 = T1 + timedelta(days=30)
TENANT_A = TenantId.of("tenant-a")
TENANT_B = TenantId.of("tenant-b")
PRINCIPAL = PrincipalRef.service("kg-api-tests")

# Resolved relative to this file, not the process cwd (ADR-025 Group C9;
# mirrors services/identity/tests/test_authz_router.py's
# `_POLICY_CONFIG_PATH` convention exactly).
POLICY_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "policy.example.yaml"


def evidence(locator: str, *, captured_at: datetime = T0) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef.create(
            source=EvidenceSource.MANUAL_ENTRY,
            locator=locator,
            source_principal="tester",
            captured_at=captured_at,
        ),
    )


def make_node(
    node_id: str,
    node_type: str = "person",
    *,
    label: str | None = None,
    confidence: float = 0.9,
    classification: Classification = Classification.INTERNAL,
    source: str = "tester",
    created_at: datetime = T0,
    updated_at: datetime = T0,
    metadata: Metadata | None = None,
    histories: tuple[TemporalHistory, ...] = (),
) -> MemoryNode:
    return MemoryNode(
        node_id=node_id,
        node_type=node_type,
        label=label or node_id,
        created_at=created_at,
        updated_at=updated_at,
        source=source,
        confidence=confidence,
        classification=classification,
        evidence=evidence(node_id, captured_at=created_at),
        metadata=metadata or Metadata(),
        histories=histories,
    )


def make_edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    *,
    edge_type: str = "owns",
    direction: EdgeDirection = EdgeDirection.DIRECTED,
    confidence: float = 0.9,
    valid_from: datetime = T0,
    valid_until: datetime | None = None,
    created_at: datetime = T0,
    updated_at: datetime = T0,
) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        direction=direction,
        evidence=evidence(edge_id, captured_at=created_at),
        confidence=confidence,
        validity=TemporalValidity(valid_from=valid_from, valid_until=valid_until),
        created_at=created_at,
        updated_at=updated_at,
    )


def owner_history() -> TemporalHistory:
    return TemporalHistory(
        attribute="owner",
        facts=(
            TemporalFact(
                value="alice",
                validity=TemporalValidity(valid_from=T0, valid_until=T1),
                evidence=evidence("owner-alice", captured_at=T0),
                recorded_at=T0,
            ),
            TemporalFact(
                value="bob",
                validity=TemporalValidity(valid_from=T1, valid_until=None),
                evidence=evidence("owner-bob", captured_at=T1),
                recorded_at=T1,
            ),
        ),
    )


def base_graph() -> MemoryGraph:
    """person-1 --owns--> project-1 (open-ended); person-2 --owns--> project-1
    (closed at T1); person-3 unconnected."""
    person1 = make_node(
        "person-1",
        "person",
        confidence=0.9,
        classification=Classification.INTERNAL,
        metadata=Metadata.from_mapping({"team": "alpha"}),
        histories=(owner_history(),),
    )
    person2 = make_node(
        "person-2", "person", confidence=0.4, classification=Classification.CONFIDENTIAL
    )
    person3 = make_node("person-3", "person", confidence=0.9)
    project1 = make_node("project-1", "project", confidence=0.9)
    rel1 = make_edge("rel-1", "person-1", "project-1", edge_type="owns", valid_from=T0)
    rel2 = make_edge(
        "rel-2", "person-2", "project-1", edge_type="owns", valid_from=T0, valid_until=T1
    )
    return MemoryGraph(nodes=(person1, person2, person3, project1), edges=(rel1, rel2))


@pytest.fixture
def store() -> InMemoryGraphStore:
    store = InMemoryGraphStore()
    store.write(TENANT_A, base_graph(), principal=PRINCIPAL)
    store.write(TENANT_B, MemoryGraph(nodes=(make_node("person-only-in-b"),)), principal=PRINCIPAL)
    return store


@pytest.fixture
def application(store: InMemoryGraphStore) -> KnowledgeGraphApplication:
    return KnowledgeGraphApplication(graph_store=store, revision_reader=store)


@pytest.fixture
def caller_context_a() -> CallerContext:
    return CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-test", roles=("service-account",)),
        tenant=TENANT_A,
    )


def _real_policy_enforcement_point() -> LocalPolicyEnforcementPoint:
    return LocalPolicyEnforcementPoint(load_policy_config(POLICY_CONFIG_PATH))


@pytest.fixture
def client(application: KnowledgeGraphApplication, caller_context_a: CallerContext) -> TestClient:
    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: application
    # Mutation routes depend on require_tenant_context; read routes depend
    # on require_authenticated_caller (Phase 2B, ADR-038 — accepts either a
    # plain service token or a Delegated Credential). Both are overridden
    # with the same caller_context_a so every pre-existing route test keeps
    # its previously-expected, identical response for this caller.
    app.dependency_overrides[require_tenant_context] = lambda: caller_context_a
    app.dependency_overrides[require_authenticated_caller] = lambda: caller_context_a
    app.dependency_overrides[policy_enforcement_point_dependency] = _real_policy_enforcement_point
    return TestClient(app)


@pytest.fixture
def client_no_auth_override(
    application: KnowledgeGraphApplication,
) -> TestClient:
    """A client with the real `require_tenant_context` dependency still
    wired (only the application-service and policy-enforcement-point
    dependencies are overridden) — used to exercise the actual
    auth-rejection path (missing/malformed header), which is rejected
    before authorization is ever evaluated."""
    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: application
    app.dependency_overrides[policy_enforcement_point_dependency] = _real_policy_enforcement_point
    return TestClient(app)
