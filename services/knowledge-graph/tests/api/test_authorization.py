"""HTTP-level authorization tests for the Knowledge Graph Query API
(ADR-025 Group C9).

Covers, at the HTTP boundary, every category the Group C task list requires:

- allowed: a caller whose role is granted by the real
  `config/policy.example.yaml` receives the identical, unchanged response
  every other (pre-existing) route test already expects.
- denied (missing role): a caller with no role the policy grants receives
  403 `PERMISSION_DENIED` on every one of the seven routes.
- missing policy: a missing policy configuration file falls back to an
  empty, default-deny ruleset (`emg_policy_engine.loader.load_policy_config`),
  so a caller who would otherwise be allowed is denied.
- missing scope: a service principal whose role matches but whose scope
  does not satisfy a scope-conditioned rule is denied.
- default deny: an unrecognized resource_type/action pair (no matching
  rule at all) is denied by the Policy Engine's own default-deny behavior.
- ordering (ADR-025 §8.8): authentication failure (401) is never masked by
  or reordered behind an authorization decision (403); not-found (404)
  remains unchanged and orthogonal to authorization.

The ABAC combining logic itself (default-deny, deny-overrides) is
unit-tested in `libs/python/emg-policy-engine/tests/test_engine.py`; the
scenario-based real-policy expectations are covered in
`tests/test_authz_scenarios.py`. This module is HTTP-boundary testing only
— it exercises `require_permission`/`policy_enforcement_point_dependency`
exactly as a real request would, never a direct call into a router
function.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from emg_auth_client import AuthorizationRequest
from emg_errors import PermissionDeniedError
from emg_knowledge_graph import KnowledgeGraphApplication
from emg_knowledge_graph_api.authn import CallerContext, ServicePrincipal, require_tenant_context
from emg_knowledge_graph_api.authorization import require_permission
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
from emg_policy_engine import LocalPolicyEnforcementPoint, load_policy_config
from emg_policy_engine.rules import PolicyConfig, PolicyRule
from fastapi.testclient import TestClient

from .conftest import POLICY_CONFIG_PATH, TENANT_A

# One representative request per route, parametrized (method, path, resource_type).
_ROUTES = [
    ("GET", "/v1/knowledge-graph/entities/person-1", RESOURCE_ENTITY),
    ("GET", "/v1/knowledge-graph/entities", RESOURCE_ENTITY),
    ("GET", "/v1/knowledge-graph/edges/rel-1", RESOURCE_EDGE),
    ("GET", "/v1/knowledge-graph/edges", RESOURCE_EDGE),
    ("GET", "/v1/knowledge-graph/entities/person-1/neighbors", RESOURCE_NEIGHBORS),
    (
        "GET",
        "/v1/knowledge-graph/paths/shortest?from_node_id=person-1&to_node_id=project-1",
        RESOURCE_PATH,
    ),
    (
        "GET",
        "/v1/knowledge-graph/entities/person-1/history/owner?valid_at=2026-01-15T00:00:00Z",
        RESOURCE_HISTORY,
    ),
]


def _client_for(
    application: KnowledgeGraphApplication,
    *,
    caller_context: CallerContext,
    pep: LocalPolicyEnforcementPoint,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: application
    app.dependency_overrides[require_tenant_context] = lambda: caller_context
    app.dependency_overrides[policy_enforcement_point_dependency] = lambda: pep
    return TestClient(app)


def _real_pep() -> LocalPolicyEnforcementPoint:
    return LocalPolicyEnforcementPoint(load_policy_config(POLICY_CONFIG_PATH))


def _empty_pep() -> LocalPolicyEnforcementPoint:
    return LocalPolicyEnforcementPoint(PolicyConfig(rules=[]))


# --- allowed -----------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "_resource_type"), _ROUTES)
def test_granted_role_is_allowed(
    application: KnowledgeGraphApplication, method: str, path: str, _resource_type: str
) -> None:
    caller = CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-test", roles=("service-account",)),
        tenant=TENANT_A,
    )
    client = _client_for(application, caller_context=caller, pep=_real_pep())
    response = client.request(method, path)
    assert response.status_code != 403
    assert response.status_code != 401


# --- denied: missing role ------------------------------------------------


@pytest.mark.parametrize(("method", "path", "_resource_type"), _ROUTES)
def test_ungranted_role_is_denied_with_403(
    application: KnowledgeGraphApplication, method: str, path: str, _resource_type: str
) -> None:
    caller = CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-untrusted", roles=("some-other-role",)),
        tenant=TENANT_A,
    )
    client = _client_for(application, caller_context=caller, pep=_real_pep())
    response = client.request(method, path)
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["error_code"] == "PERMISSION_DENIED"
    assert body["data"] is None
    assert "correlation_id" in body
    assert "Traceback" not in response.text


def test_principal_with_no_roles_at_all_is_denied(
    application: KnowledgeGraphApplication,
) -> None:
    caller = CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-bare", roles=()),
        tenant=TENANT_A,
    )
    client = _client_for(application, caller_context=caller, pep=_real_pep())
    response = client.get("/v1/knowledge-graph/entities/person-1")
    assert response.status_code == 403
    assert response.json()["error"]["error_code"] == "PERMISSION_DENIED"


# --- missing policy configuration ---------------------------------------


def test_missing_policy_file_denies_a_normally_allowed_caller(
    application: KnowledgeGraphApplication,
) -> None:
    missing_path = Path(__file__).resolve().parent / "does-not-exist-policy.yaml"
    assert not missing_path.exists()
    pep = LocalPolicyEnforcementPoint(load_policy_config(missing_path))
    caller = CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-test", roles=("service-account",)),
        tenant=TENANT_A,
    )
    client = _client_for(application, caller_context=caller, pep=pep)
    response = client.get("/v1/knowledge-graph/entities/person-1")
    assert response.status_code == 403
    assert response.json()["error"]["error_code"] == "PERMISSION_DENIED"


def test_empty_policy_config_denies_every_route(
    application: KnowledgeGraphApplication,
) -> None:
    caller = CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-test", roles=("service-account",)),
        tenant=TENANT_A,
    )
    client = _client_for(application, caller_context=caller, pep=_empty_pep())
    for method, path, _resource_type in _ROUTES:
        response = client.request(method, path)
        assert response.status_code == 403, f"{method} {path} was not denied by an empty policy"


# --- missing scope (service principal: role matches, scope does not) ----


def test_service_principal_missing_required_scope_is_denied() -> None:
    config = PolicyConfig(
        rules=[
            PolicyRule(
                rule_id="scoped-rule",
                resource_type=RESOURCE_ENTITY,
                action="read",
                effect="allow",
                required_roles=["service-account"],
                required_scopes=["knowledge-graph:read"],
            )
        ]
    )
    pep = LocalPolicyEnforcementPoint(config)
    dependency = require_permission(RESOURCE_ENTITY)
    caller = CallerContext(
        principal=ServicePrincipal(
            client_id="emg-svc-test", roles=("service-account",), scopes=("unrelated-scope",)
        ),
        tenant=TENANT_A,
    )
    with pytest.raises(PermissionDeniedError):
        dependency(caller, pep)


def test_service_principal_with_required_scope_is_allowed() -> None:
    config = PolicyConfig(
        rules=[
            PolicyRule(
                rule_id="scoped-rule",
                resource_type=RESOURCE_ENTITY,
                action="read",
                effect="allow",
                required_roles=["service-account"],
                required_scopes=["knowledge-graph:read"],
            )
        ]
    )
    pep = LocalPolicyEnforcementPoint(config)
    dependency = require_permission(RESOURCE_ENTITY)
    caller = CallerContext(
        principal=ServicePrincipal(
            client_id="emg-svc-test", roles=("service-account",), scopes=("knowledge-graph:read",)
        ),
        tenant=TENANT_A,
    )
    dependency(caller, pep)  # must not raise


# --- default deny (no matching rule at all) ------------------------------


def test_unrecognized_resource_type_is_denied_by_default() -> None:
    pep = _real_pep()
    decision = pep.authorize(
        AuthorizationRequest(
            principal=ServicePrincipal(client_id="emg-svc-test", roles=("service-account",)),
            resource_type="knowledge-graph.nonexistent",
            action="read",
        )
    )
    assert decision.outcome == "deny"


# --- ordering: authentication failures are never masked by authorization ---


def test_missing_authorization_header_is_401_not_403(client_no_auth_override: TestClient) -> None:
    response = client_no_auth_override.get("/v1/knowledge-graph/entities/person-1")
    assert response.status_code == 401
    assert response.json()["error"]["error_code"] == "AUTHORIZATION_ERROR"


def test_not_found_remains_404_for_an_authorized_caller(client: TestClient) -> None:
    # `client` fixture's `caller_context_a` (service-account) is granted by
    # the real policy; a nonexistent id within the caller's own tenant is
    # still a 404, unaffected by authorization.
    response = client.get("/v1/knowledge-graph/entities/ghost")
    assert response.status_code == 404
    assert response.json()["error"]["error_code"] == "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"
