"""Thin async client over Keycloak's OpenID Connect token endpoint.

FEAT-02-1 (Identity Provider Integration): Direct Access Grants for
human-user login. FEAT-02-2: refresh grant. FEAT-02-3 (Sprint 3): OAuth 2.0
Client Credentials grant for service-to-service (M2M) authentication, added
below without changing either Sprint 2 method's behavior or signature. This
module talks to Keycloak using the standard OIDC token endpoint only; it
does not reimplement any authentication logic Keycloak already governs.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from emg_errors import AuthorizationError, UpstreamServiceError

from .config import Settings


@dataclass(frozen=True)
class KeycloakTokenResult:
    """Raw token response from Keycloak, before EMG session issuance.

    `refresh_token` is `None` for Client Credentials grants (FEAT-02-3):
    Keycloak does not issue a refresh token for service-account tokens by
    default, and machine callers are expected to simply request a fresh
    token when the current one nears expiry rather than refresh — there is
    no human present to re-authenticate, so there is nothing a refresh
    token buys over re-requesting with the (already-held) client secret.
    """

    access_token: str
    expires_in: int
    raw_claims: dict[str, object]
    refresh_token: str | None = None


class KeycloakClient:
    """Wraps Keycloak's `/realms/{realm}/protocol/openid-connect/token`
    endpoint for the two grant types Sprint 2 requires."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._token_url = (
            f"{settings.keycloak_base_url}/realms/{settings.keycloak_realm}"
            "/protocol/openid-connect/token"
        )
        self._client = httpx.AsyncClient(
            timeout=settings.keycloak_request_timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def login_with_password(self, username: str, password: str) -> KeycloakTokenResult:
        """Direct Access Grants (Resource Owner Password Credentials).

        Raises:
            AuthorizationError: Keycloak rejected the credentials (401/400
                invalid_grant) — the caller is responsible for audit logging
                this denial (FEAT-02-3 task "wire failed-auth logging").
            UpstreamServiceError: Keycloak was unreachable or returned an
                unexpected error.
        """
        data = {
            "grant_type": "password",
            "client_id": self._settings.keycloak_client_id,
            "client_secret": self._settings.keycloak_client_secret,
            "username": username,
            "password": password,
            "scope": "openid",
        }
        return await self._request_token(data)

    async def refresh(self, refresh_token: str) -> KeycloakTokenResult:
        """Refresh grant. Raises AuthorizationError if the refresh token is
        invalid or expired, UpstreamServiceError on transport/Keycloak
        failure."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self._settings.keycloak_client_id,
            "client_secret": self._settings.keycloak_client_secret,
            "refresh_token": refresh_token,
        }
        return await self._request_token(data)

    async def client_credentials_token(
        self, *, client_id: str, client_secret: str
    ) -> KeycloakTokenResult:
        """OAuth 2.0 Client Credentials grant (FEAT-02-3) — machine-to-machine
        authentication. `client_id`/`client_secret` are the CALLING
        service's own credentials (e.g. Settings.service_client_id/secret),
        never a value this method invents or looks up on the caller's
        behalf — see services/identity/README.md, "Why the identity service
        does not broker M2M tokens."

        Raises:
            AuthorizationError: Keycloak rejected the client_id/secret pair
                (unknown client, disabled client, or wrong secret).
            UpstreamServiceError: Keycloak was unreachable or returned an
                unexpected error.
        """
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        return await self._request_token(data)

    async def _request_token(self, data: dict[str, str]) -> KeycloakTokenResult:
        try:
            response = await self._client.post(
                self._token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError(f"Keycloak token endpoint unreachable: {exc}") from exc

        if response.status_code == 200:
            payload = response.json()
            return KeycloakTokenResult(
                access_token=payload["access_token"],
                refresh_token=payload.get("refresh_token"),
                expires_in=int(payload["expires_in"]),
                raw_claims=payload,
            )

        if response.status_code in (400, 401):
            # Deliberately generic message: never echo the upstream response
            # body, which for a client_credentials failure could restate the
            # client_id (acceptable) but must never risk relaying anything
            # secret-shaped back to a log or API caller (Required Security
            # Controls: "Secret redaction in logs").
            raise AuthorizationError("Keycloak rejected the credentials or token")

        raise UpstreamServiceError(
            f"Keycloak token endpoint returned unexpected status {response.status_code}"
        )
