"""Thin async client over Keycloak's OpenID Connect token endpoint.

FEAT-02-1 (Identity Provider Integration). This module talks to Keycloak
using the standard OIDC token endpoint only (Direct Access Grants for
human-user login, per docker-compose.yml's local realm import); it does not
reimplement any authentication logic Keycloak already governs. Service
identity / machine-to-machine client-credentials flow is explicitly FEAT-02-3
(Sprint 3) and is not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from emg_errors import AuthorizationError, UpstreamServiceError

from .config import Settings


@dataclass(frozen=True)
class KeycloakTokenResult:
    """Raw token response from Keycloak, before EMG session issuance."""

    access_token: str
    refresh_token: str
    expires_in: int
    raw_claims: dict[str, object]


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
                refresh_token=payload["refresh_token"],
                expires_in=int(payload["expires_in"]),
                raw_claims=payload,
            )

        if response.status_code in (400, 401):
            raise AuthorizationError("Keycloak rejected the credentials or token")

        raise UpstreamServiceError(
            f"Keycloak token endpoint returned unexpected status {response.status_code}"
        )
