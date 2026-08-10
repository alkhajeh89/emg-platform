"""Phase 2B — delegated-request audit attribution, fail-closed (Required
Change #2), plus regression proof that ADR-025 403 / ADR-026 classification
denial behavior is unchanged for delegated callers and that the BFF never
evaluates policy locally (the PEP call site is identical for both caller
kinds — see authorization.py).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from emg_auth_client import Principal
from emg_errors import UpstreamServiceError
from emg_knowledge_graph_api import audit_producer
from emg_knowledge_graph_api.authn import CallerContext
from emg_knowledge_graph_api.dependencies import (
    knowledge_graph_application_dependency,
    policy_enforcement_point_dependency,
)
from emg_knowledge_graph_api.main import create_app
from emg_policy_engine import LocalPolicyEnforcementPoint, load_policy_config
from fastapi.testclient import TestClient

from .conftest import POLICY_CONFIG_PATH, TENANT_A


def _delegated_caller() -> CallerContext:
    return CallerContext(
        principal=Principal(
            subject="human-a",
            roles=(
                "service-account",
            ),  # matches the existing broad-grant test role in policy.example.yaml
            attributes={"classification_clearance": "SECRET"},
        ),
        tenant=TENANT_A,
        acting_service="emg-studio-bff",
    )


def _service_caller() -> CallerContext:
    from emg_knowledge_graph_api.authn import ServicePrincipal

    return CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-test", roles=("service-account",)),
        tenant=TENANT_A,
        acting_service=None,
    )


@pytest.fixture
def delegated_client(application, monkeypatch):
    from emg_knowledge_graph_api.authn import require_authenticated_caller

    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: application
    app.dependency_overrides[require_authenticated_caller] = _delegated_caller
    app.dependency_overrides[policy_enforcement_point_dependency] = (
        lambda: LocalPolicyEnforcementPoint(load_policy_config(POLICY_CONFIG_PATH))
    )
    return TestClient(app)


@pytest.fixture
def service_client(application):
    from emg_knowledge_graph_api.authn import require_authenticated_caller, require_tenant_context

    app = create_app()
    app.dependency_overrides[knowledge_graph_application_dependency] = lambda: application
    app.dependency_overrides[require_tenant_context] = _service_caller
    app.dependency_overrides[require_authenticated_caller] = _service_caller
    app.dependency_overrides[policy_enforcement_point_dependency] = (
        lambda: LocalPolicyEnforcementPoint(load_policy_config(POLICY_CONFIG_PATH))
    )
    return TestClient(app)


def test_delegated_request_with_audit_success_returns_200_with_data(delegated_client, monkeypatch):
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code == 200
    assert "person-1" in response.text
    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["resource_id"] == "person-1"


def test_delegated_request_fails_closed_when_audit_emission_fails(delegated_client, monkeypatch):
    async def failing_emit(*args, **kwargs):
        raise UpstreamServiceError("simulated audit outage")

    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", failing_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-1")

    # Fail-closed: any 5xx is acceptable evidence (KG's error map does not
    # dedicate a specific status to UpstreamServiceError beyond the generic
    # 500 fallback) — what matters is that this is NOT a 200 and NOT the
    # entity payload.
    assert response.status_code >= 500
    assert '"node_id"' not in response.text


def test_delegated_search_audits_only_bounded_safe_metadata(delegated_client, monkeypatch):
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = delegated_client.post(
        "/v1/knowledge-graph/search", json={"q": "person-secret-term", "limit": 7}
    )

    assert response.status_code == 200
    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["action"] == "search"
    assert kwargs["resource_id"] is None
    assert kwargs["safe_metadata"] == {
        "requested_page_size": "7",
        "continuation": "false",
        "normalizer_version": "1",
        "query_length_bucket": "17-64",
    }
    assert "person-secret-term" not in repr(kwargs)


def test_delegated_search_audit_failure_is_fail_closed(delegated_client, monkeypatch):
    async def failing_emit(*args, **kwargs):
        raise UpstreamServiceError("simulated audit outage")

    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", failing_emit)
    response = delegated_client.post("/v1/knowledge-graph/search", json={"q": "person", "limit": 1})
    assert response.status_code >= 500
    assert '"node_id"' not in response.text


def test_delegated_search_validation_failure_is_audit_attributed(delegated_client, monkeypatch):
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)
    response = delegated_client.post(
        "/v1/knowledge-graph/search", json={"q": "sensitive-invalid-term", "limit": 0}
    )
    assert response.status_code == 400
    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["outcome"] == "error"
    assert "sensitive-invalid-term" not in repr(kwargs)


def test_non_delegated_service_request_never_calls_audit_and_is_unaffected(
    service_client, monkeypatch
):
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = service_client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code == 200
    fake_emit.assert_not_awaited()


def test_classification_denial_unchanged_for_delegated_caller(delegated_client, monkeypatch):
    """ADR-026 denial shape (indistinguishable-from-not-found) is identical
    for a delegated caller as for a service caller — proven here by denying
    at the operation level via a caller with no granted role, since
    per-object classification denial is already covered end-to-end by
    test_classification_scenarios.py against the same require_permission_delegated_aware
    call site this module wires delegated callers through.

    **Correction-sprint Finding 6**: unlike before this fix, a delegated
    operation-level denial is now ALSO audit-attributed (outcome="denied"),
    before the caller ever sees the 403 — see the two tests immediately
    below for the audit-succeeds and audit-fails-on-deny cases specifically.
    This test only re-confirms the response SHAPE (403, ADR-026-indistinguishable)
    is unchanged; audit behavior on deny has its own dedicated coverage."""
    from emg_knowledge_graph_api.authn import require_authenticated_caller

    unauthorized = CallerContext(
        principal=Principal(
            subject="human-b", roles=(), attributes={"classification_clearance": "SECRET"}
        ),
        tenant=TENANT_A,
        acting_service="emg-studio-bff",
    )
    delegated_client.app.dependency_overrides[require_authenticated_caller] = lambda: unauthorized
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code == 403


def test_delegated_denial_is_audit_attributed_before_the_403(delegated_client, monkeypatch):
    """Correction-sprint Finding 6 (ADR-038 §8.7: 'authorization decision'
    must be recorded for every delegated operation, not only allowed
    ones). The denial audit call happens in the authorization dependency,
    before the route body ever runs."""
    from emg_knowledge_graph_api.authn import require_authenticated_caller

    unauthorized = CallerContext(
        principal=Principal(
            subject="human-b", roles=(), attributes={"classification_clearance": "SECRET"}
        ),
        tenant=TENANT_A,
        acting_service="emg-studio-bff",
    )
    delegated_client.app.dependency_overrides[require_authenticated_caller] = lambda: unauthorized
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code == 403
    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["outcome"] == "denied"


def test_delegated_denial_escalates_to_500_when_audit_attribution_fails(
    delegated_client, monkeypatch
):
    """A denial that cannot itself be audit-attributed must not be returned
    to the caller as an ordinary, silently-unattributed 403 — it escalates
    to a 500, since ADR-038 §8.7 attribution could not be guaranteed."""
    from emg_knowledge_graph_api.authn import require_authenticated_caller

    unauthorized = CallerContext(
        principal=Principal(
            subject="human-b", roles=(), attributes={"classification_clearance": "SECRET"}
        ),
        tenant=TENANT_A,
        acting_service="emg-studio-bff",
    )
    delegated_client.app.dependency_overrides[require_authenticated_caller] = lambda: unauthorized

    async def failing_emit(*args, **kwargs):
        raise UpstreamServiceError("simulated audit outage")

    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", failing_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code >= 500
    assert response.status_code != 403


def test_non_delegated_denial_never_calls_audit_and_is_unaffected(service_client, monkeypatch):
    """The non-delegated (service-to-service) deny path is completely
    unaffected by Finding 6 — no audit call is attempted, exactly as
    before this correction."""
    from emg_knowledge_graph_api.authn import ServicePrincipal, require_authenticated_caller

    unauthorized_service = CallerContext(
        principal=ServicePrincipal(client_id="emg-svc-test", roles=()),
        tenant=TENANT_A,
        acting_service=None,
    )
    service_client.app.dependency_overrides[require_authenticated_caller] = (
        lambda: unauthorized_service
    )
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = service_client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code == 403
    fake_emit.assert_not_awaited()


def test_classification_denied_entity_is_audit_attributed_as_denied_not_success(
    delegated_client, monkeypatch
):
    """Final correction-sprint Finding 4: person-2 is CONFIDENTIAL; a caller
    with only INTERNAL clearance gets the same 404 shape as a genuine
    not-found (ADR-026 uniform denial), but the audit record must say
    "denied", distinguishing it internally from a real absence."""
    from emg_knowledge_graph_api.authn import require_authenticated_caller

    low_clearance_caller = CallerContext(
        principal=Principal(
            subject="human-a",
            roles=("service-account",),
            attributes={"classification_clearance": "INTERNAL"},
        ),
        tenant=TENANT_A,
        acting_service="emg-studio-bff",
    )
    delegated_client.app.dependency_overrides[require_authenticated_caller] = (
        lambda: low_clearance_caller
    )
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-2")

    assert response.status_code == 404
    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["outcome"] == "denied"


def test_genuine_not_found_entity_is_audit_attributed_as_not_found(delegated_client, monkeypatch):
    """Same 404 shape as a classification denial, but a genuinely
    nonexistent entity id must be attributed "not_found", not "denied" —
    the two are distinguishable in the audit record even though the HTTP
    response is identical either way."""
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-does-not-exist")

    assert response.status_code == 404
    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["outcome"] == "not_found"


def test_unhandled_error_during_delegated_request_is_audit_attributed_as_error(
    delegated_client, monkeypatch
):
    """Final correction-sprint Finding 4: an unexpected exception during a
    delegated request must still be audit-attributed (outcome="error")
    before the 500 propagates — not silently unattributed."""
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated unexpected application error")

    delegated_client.app.dependency_overrides[knowledge_graph_application_dependency] = (
        lambda: type("Boom", (), {"get_entity": staticmethod(boom)})()
    )

    with pytest.raises(RuntimeError, match="simulated unexpected application error"):
        delegated_client.get("/v1/knowledge-graph/entities/person-1")

    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["outcome"] == "error"


def test_delegated_success_still_attributed_as_success(delegated_client, monkeypatch):
    """Regression: the plain success path (person-1, within clearance)
    still attributes outcome="success" exactly as before Finding 4."""
    fake_emit = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_producer, "emit_delegated_audit_event", fake_emit)

    response = delegated_client.get("/v1/knowledge-graph/entities/person-1")

    assert response.status_code == 200
    fake_emit.assert_awaited_once()
    _, kwargs = fake_emit.await_args
    assert kwargs["outcome"] == "success"


def test_bff_never_evaluates_policy_locally_pep_is_the_only_authority(delegated_client):
    """Structural proof: the delegated route depends on the exact same
    PolicyEnforcementPointDep / require_permission_delegated_aware call
    site as the service-to-service path (authorization.py) — there is no
    separate, BFF-local authorization branch anywhere in this service.

    Correction-sprint Finding 12 deduplicated the two factories' PEP call
    into one shared `_authorize()` helper — there is now exactly ONE
    `pep.authorize(` call site in the whole module, structurally impossible
    for the two paths to diverge (stronger evidence than the pre-dedup
    "two identical call sites" this test previously checked for)."""
    import inspect

    from emg_knowledge_graph_api import authorization

    source = inspect.getsource(authorization)
    assert source.count("pep.authorize(") == 1
    assert source.count("_authorize(") == 3  # def + both factories calling it
