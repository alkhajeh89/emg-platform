# Identity Federation Readiness Guide

Sprint 3 (FEAT-02-4, Identity Federation Readiness). This document explains
what is actually implemented this sprint, what is deliberately deferred to
per-environment operational configuration, and how to reason about
air-gapped/disconnected deployments.

## What "readiness" means here

FEAT-02-4 prepares the Identity Platform to be federated with external
identity sources **without binding it to any one of them**. It does this by
defining, in `services/identity/src/emg_identity/federation.py`:

- A provider-type-agnostic configuration shape (`FederationProviderConfig`)
  covering LDAP, Active Directory, external OIDC, and SAML, each with an
  `enabled` flag, opaque `connection_settings`, and claim/group mapping
  rules.
- Pure, local validation (`validate_federation_config`) and safe config
  loading (`load_federation_config`) — neither function makes a network
  call or imports a protocol client library for any of these providers.
- Two read-only HTTP endpoints (`GET /federation/providers`,
  `GET /federation/health`) so an operator can see what is configured and
  whether it validates, with secret-shaped connection settings always
  redacted (see `docs/engineering/security-limitations.md`).

## What is implemented now vs. environment-specific

| Concern | Implemented this sprint | Deferred (environment-specific) |
| --- | --- | --- |
| Configuration schema, validation, claim/group mapping projection | Yes — `federation.py`, unit-tested | — |
| Visibility endpoints (`/federation/providers`, `/federation/health`) | Yes | — |
| Actually connecting to an LDAP/AD server | No | Keycloak's built-in User Federation (LDAP/Kerberos) provider, configured per deployment directly in Keycloak's admin console/API |
| Actually brokering an external OIDC or SAML IdP | No | Keycloak's Identity Brokering, configured per deployment the same way |
| Populating `connection_settings` with real directory URLs/credentials | No | Operator-authored `federation.yaml` (copy of `federation.example.yaml`), with secrets sourced from the centralized secrets store, never committed |
| Government/production directory connectivity | Explicitly not implemented — out of scope for this sprint by direct instruction | A future sprint, once a real target directory is designated |

This module gives services/identity (and an operator, via the health
endpoint) a single place to see and validate what federation is
configured/enabled, **independent of which external system is actually in
use** — the actual protocol handling for LDAP/AD/OIDC/SAML is Keycloak's,
per Engineering Master Plan §4's platform selection, not reimplemented here.

## Configuring a provider (example)

Copy `services/identity/config/federation.example.yaml` to the path
`Settings.federation_config_path` points at (default:
`services/identity/config/federation.example.yaml` itself, for local
development — override via `EMG_IDENTITY_FEDERATION_CONFIG_PATH` per
environment) and edit it. Every provider in the example ships
`enabled: false`; enabling one is an explicit, reviewed operational change:

```yaml
providers:
  - name: corp-ldap
    provider_type: ldap
    enabled: true
    display_name: "Corporate LDAP"
    connection_settings:
      url: "ldaps://ldap.example.internal"
      bind_dn: "cn=svc-emg,dc=example,dc=internal"
      bind_password: "__set_via_secrets_store__"
    claim_mappings:
      - external_claim: "clearance"
        emg_attribute: "classification_clearance"
      - external_claim: "dept"
        emg_attribute: "department"
    group_role_mappings:
      - external_group: "Investigators"
        emg_role: "investigator"
local_fallback_enabled: true
```

`validate_federation_config` will reject this if `enabled: true` and
`connection_settings` is empty, if any claim/group mapping is incomplete, or
if `local_fallback_enabled: false` while no provider is enabled (which would
leave no authentication path available at all — a fail-closed check on the
*configuration*, matching the module's fail-closed posture on tokens).

## Air-gapped and disconnected deployments

Module 9 §7 / ADR-017 §5 scenarios (Lab Prototype, disconnected/classified
environments): set every external provider's `enabled: false` (or omit the
config file entirely — `load_federation_config` falls back safely, logging
at INFO, not raising) and leave `local_fallback_enabled: true` (the
pydantic-model default). No code path in `federation.py` requires network
access to an external identity provider under this configuration.

## Local identity-provider fallback

This requirement is already satisfied without any Sprint 3 code change:
Sprint 2's Keycloak realm authentication
(`keycloak_client.py::login_with_password`, against the local `emg` realm)
is the fallback path, and `FederationConfig.local_fallback_enabled`
defaults to `True` specifically so an empty or missing federation
configuration never disables it.

## Claim and group-to-role mapping strategy

`apply_claim_mappings` and `apply_group_role_mappings` are intentionally
allow-list, not pass-through: only claims/groups a provider's configuration
explicitly maps are ever projected into `Principal.attributes` /
realm-role-equivalent output. An external directory returning extra,
unvetted claims or group memberships does not leak them into EMG's
authorization-relevant attribute set. The target shape
(`classification_clearance`, `department`) matches exactly what Sprint 2's
`_claims_to_principal` already populates from Keycloak's native claims, so a
federated identity produces a `Principal` indistinguishable in shape from a
local one — Module 5's future PEP does not need to know or care which path
authenticated a given user.

## Explicitly not done this sprint

Per the user's direct instruction: no connection to a real government
directory or production identity provider. `federation.example.yaml`'s
values are illustrative placeholders (`__set_via_secrets_store__`), not
credentials for any real system.
