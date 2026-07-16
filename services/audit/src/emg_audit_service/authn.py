"""Inbound service-token authentication for the audit service (Sprint 6).

Consistent with Sprint 3's stated principle that each service validates
inbound machine tokens itself (no shared broker), the audit service verifies
Bearer service tokens independently rather than importing anything from
`services/identity`. The trust path is identical to identity's
`ServiceTokenValidator`: Keycloak-issued RS256 tokens verified against the
realm JWKS, with issuer and audience checks, mapping the token's `azp` to a
recognized service client.

No new roles are invented — the recognized clients and their roles mirror the
existing Keycloak realm seed and identity's SERVICE_REGISTRY exactly
(`service-account`, `svc-identity`, `svc-authorization`, `svc-audit`).

Authorization split (existing roles only):
- **Ingest** (`POST /audit/events`): any recognized EMG service principal may
  submit audit events (identity, authorization, and audit services all
  produce governed-action records).
- **Read** (`GET /audit/events`, `GET /audit/integrity`): restricted to a
  principal holding the `svc-audit` role — the audit-plane reader. Human
  compliance-reporting access is the later full query/reporting feature
  (FEAT-04-4), not Sprint 6.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

import jwt
from emg_errors import AuthorizationError
from fastapi import Depends, Header

from .config import Settings, get_settings

SigningKeyResolver = Callable[[str], object]


@dataclass(frozen=True)
class ServicePrincipal:
    """The authenticated identity of a calling EMG service (never a human)."""

    client_id: str
    service_name: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)


# Recognized service clients — mirrors identity's SERVICE_REGISTRY and the
# Keycloak realm seed. No new roles. New services are registered here as a
# reviewed source change (same posture as Sprint 3).
_RECOGNIZED_CLIENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "emg-svc-identity": ("identity", ("service-account", "svc-identity")),
    "emg-svc-authorization": ("authorization", ("service-account", "svc-authorization")),
    "emg-svc-audit": ("audit", ("service-account", "svc-audit")),
}


class ServiceTokenValidator:
    def __init__(
        self, settings: Settings, *, signing_key_resolver: SigningKeyResolver | None = None
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

    def validate(self, token: str) -> ServicePrincipal:
        """Verify signature, issuer, audience, expiry; map `azp` to a
        recognized service client. Fail-closed: any failure raises
        AuthorizationError."""
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
        if not isinstance(client_id, str) or client_id not in _RECOGNIZED_CLIENTS:
            raise AuthorizationError(f"Unrecognized service client '{client_id}'")

        service_name, roles = _RECOGNIZED_CLIENTS[client_id]
        raw_scope = payload.get("scope", "")
        scopes = tuple(str(raw_scope).split()) if raw_scope else ()
        return ServicePrincipal(
            client_id=client_id, service_name=service_name, roles=roles, scopes=scopes
        )


def _settings_singleton() -> Settings:
    return get_settings()


def settings_dependency() -> Settings:
    return _settings_singleton()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]


def service_token_validator_dependency(settings: SettingsDep) -> ServiceTokenValidator:
    return ServiceTokenValidator(settings)


ServiceTokenValidatorDep = Annotated[
    ServiceTokenValidator, Depends(service_token_validator_dependency)
]


def _principal_from_header(
    validator: ServiceTokenValidator, authorization: str | None
) -> ServicePrincipal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthorizationError("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    return validator.validate(token)


def require_service_principal(
    validator: ServiceTokenValidatorDep,
    authorization: Annotated[str | None, Header()] = None,
) -> ServicePrincipal:
    """Any recognized EMG service principal — used for ingestion."""
    return _principal_from_header(validator, authorization)


def require_audit_reader(
    validator: ServiceTokenValidatorDep,
    authorization: Annotated[str | None, Header()] = None,
) -> ServicePrincipal:
    """A principal holding the `svc-audit` role — used for query/integrity
    (audit-plane read access). Default-deny: anyone without `svc-audit` is
    rejected."""
    principal = _principal_from_header(validator, authorization)
    if "svc-audit" not in principal.roles:
        raise AuthorizationError(
            f"Service client '{principal.client_id}' lacks the 'svc-audit' role required "
            "to read audit records"
        )
    return principal


ServicePrincipalDep = Annotated[ServicePrincipal, Depends(require_service_principal)]
AuditReaderDep = Annotated[ServicePrincipal, Depends(require_audit_reader)]
