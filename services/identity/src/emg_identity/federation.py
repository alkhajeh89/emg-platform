"""Identity Federation Readiness (Sprint 3, FEAT-02-4).

"Prepare the Identity Platform for future federation without binding it to
one external directory." This module defines the *shape* of federation
configuration — provider types, enable/disable state, claim/attribute
mapping, group-to-role mapping — and validates it. It does not connect to
any external directory: Keycloak's built-in user federation (LDAP/AD) and
Identity Brokering (external OIDC/SAML) providers are configured
operationally, per deployment, directly in Keycloak — this module gives
services/identity (and, via /federation/health, an operator) a single place
to see and validate what federation is configured/enabled, independent of
which external system is actually in use.

Air-gapped / disconnected deployments (Module 9 §7, ADR-017 §5): set every
external provider's `enabled: false` and keep `local_fallback_enabled: true`
(the default). No code path in this module requires network access to an
external identity provider — `validate_federation_config` and
`load_federation_config` are pure/local, and Sprint 2's local-realm
authentication (`keycloak_client.py`) already satisfies the "local
identity-provider fallback" requirement without any change.
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .redact import redact_mapping

_log = logging.getLogger("emg.identity")


class FederationProviderType(str, Enum):
    """Supported federation provider categories. SAML is included because
    Keycloak (the platform's selected IdP, Engineering Master Plan §4)
    natively supports acting as a SAML Identity Broker — this does not
    introduce any new architecture, it is Keycloak configuration surfaced
    for visibility. All types are "readiness" only: no client library for
    any of these protocols is invoked by this module."""

    LDAP = "ldap"
    ACTIVE_DIRECTORY = "active_directory"
    OIDC_EXTERNAL = "oidc_external"
    SAML = "saml"
    LOCAL = "local"


class ClaimMapping(BaseModel):
    """Maps one external claim/attribute name to the EMG attribute name it
    populates on `emg_auth_client.Principal.attributes` — the same
    dictionary shape Sprint 2's `_claims_to_principal` already populates
    from Keycloak's native claims, so a federated identity produces a
    Principal indistinguishable in shape from a local one."""

    external_claim: str
    emg_attribute: str


class GroupRoleMapping(BaseModel):
    """Maps one external group name to an EMG realm role."""

    external_group: str
    emg_role: str


class FederationProviderConfig(BaseModel):
    name: str
    provider_type: FederationProviderType
    enabled: bool = False
    display_name: str = ""
    # Opaque, provider-specific connection settings (e.g. LDAP bind DN/URL,
    # OIDC discovery URL). Never returned or logged unredacted — see
    # redact.py and the /federation/providers route.
    connection_settings: dict[str, str] = Field(default_factory=dict)
    claim_mappings: list[ClaimMapping] = Field(default_factory=list)
    group_role_mappings: list[GroupRoleMapping] = Field(default_factory=list)

    def redacted_connection_settings(self) -> dict[str, object]:
        return redact_mapping(dict(self.connection_settings))


class FederationConfig(BaseModel):
    providers: list[FederationProviderConfig] = Field(default_factory=list)
    # Air-gapped readiness: local Keycloak realm auth remains available
    # regardless of external provider state. Defaulting True means an
    # empty/missing config file is always safe (Testing Requirements:
    # "Safe handling of missing federation configuration").
    local_fallback_enabled: bool = True


def default_federation_config() -> FederationConfig:
    """The safe default when no configuration file is present: no external
    providers, local Keycloak realm authentication only."""
    return FederationConfig(providers=[], local_fallback_enabled=True)


def load_federation_config(path: Path) -> FederationConfig:
    """Load federation configuration from `path`. Never raises for a
    missing file — falls back to `default_federation_config()` and logs at
    INFO, since "no federation configured" is an entirely normal state
    (e.g. the Lab Prototype and most local development). Malformed YAML or
    a schema violation in a file that DOES exist is still surfaced (fail
    closed on bad configuration, not silently ignored)."""
    if not path.exists():
        _log.info(
            "No federation configuration file at %s — using local-only default",
            path,
        )
        return default_federation_config()

    raw = yaml.safe_load(path.read_text()) or {}
    return FederationConfig.model_validate(raw)


def validate_federation_config(config: FederationConfig) -> list[str]:
    """Return a list of human-readable validation problems (empty list =
    valid). Never raises — callers (e.g. GET /federation/health) decide how
    to surface problems."""
    errors: list[str] = []
    seen_names: set[str] = set()

    for provider in config.providers:
        if provider.name in seen_names:
            errors.append(f"Duplicate provider name '{provider.name}'")
        seen_names.add(provider.name)

        if not provider.enabled:
            continue

        if provider.provider_type is FederationProviderType.LOCAL:
            continue

        if not provider.connection_settings:
            errors.append(
                f"Provider '{provider.name}' ({provider.provider_type.value}) is enabled "
                "but has no connection_settings"
            )

        for mapping in provider.claim_mappings:
            if not mapping.external_claim or not mapping.emg_attribute:
                errors.append(f"Provider '{provider.name}' has an incomplete claim mapping")

        for role_mapping in provider.group_role_mappings:
            if not role_mapping.external_group or not role_mapping.emg_role:
                errors.append(f"Provider '{provider.name}' has an incomplete group-role mapping")

    if not config.local_fallback_enabled and not any(p.enabled for p in config.providers):
        errors.append(
            "local_fallback_enabled is false and no provider is enabled — "
            "no authentication path would be available"
        )

    return errors


def apply_claim_mappings(
    provider: FederationProviderConfig, external_claims: dict[str, str]
) -> dict[str, str]:
    """Project a federated identity's external claims into the
    `Principal.attributes` shape, per the provider's configured
    `claim_mappings`. Unmapped external claims are dropped, not passed
    through — only claims a provider explicitly maps ever reach a
    Principal, keeping unexpected/unvetted external attributes out of the
    platform's authorization-relevant attribute set."""
    result: dict[str, str] = {}
    for mapping in provider.claim_mappings:
        if mapping.external_claim in external_claims:
            result[mapping.emg_attribute] = external_claims[mapping.external_claim]
    return result


def apply_group_role_mappings(
    provider: FederationProviderConfig, external_groups: list[str]
) -> tuple[str, ...]:
    """Project a federated identity's external group memberships into EMG
    realm roles, per the provider's configured `group_role_mappings`."""
    mapping_by_group = {m.external_group: m.emg_role for m in provider.group_role_mappings}
    roles = [mapping_by_group[group] for group in external_groups if group in mapping_by_group]
    return tuple(roles)
