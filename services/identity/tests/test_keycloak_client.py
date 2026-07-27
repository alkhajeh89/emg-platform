import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emg_errors import AuthorizationError, UpstreamServiceError
from emg_identity.keycloak_client import KeycloakClient


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _access_token(settings, private_key, *, exp_delta=300, **extra_claims) -> str:
    """Mint a real, signed RS256 access token — the shape a live Keycloak
    would actually issue, unlike a bare placeholder string. Group D Phase 1
    Remediation (Blocking Fix 1): KeycloakClient now decodes and verifies
    this token via JWKS rather than trusting the token endpoint's own
    top-level JSON response, so these tests must mint a real token for the
    claims (`realm_access`, `classification_clearance`, `department`) to be
    reachable at all."""
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + exp_delta,
        "iss": settings.keycloak_issuer,
        "sub": "dev.investigator",
        **extra_claims,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def _client_with_handler(settings, handler, *, public_key=None) -> KeycloakClient:
    transport = httpx.MockTransport(handler)
    resolver = (lambda token: public_key) if public_key is not None else None
    return KeycloakClient(settings, transport=transport, signing_key_resolver=resolver)


@pytest.mark.asyncio
async def test_login_with_password_success(settings, rsa_keypair):
    private_key, public_key = rsa_keypair
    access_token = _access_token(
        settings, private_key, realm_access={"roles": ["platform-user", "investigator"]}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/protocol/openid-connect/token")
        body = request.read().decode()
        assert "grant_type=password" in body
        return httpx.Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": "kc-refresh-token",
                "expires_in": 300,
            },
        )

    client = _client_with_handler(settings, handler, public_key=public_key)
    result = await client.login_with_password("dev.investigator", "dev_local_password_only")
    assert result.access_token == access_token
    assert result.refresh_token == "kc-refresh-token"
    assert result.expires_in == 300
    # The token endpoint's own top-level JSON never carries realm_access —
    # raw_claims (kept, unchanged) reflects that; verified_claims is where
    # the actual decoded token claims now live.
    assert "realm_access" not in result.raw_claims
    assert result.verified_claims["realm_access"]["roles"] == ["platform-user", "investigator"]
    await client.aclose()


@pytest.mark.asyncio
async def test_login_with_password_rejects_tampered_access_token(settings, rsa_keypair):
    """Defense-in-depth: even though Keycloak itself always signs
    legitimately, KeycloakClient must not blindly trust a 200 response's
    access_token — a corrupted signature is rejected exactly like
    ServiceTokenValidator rejects a tampered machine token."""
    private_key, public_key = rsa_keypair
    access_token = _access_token(settings, private_key)
    header_b64, payload_b64, signature_b64 = access_token.split(".")
    mid = len(signature_b64) // 2
    corrupted_char = "A" if signature_b64[mid] != "A" else "B"
    tampered_signature = signature_b64[:mid] + corrupted_char + signature_b64[mid + 1 :]
    tampered = f"{header_b64}.{payload_b64}.{tampered_signature}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": tampered, "refresh_token": "r", "expires_in": 300}
        )

    client = _client_with_handler(settings, handler, public_key=public_key)
    with pytest.raises(AuthorizationError):
        await client.login_with_password("dev.investigator", "dev_local_password_only")
    await client.aclose()


@pytest.mark.asyncio
async def test_refresh_returns_verified_claims(settings, rsa_keypair):
    """The Keycloak refresh grant is also a human-token-acquisition path and
    must be verified identically to login_with_password."""
    private_key, public_key = rsa_keypair
    access_token = _access_token(settings, private_key, realm_access={"roles": ["platform-user"]})

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "grant_type=refresh_token" in body
        return httpx.Response(
            200,
            json={"access_token": access_token, "refresh_token": "new-refresh", "expires_in": 300},
        )

    client = _client_with_handler(settings, handler, public_key=public_key)
    result = await client.refresh("some-refresh-token")
    assert result.verified_claims["realm_access"]["roles"] == ["platform-user"]
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
