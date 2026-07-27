"""Thin async client over Keycloak's OpenID Connect token endpoint.

FEAT-02-1 (Identity Provider Integration): Direct Access Grants for
human-user login. FEAT-02-2: refresh grant. FEAT-02-3 (Sprint 3): OAuth 2.0
Client Credentials grant for service-to-service (M2M) authentication, added
below without changing either Sprint 2 method's behavior or signature. This
module talks to Keycloak using the standard OIDC token endpoint only; it
does not reimplement any authentication logic Keycloak already governs.

**Group D Phase 1 Remediation (Blocking Fix 1, 2026-07-27):** the token
endpoint's own JSON response (`access_token`, `expires_in`, `refresh_token`,
`token_type`, ...) is not the decoded claims of the access token — it never
carries `realm_access`, `classification_clearance`, or `department`; those
are claims *inside* the signed `access_token` JWT itself. Prior to this fix,
`_request_token` assigned that top-level response directly as `raw_claims`,
so `routers/auth.py`'s `_claims_to_principal` was reading fields that were
never actually present on it (roles and ABAC attributes were silently
always absent for real Keycloak responses). This module now decodes and
verifies the human-grant access token via the realm's JWKS endpoint — the
same trusted RS256/JWKS path `ServiceTokenValidator`
(`service_token_validator.py`) already uses for machine tokens — and
exposes the result as `KeycloakTokenResult.verified_claims`, a field
distinct from `raw_claims` so the Client Credentials (M2M) grant's
contract, which nothing downstream reads claims from, is completely
unaffected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import jwt
from emg_errors import AuthorizationError, UpstreamServiceError

from .config import Settings

SigningKeyResolver = Callable[[str], object]


@dataclass(frozen=True)
class KeycloakTokenResult:
    """Raw token response from Keycloak, before EMG session issuance.

    `refresh_token` is `None` for Client Credentials grants (FEAT-02-3):
    Keycloak does not issue a refresh token for service-account tokens by
    default, and machine callers are expected to simply request a fresh
    token when the current one nears expiry rather than refresh — there is
    no human present to re-authenticate, so there is nothing a refresh
    token buys over re-requesting with the (already-held) client secret.

    `verified_claims` (Group D Phase 1 Remediation): the *verified*,
    decoded claims of `access_token` itself — populated only for the two
    human grants (`login_with_password`, `refresh`); left as an empty dict
    for `client_credentials_token`, whose result nothing downstream reads
    claims from (machine tokens are independently re-verified by each
    service's own `ServiceTokenValidator` when presented inbound). This is
    deliberately a separate field from `raw_claims` (kept, unchanged, as the
    token endpoint's own top-level JSON) rather than a repurposing of it, so
    nothing that already reads `raw_claims` for the M2M grant is disturbed.
    """

    access_token: str
    expires_in: int
    raw_claims: dict[str, object]
    refresh_token: str | None = None
    verified_claims: dict[str, object] = field(default_factory=dict)


class KeycloakClient:
    """Wraps Keycloak's `/realms/{realm}/protocol/openid-connect/token`
    endpoint for the two grant types Sprint 2 requires."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        signing_key_resolver: SigningKeyResolver | None = None,
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
        self._signing_key_resolver = signing_key_resolver or self._default_signing_key_resolver
        self._jwks_client: jwt.PyJWKClient | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    def _default_signing_key_resolver(self, token: str) -> object:  # pragma: no cover - network
        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(
                self._settings.jwks_uri, lifespan=self._settings.jwks_cache_ttl_seconds
            )
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def _verify_access_token_claims(self, access_token: str) -> dict[str, object]:
        """Decode and verify a Keycloak-issued human access token via the
        realm's JWKS endpoint — the same trusted RS256/JWKS verification
        path `ServiceTokenValidator` uses for machine tokens
        (`service_token_validator.py`), applied here so
        `routers/auth.py`'s `_claims_to_principal` reads genuinely verified
        claims (`realm_access`, `classification_clearance`, `department`)
        rather than the token endpoint's own top-level JSON response.

        Audience is deliberately not asserted here (`verify_aud=False`):
        unlike machine tokens (`Settings.service_token_audience`, a fixed,
        platform-owned convention already enforced by
        `ServiceTokenValidator`), this repository has no established
        audience convention for human access tokens, and inventing one is
        out of this fix's scope — see the Keycloak realm seed's
        `emg-identity-service` client, which (unlike the service-account
        clients) carries no dedicated audience-mapper client scope.
        Signature, issuer, and expiry are still fully verified: the token
        cannot be forged, cannot be issued by a different realm, and cannot
        be replayed past expiry.
        """
        try:
            signing_key = self._signing_key_resolver(access_token)
            return jwt.decode(
                access_token,
                cast(Any, signing_key),
                algorithms=["RS256"],
                issuer=self._settings.keycloak_issuer,
                options={"require": ["exp", "iat", "iss"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise AuthorizationError(f"Invalid Keycloak access token: {exc}") from exc

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
        return await self._request_token(data, verify_claims=True)

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
        return await self._request_token(data, verify_claims=True)

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

    async def _request_token(
        self, data: dict[str, str], *, verify_claims: bool = False
    ) -> KeycloakTokenResult:
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
            access_token = payload["access_token"]
            verified_claims = (
                self._verify_access_token_claims(access_token) if verify_claims else {}
            )
            return KeycloakTokenResult(
                access_token=access_token,
                refresh_token=payload.get("refresh_token"),
                expires_in=int(payload["expires_in"]),
                raw_claims=payload,
                verified_claims=verified_claims,
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
