"""DELEGATION test category, BFF side: token exchange happens per call (no
caching/reuse), exchange failure fails closed, delegated request never
forwards without a Delegated Credential."""

from __future__ import annotations

import time

import httpx
import pytest
from emg_studio_bff import delegation
from emg_studio_bff.session_store import HumanSession


def _seed_session(session_store, *, session_id="sess-deleg") -> HumanSession:
    session = HumanSession(
        session_id=session_id,
        subject="human-a",
        tenant_id="tenant-a",
        classification_clearance="CONFIDENTIAL",
        roles=("investigator",),
        access_token="human-access-token",
        refresh_token="human-refresh-token",
        access_token_expires_at=time.time() + 300,
        created_at=time.time(),
        csrf_token="csrf-token-value",
    )
    session_store.create_session(session)
    return session


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in recording every call it receives,
    so tests can assert exchange happens exactly once per proxied request
    (never cached/reused) without a live Keycloak or Knowledge Graph."""

    calls: list[tuple[str, str, dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, **kwargs):
        _FakeAsyncClient.calls.append(("POST", url, data or {}))
        exchanged_access_token = f"delegated-token-{len(_FakeAsyncClient.calls)}"
        return httpx.Response(200, json={"access_token": exchanged_access_token, "expires_in": 60})

    async def get(self, url, params=None, headers=None, **kwargs):
        _FakeAsyncClient.calls.append(
            ("GET", url, {"params": dict(params or {}), "headers": dict(headers or {})})
        )
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})


@pytest.fixture(autouse=True)
def _reset_fake_calls():
    _FakeAsyncClient.calls = []
    yield
    _FakeAsyncClient.calls = []


@pytest.fixture
def patch_httpx(monkeypatch):
    monkeypatch.setattr("emg_studio_bff.delegation.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        "emg_studio_bff.routers.knowledge_graph_proxy.httpx.AsyncClient", _FakeAsyncClient
    )


def test_token_exchange_happens_on_every_call_not_cached(client, session_store, patch_httpx):
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    first = client.get("/api/knowledge-graph/entities/e1")
    second = client.get("/api/knowledge-graph/entities/e1")

    assert first.status_code == 200
    assert second.status_code == 200

    exchange_calls = [c for c in _FakeAsyncClient.calls if c[0] == "POST"]
    assert (
        len(exchange_calls) == 2
    ), "expected a fresh token exchange for each proxied call, not a reused credential"

    kg_calls = [c for c in _FakeAsyncClient.calls if c[0] == "GET"]
    assert len(kg_calls) == 2
    # Each forwarded call carries a DIFFERENT delegated bearer token —
    # proof the second call did not reuse the first's credential.
    auth_headers = [c[2]["headers"]["Authorization"] for c in kg_calls]
    assert auth_headers[0] != auth_headers[1]


def test_exchange_failure_fails_closed_no_forward_attempted(client, session_store, monkeypatch):
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    async def failing_exchange(settings, *, subject_token, audience):
        raise delegation.DelegationError("simulated exchange failure")

    monkeypatch.setattr(
        "emg_studio_bff.routers.knowledge_graph_proxy.delegation.exchange_for_delegated_credential",
        failing_exchange,
    )

    response = client.get("/api/knowledge-graph/entities/e1")
    assert response.status_code == 401
    assert "ok" not in response.text


def test_proxy_forwards_upstream_status_and_body_unchanged(client, session_store, patch_httpx):
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    response = client.get("/api/knowledge-graph/entities/e1")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_proxy_response_defaults_to_private_no_store(client, session_store, patch_httpx):
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    response = client.get("/api/knowledge-graph/entities/e1")
    assert response.headers.get("cache-control") == "private, no-store"


def test_proxy_requires_an_authenticated_session(client):
    response = client.get("/api/knowledge-graph/entities/e1")
    assert response.status_code == 401


def test_proxy_is_get_only_no_mutation_route_reachable(client, session_store):
    """The router only declares a GET route — POST/PUT/DELETE to any path
    under /api/knowledge-graph/ must 405, never reach a mutation."""
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    response = client.post("/api/knowledge-graph/entities", json={"malicious": "mutation"})
    assert response.status_code in (404, 405)


def test_browser_supplied_tenant_query_param_is_rejected(client, session_store, patch_httpx):
    """Correction-sprint Finding 10 (ADR-036 D-5): the BFF itself must not
    accept a client-supplied tenant/security-identity parameter — rejected
    before any token exchange or upstream call is attempted."""
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    response = client.get("/api/knowledge-graph/entities/e1", params={"tenant_id": "attacker"})
    assert response.status_code == 401
    assert _FakeAsyncClient.calls == [], "no exchange or upstream call should have been attempted"


def test_browser_supplied_classification_clearance_query_param_is_rejected(
    client, session_store, patch_httpx
):
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    response = client.get(
        "/api/knowledge-graph/entities/e1", params={"classification_clearance": "SECRET"}
    )
    assert response.status_code == 401
    assert _FakeAsyncClient.calls == []


def test_upstream_set_cookie_header_is_never_forwarded_to_browser(
    client, session_store, monkeypatch
):
    """Final correction-sprint Finding 9: a downstream service must never be
    able to inject a cookie into the browser's trusted BFF origin."""
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    class _CookieInjectingClient(_FakeAsyncClient):
        async def get(self, url, params=None, headers=None, **kwargs):
            _FakeAsyncClient.calls.append(("GET", url, {}))
            return httpx.Response(
                200,
                json={"ok": True},
                headers={
                    "content-type": "application/json",
                    "set-cookie": "evil=injected; Path=/",
                },
            )

    monkeypatch.setattr(
        "emg_studio_bff.routers.knowledge_graph_proxy.httpx.AsyncClient", _CookieInjectingClient
    )
    monkeypatch.setattr("emg_studio_bff.delegation.httpx.AsyncClient", _FakeAsyncClient)

    response = client.get("/api/knowledge-graph/entities/e1")

    assert response.status_code == 200
    assert "set-cookie" not in {k.lower() for k in response.headers}
    assert "evil" not in response.headers.get("set-cookie", "")


def test_correlation_id_forwarded_to_upstream_matches_bff_own_id(
    client, session_store, patch_httpx
):
    """Correction-sprint Finding 9: the BFF's own correlation-id middleware
    value (not a raw, possibly-empty re-read of the incoming header) is what
    reaches Knowledge Graph."""
    _seed_session(session_store)
    client.cookies.set("__Host-emg_studio_session", "sess-deleg")

    response = client.get(
        "/api/knowledge-graph/entities/e1", headers={"x-correlation-id": "browser-supplied-id"}
    )
    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "browser-supplied-id"

    kg_calls = [c for c in _FakeAsyncClient.calls if c[0] == "GET"]
    assert len(kg_calls) == 1
    assert kg_calls[0][2]["headers"]["x-correlation-id"] == "browser-supplied-id"
