# Service Identity Registration Guide

Sprint 3 (FEAT-02-3, Service Identity & Machine-to-Machine Authentication).
This is the operational procedure for registering a new EMG service so it
can authenticate to other services via OAuth 2.0 Client Credentials, and for
other services to validate its tokens.

## Why registration is two steps, in two places

A service's machine identity has to be known in two independent places, and
both are required — neither alone is sufficient:

1. **Keycloak** (`tools/seed-data/keycloak/emg-realm.json` locally; the
   realm's admin console/API in a real environment) — where the client
   actually exists, gets a secret, and is issued RS256 access tokens.
2. **`services/identity/src/emg_identity/service_registry.py`** —
   `SERVICE_REGISTRY`, the identity service's allow-list of which
   `client_id`s are recognized machine callers, and what least-privilege
   roles each one holds.

`ServiceTokenValidator` (`service_token_validator.py`) rejects any token
whose `azp` (authorized party) claim is not a key in `SERVICE_REGISTRY`,
*even if Keycloak validly signed it*. A validly-signed token is necessary
but not sufficient — this is deliberate defense-in-depth: a client
provisioned in Keycloak by mistake, or removed from EMG's own registry
without also being disabled in Keycloak, still cannot be trusted by any
service using `ServiceTokenValidator`.

## Registering a new service (development/local realm)

1. Add a confidential client to `tools/seed-data/keycloak/emg-realm.json`,
   following the pattern of `emg-svc-authorization`:
   - `"serviceAccountsEnabled": true`
   - `"directAccessGrantsEnabled": false` — service-account-only, never a
     human login (this is what makes "clear separation between user
     sessions and service identities" structural rather than conventional
     at the Keycloak layer too).
   - `"clientAuthenticatorType": "client-secret"` with a clearly-labeled
     local-dev-only secret (`..._local_dev_secret_do_not_use_in_prod`
     suffix, matching every other secret in this file).
   - `"defaultClientScopes": ["emg-internal-services-audience"]` — without
     this, the issued token will not carry the `emg-internal-services`
     audience `ServiceTokenValidator` requires, and every validation will
     fail with an audience error.
   - `"fullScopeAllowed": false` — least privilege; grant only the specific
     realm roles the service needs via `defaultRoles`/direct role
     assignment, not the realm's full role catalog.
   - Add a matching `service-account-<client-id>` entry under `"users"`
     with the realm roles this service should hold.
2. Add an entry to `SERVICE_REGISTRY` in `service_registry.py`:

   ```python
   "emg-svc-<name>": ServiceRegistryEntry(
       service_name="<name>",
       roles=("service-account", "svc-<name>"),
   ),
   ```

   The `roles` tuple should match the realm roles granted in step 1 — it is
   the identity service's own record of what that service is allowed to do,
   independent of (and re-validated against, not merely copied from) the
   token's own claims.
3. This is a reviewed, versioned source change (both files are committed to
   the repository), consistent with ADR-016 §3's pattern for registering new
   agent roles/APIs before deployment — not a runtime or database
   operation.

## Registering a new service (non-local environments)

The Keycloak-side step is the same in shape but performed against the
real realm via Keycloak's admin API or console, with the client secret
sourced from the centralized secrets store (Engineering Master Plan §5) —
never written into a committed file. The `SERVICE_REGISTRY` change in
`service_registry.py` is identical in every environment: it is
environment-agnostic code, not configuration, so the same reviewed source
change ships to every environment via normal deployment.

## How a registered service actually calls another service

1. The calling service holds its own `client_id`/`client_secret` (e.g. via
   `Settings.service_client_id` / `service_client_secret`, sourced from
   environment/secrets store — see `services/identity/README.md`'s
   environment variable table).
2. It requests its own token directly from Keycloak using
   `KeycloakClient.client_credentials_token(client_id=..., client_secret=...)`
   — demonstrated in `services/identity/tests/test_keycloak_client.py`.
3. It presents that token as a Bearer token to the callee.
4. The callee validates it with its own `ServiceTokenValidator.validate()`
   (optionally with `required_scope=` for endpoint-level least privilege)
   and receives back a `ServicePrincipal` — never a human `Principal` (see
   `service_principal.py`'s module docstring for why these are deliberately
   distinct types).

The identity service does **not** broker tokens on behalf of other
services — see `services/identity/src/emg_identity/routers/service_auth.py`'s
module docstring ("Why the identity service does not broker M2M tokens")
for the least-privilege rationale.
