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
from emg_auth_client import Principal
from emg_common_types import normalize_classification_clearance
from emg_errors import AuthorizationError
from emg_platform_core import TenantId
from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError as _PydanticValidationError

from .config import Settings, get_settings

SigningKeyResolver = Callable[[str], object]

_BEARER_AUTH = HTTPBearer(
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description="Service bearer token issued by the configured identity provider.",
    auto_error=False,
)
BearerCredentialsDep = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(_BEARER_AUTH),
]

_RECOGNIZED_CLIENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "emg-svc-identity": ("identity", ("service-account", "svc-identity")),
    "emg-svc-authorization": (
        "authorization",
        ("service-account", "svc-authorization"),
    ),
    "emg-svc-audit": ("audit", ("service-account", "svc-audit")),
    "emg-svc-knowledge-graph-writer": (
        "knowledge-graph-writer",
        ("service-account", "svc-knowledge-graph-writer"),
    ),
}


@dataclass(frozen=True)
class ServicePrincipal:
    """The authenticated identity of a calling EMG service (never a human).
    Structurally identical to `emg_audit_service.authn.ServicePrincipal` /
    `emg_identity.service_principal.ServicePrincipal` — deliberately not
    imported from either (per the "each service validates independently"
    convention those modules themselves document).

    `service_name` (ADR-025 Group C, discovered during implementation): both
    sibling `ServicePrincipal` types already carry this field, because it is
    required by `emg_auth_client.ServicePrincipalLike` — the structural
    Protocol `AuthorizationRequest.principal` is typed against. This type
    was missing it (a pre-existing Sprint 7.4 gap, never caught before
    because nothing in this service called into `emg_auth_client`/
    `emg_policy_engine` until this ADR). SRS-2 applies the same reviewed
    client allow-list and required-role contract used by Identity and Audit,
    so `service_name` is resolved from the verified client identifier rather
    than accepted from token-controlled content.

    `attributes` (ADR-026 Revision 2, Amendment 2, Group D3): mirrors
    `emg_auth_client.Principal.attributes` exactly, closing the asymmetry
    between human and machine identity types. Defaults to an empty dict, so
    this addition affects no existing construction call site. Populated from
    a dedicated `classification_clearance` JWT claim (Group D5), extracted
    the same way this module already extracts `tenant_claim` below — see
    `TenantServiceTokenValidator.validate()`."""

    client_id: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    scopes: tuple[str, ...] = field(default_factory=tuple)
    service_name: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CallerContext:
    """The authenticated caller plus the tenant their token resolves to —
    the one object routers depend on for both "who" and "which tenant".

    `acting_service` (Phase 2B, ADR-038 §8.3): the authenticated Acting
    Service's client id when this context was resolved from a Delegated
    Credential (`DelegatedCredentialValidator`), `None` for the existing
    plain service-to-service path (`TenantServiceTokenValidator`). Additive
    — every pre-existing `CallerContext(...)` construction call site is
    unchanged, since the default preserves prior behavior exactly. Per
    ADR-038 §8.2/§8.3, the Acting Service is carried here for audit
    attribution ONLY; it is never the authorization subject and is never
    read by `require_permission`/the PEP."""

    principal: ServicePrincipal | Principal
    tenant: TenantId
    acting_service: str | None = None


def _settings_singleton() -> Settings:
    return get_settings()


def settings_dependency() -> Settings:
    return _settings_singleton()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]


def _extract_attributes(payload: dict[str, Any], settings: Settings) -> dict[str, str]:
    """Extract the `classification_clearance` claim into an attributes dict
    (ADR-026 Revision 2, Amendment 2, Group D5) — the same optional-claim
    convention as `tenant_claim` just above, except that clearance absence is
    not an authentication failure (ADR-026 Revision 2 §8.4): a missing,
    non-string, or unrecognized claim value resolves to the platform's
    lowest clearance, `"UNCLASSIFIED"`, rather than this validator rejecting
    the token outright (ADR-026 final blocker fix: an unrecognized string,
    e.g. `"banana"`, previously survived unchanged instead of resolving to
    `"UNCLASSIFIED"`). The default is applied explicitly here — not left as
    an absent dict key — because `PolicyRule.required_attributes`/
    `required_resource_attributes` matching (`emg_policy_engine.engine`) has
    no "attribute absent" special case: an absent key simply fails every
    allow-list match, which would satisfy neither an allow rule requiring a
    specific clearance nor a deny rule keyed on the literal value
    `"UNCLASSIFIED"`. Resolving the default here, once, keeps that matching
    logic itself generic and declarative (ADR-026A principle 1) rather than
    teaching it a classification-specific "no value means lowest tier"
    rule. Validation itself is delegated to the shared
    `emg_common_types.normalize_classification_clearance` helper so this
    check is not duplicated across services."""
    raw_clearance = payload.get(settings.classification_clearance_claim)
    clearance = normalize_classification_clearance(raw_clearance)
    return {"classification_clearance": clearance}


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
        if not isinstance(client_id, str) or client_id not in _RECOGNIZED_CLIENTS:
            raise AuthorizationError(f"Unrecognized service client '{client_id}'")
        service_name, required_roles = _RECOGNIZED_CLIENTS[client_id]

        raw_scope = payload.get("scope", "")
        scopes = tuple(str(raw_scope).split()) if raw_scope else ()
        realm_access = payload.get("realm_access")
        raw_roles = realm_access.get("roles", ()) if isinstance(realm_access, dict) else ()
        roles = tuple(str(role) for role in raw_roles) if isinstance(raw_roles, list) else ()
        if not set(required_roles).issubset(roles):
            raise AuthorizationError(
                f"Service client '{client_id}' token is missing its required registered roles"
            )
        attributes = _extract_attributes(payload, self._settings)
        principal = ServicePrincipal(
            client_id=client_id,
            service_name=service_name,
            roles=roles,
            scopes=scopes,
            attributes=attributes,
        )

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
    credentials: BearerCredentialsDep,
) -> CallerContext:
    """Extract and verify the Bearer token, returning the authenticated
    caller's `CallerContext` (principal + resolved tenant). Raises
    AuthorizationError (mapped to HTTP 401) if the header is missing or
    malformed, the token is invalid, or the token carries no resolvable
    tenant claim — a request can never supply or override its own tenant.

    Unchanged by Phase 2B: mutation routes and any other pre-existing call
    site depend on this exact function via `TenantContextDep` and continue
    to accept only plain service-to-service tokens. Delegated Credentials
    are handled by a separate, additive path below
    (`AuthenticatedCallerDep`) — never by this one."""
    if credentials is None:
        raise AuthorizationError("Missing or malformed Authorization header")
    return validator.validate(credentials.credentials)


TenantContextDep = Annotated[CallerContext, Depends(require_tenant_context)]


# --- Phase 2B: Delegated Credential validation (ADR-038) -------------------
#
# Additive. Every symbol above this line, and every existing caller of
# `TenantContextDep`/`TenantServiceTokenValidator`, is unchanged.

# Client ids recognized as Acting Services (ADR-038 Trust Domain B) — a
# category distinct from `_RECOGNIZED_CLIENTS` above (plain service-to-
# service callers). Per-service, not a shared library, matching this
# module's existing "each service validates independently" convention.
_RECOGNIZED_ACTING_SERVICES: frozenset[str] = frozenset({"emg-studio-bff"})


class DelegatedCredentialValidator:
    """Independently validates a Delegated Credential (ADR-038 §7.6 / AC-9)
    and constructs a `CallerContext` whose `principal` is the delegated
    HUMAN Principal — never the Acting Service (ADR-038 §8.2: "The Acting
    Service SHALL never become the authorization subject").

    Trust path identical in shape to `TenantServiceTokenValidator`: RS256
    verified against the realm JWKS, issuer checked. The audience checked
    is `settings.delegated_credential_audience` — THIS service's own,
    single, isolated audience (ADR-038 §7.4 Audience Restriction) — not
    `settings.service_token_audience`, which remains exclusively the plain
    service-to-service audience.
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
        """Fail-closed: any failure raises AuthorizationError. In
        particular, a missing/blank `sub` is a hard failure — this
        validator never silently proceeds with an empty or synthetic
        subject (Phase 2B Required Configuration #1 / capability
        verification Finding 2)."""
        try:
            signing_key = self._signing_key_resolver(token)
            payload = jwt.decode(
                token,
                cast(Any, signing_key),
                algorithms=["RS256"],
                issuer=self._settings.keycloak_issuer,
                audience=self._settings.delegated_credential_audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthorizationError(f"Invalid delegated credential: {exc}") from exc

        # ADR-038 §7.4 "exactly one downstream audience": PyJWT's own
        # `audience=` check above only confirms the expected value is a
        # MEMBER of `aud` — it does not reject a token whose `aud` also
        # names other audiences. This closes that gap explicitly.
        raw_aud = payload.get("aud")
        aud_values = raw_aud if isinstance(raw_aud, list) else [raw_aud]
        if len(aud_values) != 1 or aud_values[0] != self._settings.delegated_credential_audience:
            raise AuthorizationError(
                "Delegated credential must be issued for exactly one downstream audience"
            )

        acting_service = payload.get("azp") or payload.get("client_id")
        if not isinstance(acting_service, str) or acting_service not in _RECOGNIZED_ACTING_SERVICES:
            raise AuthorizationError(f"Unrecognized Acting Service '{acting_service}'")

        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthorizationError("Delegated credential is missing the human subject claim")

        realm_access = payload.get("realm_access")
        raw_roles = realm_access.get("roles", ()) if isinstance(realm_access, dict) else ()
        roles = tuple(str(role) for role in raw_roles) if isinstance(raw_roles, list) else ()

        attributes = _extract_attributes(payload, self._settings)
        principal = Principal(subject=subject, roles=roles, attributes=attributes)

        tenant_claim_value = payload.get(self._settings.tenant_claim)
        if not isinstance(tenant_claim_value, str) or not tenant_claim_value:
            raise AuthorizationError(
                "Delegated credential is missing the required "
                f"'{self._settings.tenant_claim}' claim"
            )
        try:
            tenant = TenantId.of(tenant_claim_value)
        except _PydanticValidationError as exc:
            raise AuthorizationError(
                f"Delegated credential's '{self._settings.tenant_claim}' claim is not a valid "
                f"tenant identifier: {exc}"
            ) from exc

        return CallerContext(principal=principal, tenant=tenant, acting_service=acting_service)


def delegated_credential_validator_dependency(
    settings: SettingsDep,
) -> DelegatedCredentialValidator:
    return DelegatedCredentialValidator(settings)


DelegatedCredentialValidatorDep = Annotated[
    DelegatedCredentialValidator, Depends(delegated_credential_validator_dependency)
]


def _peek_acting_service_client_id(token: str) -> str | None:
    """Unverified peek at `azp`/`client_id`, used ONLY to decide which
    validator to run next — never to trust anything. Whichever validator is
    selected performs full cryptographic verification before any claim
    from this peek is relied upon."""
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    value = payload.get("azp") or payload.get("client_id")
    return value if isinstance(value, str) else None


def require_authenticated_caller(
    credentials: BearerCredentialsDep,
    tenant_validator: TenantValidatorDep,
    delegated_validator: DelegatedCredentialValidatorDep,
) -> CallerContext:
    """Combined dependency for routes that accept EITHER a plain service
    token OR a Delegated Credential (Phase 2B: the read routes only —
    mutation routes continue to depend on `TenantContextDep`/
    `require_tenant_context` exclusively, unchanged).

    Selection is by the token's own `azp`: a recognized Acting Service
    (`_RECOGNIZED_ACTING_SERVICES`) routes to `DelegatedCredentialValidator`;
    every other case falls back to the exact same `TenantServiceTokenValidator`
    instance/logic the service-to-service path already used before Phase 2B
    — behaviorally identical for every existing caller."""
    if credentials is None:
        raise AuthorizationError("Missing or malformed Authorization header")
    token = credentials.credentials
    azp = _peek_acting_service_client_id(token)
    if azp in _RECOGNIZED_ACTING_SERVICES:
        return delegated_validator.validate(token)
    return tenant_validator.validate(token)


AuthenticatedCallerDep = Annotated[CallerContext, Depends(require_authenticated_caller)]
