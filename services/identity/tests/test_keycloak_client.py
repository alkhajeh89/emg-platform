import httpx
import pytest
from emg_errors import AuthorizationError, UpstreamServiceError
from emg_identity.keycloak_client import KeycloakClient


def _client_with_handler(settings, handler) -> KeycloakClient:
    transport = httpx.MockTransport(handler)
    return KeycloakClient(settings, transport=transport)


@pytest.mark.asyncio
async def test_login_with_password_success(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/protocol/openid-connect/token")
        body = request.read().decode()
        assert "grant_type=password" in body
        return httpx.Response(
            200,
            json={
                "access_token": "kc-access-token",
                "refresh_token": "kc-refresh-token",
                "expires_in": 300,
                "realm_access": {"roles": ["platform-user", "investigator"]},
            },
        )

    client = _client_with_handler(settings, handler)
    result = await client.login_with_password("dev.investigator", "dev_local_password_only")
    assert result.access_token == "kc-access-token"
    assert result.refresh_token == "kc-refresh-token"
    assert result.expires_in == 300
    assert result.raw_claims["realm_access"]["roles"] == ["platform-user", "investigator"]
    await client.aclose()


@pytest.mark.asyncio
async def test_login_with_password_invalid_credentials_raises_authorization_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_grant"})

    client = _client_with_handler(settings, handler)
    with pytest.raises(AuthorizationError):
        await client.login_with_password("dev.investigator", "wrong-password")
    await client.aclose()


@pytest.mark.asyncio
async def test_login_upstream_failure_raises_upstream_service_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = _client_with_handler(settings, handler)
    with pytest.raises(UpstreamServiceError):
        await client.login_with_password("dev.investigator", "dev_local_password_only")
    await client.aclose()


@pytest.mark.asyncio
async def test_login_transport_error_raises_upstream_service_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client_with_handler(settings, handler)
    with pytest.raises(UpstreamServiceError):
        await client.login_with_password("dev.investigator", "dev_local_password_only")
    await client.aclose()


@pytest.mark.asyncio
async def test_refresh_success(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "grant_type=refresh_token" in body
        return httpx.Response(
            200,
            json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 300},
        )

    client = _client_with_handler(settings, handler)
    result = await client.refresh("some-refresh-token")
    assert result.access_token == "new-access"
    await client.aclose()


@pytest.mark.asyncio
async def test_refresh_invalid_token_raises_authorization_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = _client_with_handler(settings, handler)
    with pytest.raises(AuthorizationError):
        await client.refresh("expired-refresh-token")
    await client.aclose()


# --- Sprint 3: Client Credentials (M2M) grant, FEAT-02-3 -------------------


@pytest.mark.asyncio
async def test_client_credentials_token_success(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/protocol/openid-connect/token")
        body = request.read().decode()
        assert "grant_type=client_credentials" in body
        assert "client_id=emg-svc-authorization" in body
        return httpx.Response(
            200,
            json={
                "access_token": "kc-service-access-token",
                "expires_in": 300,
                "azp": "emg-svc-authorization",
                "scope": "svc-authorization",
            },
        )

    client = _client_with_handler(settings, handler)
    result = await client.client_credentials_token(
        client_id="emg-svc-authorization", client_secret="a-service-secret"
    )
    assert result.access_token == "kc-service-access-token"
    assert result.expires_in == 300
    # Client Credentials grants never issue a refresh token (see
    # KeycloakTokenResult's docstring).
    assert result.refresh_token is None
    await client.aclose()


@pytest.mark.asyncio
async def test_client_credentials_invalid_client_id_raises_authorization_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized_client"})

    client = _client_with_handler(settings, handler)
    with pytest.raises(AuthorizationError):
        await client.client_credentials_token(
            client_id="not-a-real-client", client_secret="whatever"
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_client_credentials_invalid_secret_raises_authorization_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    client = _client_with_handler(settings, handler)
    with pytest.raises(AuthorizationError):
        await client.client_credentials_token(
            client_id="emg-svc-authorization", client_secret="wrong-secret"
        )
    await client.aclose()
