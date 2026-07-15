"""Validates Keycloak-issued OAuth 2.0 Client Credentials (M2M) access
tokens for incoming service-to-service calls (Sprint 3, FEAT-02-3).

Design (see services/identity/README.md for the full rationale):

- Service tokens are RS256, signed by Keycloak's realm key, fetched via the
  realm's JWKS endpoint (`Settings.jwks_uri`) — a completely different trust
  path from the HS256 EMG session tokens `session.py` issues for humans.
  This is what makes "reject a human token presented where a service token
  is required" (and vice versa) a structural guarantee rather than a flag
  check: the algorithms don't match, so `jwt.decode` rejects the token
  before any claim is even inspected.
- Fail-closed: every failure mode (bad signature, wrong issuer, wrong
  audience, expired, not-yet-valid, unrecognized client, missing scope)
  raises `emg_errors.AuthorizationError` — there is no code path that
  returns a "partially trusted" principal.
- `signing_key_resolver` is injectable so tests can validate against a
  locally-generated RSA keypair without a live Keycloak/JWKS endpoint
  (services/identity/tests/test_service_token_validator.py); production
  defaults to `jwt.PyJWKClient`, which fetches and caches Keycloak's real
  JWKS.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import jwt
from emg_errors import AuthorizationError

from .config import Settings
from .service_principal import ServicePrincipal
from .service_registry import SERVICE_REGISTRY

SigningKeyResolver = Callable[[str], object]


class ServiceTokenValidator:
    def __init__(
        self, settings: Settings, *, signing_key_resolver: SigningKeyResolver | None = None
    ) -> None:
        self._settings = settings
        self._signing_key_resolver = signing_key_resolver or self._default_signing_key_resolver
        self._jwks_client: jwt.PyJWKClient | None = None

    def _default_signing_key_resolver(self, token: str) -> object:
        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(
                self._settings.jwks_uri, lifespan=self._settings.jwks_cache_ttl_seconds
            )
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def validate(self, token: str, *, required_scope: str | None = None) -> ServicePrincipal:
        """Verify signature, issuer, audience, and expiry; map the token's
        `azp` (authorized party) to a registered `ServicePrincipal`.

        Raises AuthorizationError on any validation failure, including an
        unrecognized (unregistered) client or a missing required scope.
        """
        try:
            signing_key = self._signing_key_resolver(token)
            payload = jwt.decode(
                token,
                cast(Any, signing_key),
                algorithms=["RS256"],
                issuer=self._settings.keycloak_issuer,
                audience=self._settings.service_token_audience,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthorizationError(f"Invalid service token: {exc}") from exc

        client_id = payload.get("azp") or payload.get("client_id")
        if not isinstance(client_id, str) or client_id not in SERVICE_REGISTRY:
            raise AuthorizationError(f"Unrecognized service client '{client_id}'")

        entry = SERVICE_REGISTRY[client_id]
        raw_scope = payload.get("scope", "")
        scopes = tuple(str(raw_scope).split()) if raw_scope else ()

        scope_satisfied = (
            required_scope is None
            or required_scope in scopes
            or required_scope in entry.roles
        )
        if not scope_satisfied:
            raise AuthorizationError(
                f"Service client '{client_id}' is missing required scope '{required_scope}'"
            )

        return ServicePrincipal(
            client_id=client_id,
            service_name=entry.service_name,
            roles=entry.roles,
            scopes=scopes,
        )
