"""ADR-042 dedicated Studio BFF governed-search security contract."""

from __future__ import annotations

import json
import logging
import time

import httpx
import pytest
from emg_studio_bff import delegation
from emg_studio_bff.config import Settings, validate_runtime_configuration
from emg_studio_bff.session_store import HumanSession
from pydantic import ValidationError

CSRF = "csrf-token-value"
HUMAN_TOKEN = "human-access-token-never-browser-visible"
DELEGATED_TOKEN = "delegated-token-never-browser-visible"
SEARCH_URL = "/api/knowledge-graph/search"


def _seed_session(
    client, session_store, *, session_id: str = "search-session", expired: bool = False
) -> HumanSession:
    now = time.time()
    session = HumanSession(
        session_id=session_id,
        subject="human-a",
        tenant_id="tenant-a",
        classification_clearance="CONFIDENTIAL",
        roles=("investigator",),
        access_token=HUMAN_TOKEN,
        refresh_token=None,
        access_token_expires_at=now - 1 if expired else now + 300,
        created_at=now,
        csrf_token=CSRF,
    )
    session_store.create_session(session)
    client.cookies.set("__Host-emg_studio_session", session_id)
    client.cookies.set("__Host-emg_studio_csrf", CSRF)
    return session


class _StreamResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = httpx.Headers(headers or {"content-type": "application/json"})
        self._body = body

    async def aiter_bytes(self):
        yield self._body


class _StreamContext:
    def __init__(self, response: _StreamResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response

    async def __aexit__(self, *exc):
        return False


class _RecordingClient:
    calls: list[dict[str, object]] = []
    response = _StreamResponse(200, b'{"items":[],"page_info":{"limit":20}}')
    error: Exception | None = None
    configured_timeout: float | None = None

    def __init__(self, *, timeout: float) -> None:
        type(self).configured_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, *, content, headers):
        type(self).calls.append(
            {"method": method, "url": url, "content": content, "headers": dict(headers)}
        )
        return _StreamContext(type(self).response, type(self).error)


@pytest.fixture(autouse=True)
def _reset_recording_client():
    _RecordingClient.calls = []
    _RecordingClient.response = _StreamResponse(200, b'{"items":[],"page_info":{"limit":20}}')
    _RecordingClient.error = None
    _RecordingClient.configured_timeout = None
    yield


@pytest.fixture
def search_transport(monkeypatch):
    exchanges: list[dict[str, object]] = []

    async def exchange(settings, *, subject_token, audience):
        exchanges.append({"subject_token": subject_token, "audience": audience})
        return delegation.DelegatedCredential(
            access_token=DELEGATED_TOKEN,
            acting_service="emg-studio-bff-test",
            audience=audience,
            expires_in=60,
        )

    monkeypatch.setattr(
        "emg_studio_bff.routers.knowledge_graph_proxy.delegation.exchange_for_delegated_credential",
        exchange,
    )
    monkeypatch.setattr(
        "emg_studio_bff.routers.knowledge_graph_proxy.httpx.AsyncClient", _RecordingClient
    )
    return exchanges


def _post(client, payload=b'{"q":"confidential acquisition"}', **kwargs):
    headers = {
        "content-type": "application/json",
        "x-csrf-token": CSRF,
        **kwargs.pop("headers", {}),
    }
    return client.post(SEARCH_URL, content=payload, headers=headers, **kwargs)


def test_search_requires_session_and_rejects_expired_session(client, session_store):
    assert _post(client).status_code == 401
    _seed_session(client, session_store, expired=True)
    assert _post(client).status_code == 401


@pytest.mark.parametrize("missing", ["cookie", "header"])
def test_missing_csrf_fails_before_exchange(client, session_store, search_transport, missing):
    _seed_session(client, session_store)
    headers = {} if missing == "header" else {"x-csrf-token": CSRF}
    if missing == "cookie":
        client.cookies.delete("__Host-emg_studio_csrf")
    response = client.post(
        SEARCH_URL,
        content=b'{"q":"private"}',
        headers={"content-type": "application/json", **headers},
    )
    assert response.status_code == 401
    assert search_transport == []
    assert _RecordingClient.calls == []


def test_csrf_mismatch_fails_before_exchange(client, session_store, search_transport):
    _seed_session(client, session_store)
    response = _post(client, headers={"x-csrf-token": "wrong"})
    assert response.status_code == 401
    assert search_transport == []
    assert _RecordingClient.calls == []


def test_valid_request_is_forwarded_unchanged_to_fixed_route_with_fresh_delegation(
    client, session_store, settings, search_transport
):
    _seed_session(client, session_store)
    body = b'{"q":"North","limit":2,"cursor":"opaque"}'
    browser_headers = {
        "authorization": "Bearer browser-attacker",
        "x-csrf-token": CSRF,
        "x-tenant-id": "attacker",
        "x-clearance": "TOP_SECRET",
        "x-principal": "attacker",
        "x-acting-service": "attacker",
    }
    first = _post(client, body, headers=browser_headers)
    second = _post(client, body, headers=browser_headers)

    assert first.status_code == second.status_code == 200
    assert len(search_transport) == 2
    assert all(call["subject_token"] == HUMAN_TOKEN for call in search_transport)
    assert all(call["audience"] == settings.knowledge_graph_audience for call in search_transport)
    assert len(_RecordingClient.calls) == 2
    for call in _RecordingClient.calls:
        assert call["method"] == "POST"
        assert call["url"] == "http://kg.test/v1/knowledge-graph/search"
        assert call["content"] == body
        headers = {key.lower(): value for key, value in call["headers"].items()}
        assert set(headers) == {"authorization", "content-type", "x-correlation-id"}
        assert headers["authorization"] == f"Bearer {DELEGATED_TOKEN}"
        assert headers["content-type"] == "application/json"
        assert "cookie" not in headers and "x-csrf-token" not in headers


def test_browser_cannot_select_path_method_or_query_parameters(
    client, session_store, search_transport
):
    _seed_session(client, session_store)
    assert client.post(
        "/api/knowledge-graph/admin", json={"q": "x"}, headers={"x-csrf-token": CSRF}
    ).status_code in (404, 405)
    assert client.put(SEARCH_URL, json={"q": "x"}).status_code == 405
    assert _post(client, params={"tenant_id": "attacker"}).status_code == 401
    assert search_transport == []
    assert _RecordingClient.calls == []


@pytest.mark.parametrize(
    ("payload", "content_type"),
    [
        (b'{"q":"x","tenant":"attacker"}', "application/json"),
        (b'{"q":"x","q":"y"}', "application/json"),
        (b"not-json", "application/json"),
        (b'{"q":"x"}', "text/plain"),
    ],
)
def test_invalid_transport_fails_before_exchange(
    client, session_store, search_transport, payload, content_type
):
    _seed_session(client, session_store)
    response = client.post(
        SEARCH_URL,
        content=payload,
        headers={"content-type": content_type, "x-csrf-token": CSRF},
    )
    assert response.status_code == 400
    assert search_transport == []
    assert _RecordingClient.calls == []


def test_oversized_request_fails_before_exchange_and_upstream(
    client, session_store, search_transport
):
    _seed_session(client, session_store)
    response = _post(client, b"{" + b'"q":"' + b"x" * 8_192 + b'"}')
    assert response.status_code == 400
    assert search_transport == []
    assert _RecordingClient.calls == []


def test_exchange_failure_has_no_service_only_fallback(client, session_store, monkeypatch):
    _seed_session(client, session_store)

    async def fail(*args, **kwargs):
        raise delegation.DelegationError("private exchange detail")

    monkeypatch.setattr(
        "emg_studio_bff.routers.knowledge_graph_proxy.delegation.exchange_for_delegated_credential",
        fail,
    )
    monkeypatch.setattr(
        "emg_studio_bff.routers.knowledge_graph_proxy.httpx.AsyncClient", _RecordingClient
    )
    response = _post(client)
    assert response.status_code == 401
    assert "private exchange detail" not in response.text
    assert _RecordingClient.calls == []


@pytest.mark.parametrize("error", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
def test_upstream_transport_failure_is_generic_and_not_retried(
    client, session_store, search_transport, error
):
    _seed_session(client, session_store)
    _RecordingClient.error = error
    response = _post(client)
    assert response.status_code == 502
    assert response.json()["error"]["message"] == "Upstream service unavailable"
    assert len(_RecordingClient.calls) == 1


@pytest.mark.parametrize("status", [400, 403, 503])
def test_safe_upstream_error_status_and_body_are_preserved(
    client, session_store, search_transport, status
):
    _seed_session(client, session_store)
    body = json.dumps({"data": None, "error": {"error_code": "SAFE_ERROR"}}).encode()
    _RecordingClient.response = _StreamResponse(status, body)
    response = _post(client)
    assert response.status_code == status
    assert response.content == body
    assert len(_RecordingClient.calls) == 1


def test_oversized_upstream_response_fails_closed(
    client, session_store, settings, search_transport
):
    _seed_session(client, session_store)
    _RecordingClient.response = _StreamResponse(
        200, b"x" * (settings.search_max_response_bytes + 1)
    )
    response = _post(client)
    assert response.status_code == 502
    assert response.json()["error"]["message"] == "Upstream service unavailable"


def test_tokens_cookies_and_security_context_never_return_to_browser(
    client, session_store, search_transport
):
    _seed_session(client, session_store)
    _RecordingClient.response = _StreamResponse(
        200,
        b'{"items":[]}',
        {
            "content-type": "application/json",
            "set-cookie": "evil=injected",
            "server": "kg",
            "x-upstream-internal": "private",
        },
    )
    response = _post(client)
    assert response.status_code == 200
    assert HUMAN_TOKEN not in response.text and DELEGATED_TOKEN not in response.text
    assert "set-cookie" not in response.headers
    assert "server" not in response.headers
    assert "x-upstream-internal" not in response.headers
    assert response.headers["cache-control"] == "private, no-store"


def test_query_and_cursor_are_absent_from_url_and_logs(
    client, session_store, search_transport, caplog
):
    _seed_session(client, session_store)
    query = "highly-confidential-query-needle"
    cursor = "opaque-sensitive-cursor-needle"
    with caplog.at_level(logging.DEBUG):
        response = _post(
            client,
            json.dumps({"q": query, "cursor": cursor}, separators=(",", ":")).encode(),
        )
    assert response.status_code == 200
    assert query not in str(_RecordingClient.calls[0]["url"])
    assert cursor not in str(_RecordingClient.calls[0]["url"])
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert query not in rendered_logs and cursor not in rendered_logs


def test_explicit_timeout_is_used(client, session_store, settings, search_transport):
    _seed_session(client, session_store)
    assert _post(client).status_code == 200
    assert _RecordingClient.configured_timeout == settings.search_upstream_timeout_seconds


def test_openapi_documents_dedicated_authenticated_csrf_read_only_post(client):
    operation = client.get("/openapi.json").json()["paths"][SEARCH_URL]["post"]
    assert "Read-only" in operation["description"]
    assert "authenticated" in operation["description"]
    assert "CSRF" in operation["description"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"q", "limit", "cursor"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("search_upstream_timeout_seconds", 0),
        ("search_upstream_timeout_seconds", 31),
        ("search_max_request_bytes", 8_193),
        ("search_max_response_bytes", 4 * 1_024 * 1_024 + 1),
    ],
)
def test_invalid_search_operational_bounds_are_rejected_at_startup(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_production_security_validation_remains_intact():
    settings = Settings(
        deployment_environment="production",
        keycloak_base_url="https://keycloak.example.gov",
        knowledge_graph_base_url="https://knowledge-graph.example.gov",
        oidc_redirect_uri="https://studio.example.gov/auth/callback",
        studio_frontend_url="https://studio.example.gov",
        oidc_client_secret="production-secret",
    )
    validate_runtime_configuration(settings)
