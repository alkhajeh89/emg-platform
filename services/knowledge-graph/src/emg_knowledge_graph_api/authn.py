"""Inbound authentication and tenant-context resolution for the Knowledge
Graph Query API (Sprint 7.4).

**Architectural note — read before extending.** No existing service in this
repository has an authenticated tenant-context mechanism today:
`services/audit` and `services/identity` authenticate a *caller* (a human
`Principal` or a machine `ServicePrincipal`), but neither type carries a
tenant claim anywhere in the codebase, and no router in any service extracts
a tenant identifier from a request. `emg_knowledge_graph`'s own
`GraphQueryScope`/`GraphStore`/`GraphRevisionReader` are already
tenant-scoped (`TenantId`), but until this sprint nothing in the platform
exposed that scoping over HTTP. This module is therefore the **first**
tenant-context mechanism in the platform, not a reuse of an established one.

Given that gap, this module extends the *existing* inbound-authentication
convention (`services/audit/src/emg_audit_service/authn.py`'s bearer
service-token / JWKS-verified RS256 pattern — copied here per that module's
own documented principle that "each service validates inbound machine
tokens itself, no shared broker") with one new, minimal addition: a
`tenant_claim` (default `"tenant_id"`) read from the verified JWT payload,
identical in spirit to how audit already reads a `scope` custom claim from
the same payload. A request whose token lacks a resolvable tenant claim is
rejected (`AuthorizationError`, mapped to 401) — the tenant is never taken
from a client-controlled query parameter, so a caller can never name a
tenant other than the one their own verified token carries.

This is a deliberate, minimal, clearly-flagged Sprint 7.4 addition, not a
platform-wide decision — see the Sprint 7.4 final report's "architectural
ambiguity" item for the follow-up this should receive (e.g. ratifying
`tenant_id` as the platform's standard claim name via a short ADR, once a
second tenant-scoped HTTP surface exists to confirm the convention).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

import jwt
from emg_errors import AuthorizationError
from emg_platform_core import TenantId
from fastapi import Depends, Header
from pydantic import ValidationError as _PydanticValidationError

from .config import Settings, get_settings

SigningKeyResolver = Callable[[str], object]


@dataclass(frozen=True)
class ServicePrincipal:
    """The authenticated identity of a calling EMG service (never a human).
    Structurally identical to `emg_audit_service.authn.ServicePrincipal` /
    `emg_identity.service_principal.ServicePrincipal` — deliberately not
    imported from either (per the "each service validates independently"
    convention those modules themselves document)."""

    client_id: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CallerContext:
    """The authenticated caller plus the tenant their token resolves to —
    the one object routers depend on for both "who" and "which tenant"."""

    principal: ServicePrincipal
    tenant: TenantId


def _settings_singleton() -> Settings:
    return get_settings()


def settings_dependency() -> Settings:
    return _settings_singleton()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]


class TenantServiceTokenValidator:
    """Verifies a Bearer service token and resolves the caller's tenant.

    Trust path identical to `emg_audit_service.authn.ServiceTokenValidator`:
    RS256 tokens verified against the realm JWKS, with issuer/audience
    checks. Additionally requires and extracts `settings.tenant_claim`.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        signing_key_resolver: SigningKeyResolver | None = None,
    ) -> None:
        self._settings = settings
        self._signing_key_resolver = signing_key_resolver or self._default_signing_key_resolver
        self._jwks_client: jwt.PyJWKClient | None = None

    def _default_signing_key_resolver(self, token: str) -> object:  # pragma: no cover - network
        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(
                self._settings.jwks_uri, lifespan=self._settings.jwks_cache_ttl_seconds
            )
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def validate(self, token: str) -> CallerContext:
        """Verify signature, issuer, audience, expiry, and resolve the
        tenant claim. Fail-closed: any failure raises AuthorizationError —
        never a persistence or JWT library exception, and never a
        stack-trace-bearing response."""
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
        if not isinstance(client_id, str) or not client_id:
            raise AuthorizationError("Service token is missing a client identifier")

        raw_scope = payload.get("scope", "")
        scopes = tuple(str(raw_scope).split()) if raw_scope else ()
        raw_roles = payload.get("roles", ())
        roles = tuple(raw_roles) if isinstance(raw_roles, list | tuple) else ()
        principal = ServicePrincipal(client_id=client_id, roles=roles, scopes=scopes)

        tenant_claim_value = payload.get(self._settings.tenant_claim)
        if not isinstance(tenant_claim_value, str) or not tenant_claim_value:
            raise AuthorizationError(
                f"Service token is missing the required '{self._settings.tenant_claim}' claim"
            )
        try:
            tenant = TenantId.of(tenant_claim_value)
        except _PydanticValidationError as exc:
            raise AuthorizationError(
                f"Service token's '{self._settings.tenant_claim}' claim is not a valid tenant "
                f"identifier: {exc}"
            ) from exc

        return CallerContext(principal=principal, tenant=tenant)


def tenant_validator_dependency(settings: SettingsDep) -> TenantServiceTokenValidator:
    return TenantServiceTokenValidator(settings)


TenantValidatorDep = Annotated[TenantServiceTokenValidator, Depends(tenant_validator_dependency)]


def require_tenant_context(
    validator: TenantValidatorDep,
    authorization: Annotated[str | None, Header()] = None,
) -> CallerContext:
    """Extract and verify the Bearer token, returning the authenticated
    caller's `CallerContext` (principal + resolved tenant). Raises
    AuthorizationError (mapped to HTTP 401) if the header is missing or
    malformed, the token is invalid, or the token carries no resolvable
    tenant claim — a request can never supply or override its own tenant."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthorizationError("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    return validator.validate(token)


TenantContextDep = Annotated[CallerContext, Depends(require_tenant_context)]
