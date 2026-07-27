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
    """The authenticated identity of a calling EMG service (never a human).

    `attributes` (ADR-026 Revision 2, Amendment 2, Group D3) mirrors
    `emg_auth_client.Principal.attributes` exactly, and defaults to an empty
    dict so this addition affects no existing construction call site.
    Populated from a dedicated `classification_clearance` JWT claim
    (Group D5) — see `ServiceTokenValidator.validate()` below."""

    client_id: str
    service_name: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)
    attributes: dict[str, str] = field(default_factory=dict)


# Recognized service clients — mirrors identity's SERVICE_REGISTRY and the
# Keycloak realm seed. No new roles. New services are registered here as a
# reviewed source change (same posture as Sprint 3).
_RECOGNIZED_CLIENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "emg-svc-identity": ("identity", ("service-account", "svc-identity")),
    "emg-svc-authorization": ("authorization", ("service-account", "svc-authorization")),
    "emg-svc-audit": ("audit", ("service-account", "svc-audit")),
}


_UNRESOLVED_CLEARANCE_DEFAULT = "UNCLASSIFIED"


def _extract_attributes(payload: dict[str, Any], settings: Settings) -> dict[str, str]:
    """Extract the `classification_clearance` claim into an attributes dict
    (ADR-026 Revision 2, Amendment 2, Group D5), following exactly the
    optional-claim extraction pattern this platform first established for
    `tenant_claim`
    (`services/knowledge-graph/src/emg_knowledge_graph_api/authn.py`) —
    except that, per ADR-026 Revision 2 §8.4, clearance absence is not an
    authentication failure (unlike `tenant_claim`'s required-claim
    behavior): a missing or non-string claim value resolves to the
    platform's lowest clearance, `"UNCLASSIFIED"`, rather than this
    validator rejecting the token outright. The default is applied
    explicitly here (not left as an absent dict key) because
    `PolicyRule.required_attributes`/`required_resource_attributes`
    matching has no "attribute absent" special case — see the identical
    comment in `emg_knowledge_graph_api.authn._extract_attributes`."""
    raw_clearance = payload.get(settings.classification_clearance_claim)
    clearance = (
        raw_clearance
        if isinstance(raw_clearance, str) and raw_clearance
        else _UNRESOLVED_CLEARANCE_DEFAULT
    )
    return {"classification_clearance": clearance}


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
        attributes = _extract_attributes(payload, self._settings)
        return ServicePrincipal(
            client_id=client_id,
            service_name=service_name,
            roles=roles,
            scopes=scopes,
            attributes=attributes,
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


def require_audit_custodian(
    validator: ServiceTokenValidatorDep,
    authorization: Annotated[str | None, Header()] = None,
) -> ServicePrincipal:
    """A principal holding the `svc-audit` role — used for chain-of-custody
    writes (FEAT-04-3). Custody transfers are audit-plane records; recording
    them is least-privilege and service-authenticated, restricted to the
    existing `svc-audit` role (no new role invented). Default-deny."""
    principal = _principal_from_header(validator, authorization)
    if "svc-audit" not in principal.roles:
        raise AuthorizationError(
            f"Service client '{principal.client_id}' lacks the 'svc-audit' role required "
            "to record custody transfers"
        )
    return principal


ServicePrincipalDep = Annotated[ServicePrincipal, Depends(require_service_principal)]
AuditReaderDep = Annotated[ServicePrincipal, Depends(require_audit_reader)]
AuditCustodianDep = Annotated[ServicePrincipal, Depends(require_audit_custodian)]
