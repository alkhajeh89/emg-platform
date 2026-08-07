# ADR-038 Capability Verification — Keycloak Configuration & Experimental Findings

Everything in this document was determined by making real calls against the
running `emg-adr038-verification-keycloak` container (Keycloak 25.0), not
assumed. Where the mission required an explicit "do not assume" determination
(Acting Service claim shape), the raw evidence is included below.

## Feature flags required

`command: start-dev --import-realm --features=token-exchange,admin-fine-grained-authz`

Both are Technology Preview features in Keycloak 25.0. Without
`token-exchange`, the grant type is rejected outright; without
`admin-fine-grained-authz`, per-client exchange permissions cannot be
expressed at all (the realm-wide legacy toggle exists but grants **any**
client exchange rights to **any** other, which cannot satisfy the
negative-test requirement that the unauthorized Acting Service be
provably denied).

## Finding 1 — Acting Service identity: `azp`, not `act`

Real decoded (unsigned, non-secret) claims from this environment:

**Human Principal A's own token (the `subject_token` presented to exchange):**
```json
{
  "iss": "http://localhost:8180/realms/emg-verification",
  "sub": "985f646c-b049-43f0-b3e2-513bf9944e86",
  "azp": "emg-verification-ropc",
  "realm_access": { "roles": ["investigator", "platform-user"] },
  "tenant_id": "tenant-verification-a",
  "classification_clearance": "CONFIDENTIAL"
}
```

**The resulting exchanged Delegated Credential (audience A):**
```json
{
  "iss": "http://localhost:8180/realms/emg-verification",
  "aud": "emg-verification-audience-a",
  "sub": "985f646c-b049-43f0-b3e2-513bf9944e86",
  "azp": "emg-verification-bff",
  "realm_access": { "roles": ["investigator", "platform-user"] },
  "tenant_id": "tenant-verification-a",
  "classification_clearance": "CONFIDENTIAL"
}
```

`sub` is unchanged (Human Principal preserved). `azp` changes from the ROPC
client to `emg-verification-bff` — **the Acting Service is carried by
`azp`**, the "authorized party" that performed the exchange. **No `act`
claim was emitted in any configuration tried**, across every grant/exchange
call made during this verification. `claim_adapter.py` maps `azp` →
`DelegatedCredential.acting_service` on this basis, and it is the only place
in the whole harness that reads a raw Keycloak claim name — everything
downstream (tests, the capability matrix) works only against
`DelegatedCredential`.

## Finding 2 — `sub` preservation requires an explicit mapper, on the AUDIENCE client

Keycloak 25's default legacy/preview token-exchange behaviour does **not**
project `sub` into the exchanged token by default. Claim projection during
exchange is governed by the **target audience client's** default client
scopes, not the requesting (Acting Service) client's — a genuine,
non-obvious finding. Fix: an `oidc-usermodel-property-mapper`
(`user.attribute=id` → `claim.name=sub`) attached to each audience client's
default scopes (`emg-verification-subject-claim` in
`realm/emg-verification-realm.json`). This restores standard RFC 8693
behaviour via a standard Keycloak mapper — it does not weaken any check, and
it is why `emg-verification-audience-a`/`-b` each carry
`emg-verification-subject-claim` in their `defaultClientScopes`.

## Finding 3 — fine-grained exchange permissions, two dead ends avoided

Recorded here as implementation evidence per the mission's explicit
instruction (not an ADR amendment):

1. **Both legs need their own permission.** Keycloak's exchange check
   requires token-exchange permission enabled and policy-attached on *both*
   the source client (`emg-verification-ropc`, since that's who issued the
   original subject token) and each target audience client
   (`emg-verification-audience-a`/`-b`) — granting only the audience side is
   not sufficient. `provision.py::main` enables and attaches on all three.
2. **Never rename an auto-generated scope-permission.** Enabling
   fine-grained permissions on a client auto-creates a permission literally
   named `token-exchange.permission.client.<uuid>`. The first attempt
   overwrote that name with a literal `"token-exchange"` when attaching a
   policy — this collided with every other client's identically-named
   permission (Keycloak enforces `(name, resource_server_id)` uniqueness)
   and silently broke Keycloak's own internal convention-based lookup for
   that permission: the exchange then failed closed with "client not
   allowed to exchange to audience" even though a policy was still
   attached. Root-caused and fixed structurally in
   `provision.py::attach_policy_to_permission` by always reading the
   permission's current name back before writing.
3. **Policy creation is not idempotent by default.** Re-POSTing a client
   policy with a name that already exists raises a DB unique-constraint
   error. `provision.py::ensure_client_policy` checks by name (GET) before
   creating.

## Finding 4 — exchanged-token lifetime inherits the ordinary access-token lifespan

Keycloak 25's legacy exchange implementation has no separate
`requested_token_lifetime` behaviour observed; the exchanged token's
`exp - iat` equals the realm/client `access.token.lifespan` (60s in this
environment) exactly, confirmed by
`tests/security/adr_038/test_credential_lifetime.py::test_configured_lifetime_matches_recorded_value`.

## Finding 5 — re-exchanging an already-issued Delegated Credential is rejected outright

A further exchange call using an already-issued Delegated Credential
(audience A) as the `subject_token` for a new exchange (targeting audience
B) returns:

```
HTTP 400
{"error": "invalid_token", "error_description": "Invalid token"}
```

Keycloak does not treat a previously-exchanged token as a valid subject for
further exchange in this configuration. See
`tests/security/adr_038/test_credential_lifetime.py::test_reexchanging_a_delegated_credential_does_not_extend_beyond_realm_ceiling`.

## Commands used to determine the above (representative, not exhaustive — full set in `05_TEST_EXECUTION_LOG.md`)

```bash
docker compose --env-file .env.verification.local -f docker-compose.verification.yml up -d
python3 provision.py
# then real HTTP calls via keycloak_client.py's ropc_login / client_credentials / token_exchange,
# each POSTing form-encoded grants to /realms/emg-verification/protocol/openid-connect/token
```
