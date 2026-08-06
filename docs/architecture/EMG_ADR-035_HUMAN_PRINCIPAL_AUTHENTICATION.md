# EMG ADR-035 — Human Principal Authentication

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-03
**Baseline:** `develop` at `dd84fa9`.
**Discharges:** ADR-025 §8.9 — *"Human `Principal` login path for the Knowledge
Graph API"*.
**Related:** ADR-025 (tenant + operation authorization),
ADR-026 Revision 2 (classification enforcement),
ADR-034 (service trust),
ADR-036 (Application and BFF Boundary),
ADR-038 (Human Identity Delegation Architecture),
Product Architecture Freeze §16, §17, §22.

> **This ADR authorizes an authentication contract only.** It implements no
> code, configures no Keycloak realm, and creates no product capability. It
> amends no accepted ADR.

---

## 1. Context

**FACT.** `services/knowledge-graph/src/emg_knowledge_graph_api/authn.py:63-74`
defines `_RECOGNIZED_CLIENTS` containing exactly four **service** client
identifiers. `validate()` rejects any token whose `azp`/`client_id` is not in
that set. No human can authenticate to the Knowledge Graph API today.

**FACT.** ADR-025 §8.9:486-489 records the human login path as a reserved
extension point and states that `AuthorizationRequest.principal` is already
typed generically (`AuthorizedIdentity = Principal | ServicePrincipalLike`,
`emg-auth-client/pep.py:26`), so *"adding a human path later requires no change
to this ADR's authorization call site."*

**FACT.** `emg_auth_client.Principal` (`principal.py:15-17`) carries exactly
`subject`, `roles`, and `attributes`. It carries no tenant.

**FACT.** Every client in `tools/seed-data/keycloak/emg-realm.json` is
`"publicClient": false` **and** `"standardFlowEnabled": false`. The
Authorization Code flow is disabled realm-wide.

**FACT.** The only human grant implemented is
`emg_identity.keycloak_client.login_with_password` (`:138-153`) using
`grant_type: "password"` — Resource Owner Password Credentials.

## 2. Decision

### D-1 — OIDC Authorization Code with PKCE (S256) is the human authentication flow

Human users authenticate through the OpenID Connect Authorization Code flow
with PKCE, code challenge method **S256**. `plain` is not permitted.

### D-2 — Resource Owner Password Credentials is rejected for browser use

ROPC must never back a human browser session. It requires the application to
handle the user's password, defeats multi-factor and step-up authentication,
cannot support enterprise SSO (required by Freeze §25 for v1.0), and is
deprecated in OAuth 2.1. The existing `login_with_password` implementation may
remain for service and test purposes; it is **not** a human session path.

### D-3 — A confidential Keycloak client is required for the BFF

The Authorization Code flow terminates at a **confidential** client owned by the
BFF (ADR-036), not at a public browser client. The client secret is a
server-side credential and must never reach the browser.

**Realm configuration is a prerequisite, not a deliverable of this ADR.** The
required client does not exist. Provisioning it — standard flow enabled,
registered redirect URIs, PKCE S256 required, human role/clearance/tenant claim
mappers — is configuration work governed by this ADR but performed separately.

### D-4 — Human `Principal` construction

A verified human token yields an `emg_auth_client.Principal` with no change to
that type:

| Element | Source | Rule |
| :--- | :--- | :--- |
| `subject` | verified `sub` claim | Never derived from request content |
| `roles` | `realm_access.roles` | Same extraction shape as `authn.py:207-209` |
| `attributes["classification_clearance"]` | `classification_clearance` claim | Normalized through the existing shared `emg_common_types.normalize_classification_clearance` |

### D-5 — Tenant derivation

The tenant is derived **solely** from the verified `tenant_id` token claim,
exactly as `authn.py:223-236` already does for services. A human caller context
pairs the principal with a separately derived `TenantId`, mirroring the existing
`CallerContext` shape (`authn.py:111-117`).

**A tenant identifier is never accepted from a request parameter, path, body,
header, or cookie.** No default, fallback, or inferred tenant exists.

### D-6 — Clearance degrades; tenant does not

A missing, non-string, or unrecognized `classification_clearance` claim resolves
to `UNCLASSIFIED` and is **not** an authentication failure — preserving ADR-026
Revision 2 §8.4 exactly. A missing or invalid `tenant_id` claim **is** an
authentication failure.

### D-7 — The authorization call site is unchanged

No change is made to `require_permission`, `PepMutationAuthorizationEvaluator`,
`MutationAuthorizationPreflight`, or any policy rule as a consequence of this
ADR. `AuthorizedIdentity` already admits `Principal`, and
`mutation_authorization.py:37-40` already resolves ownership for both identity
kinds (`Principal.subject` / `ServicePrincipal.client_id`), so the existing
`owner_matches_principal` condition works for humans unchanged.

### D-8 — Session and token boundaries

**The browser holds an opaque session cookie and nothing else.**

- Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` prefix, idle timeout
  and absolute lifetime both bounded.
- The browser **never** holds an access token, refresh token, ID token, client
  secret, tenant identifier, or clearance value.
- Tokens are held server-side, mapped from the session. Refresh occurs
  server-side. The session identifier is rotated on any privilege change.

### D-9 — Logout

Logout revokes the server-side session **and** the refresh token, and clears the
cookie. A revoked session is never revived by a still-valid refresh token.

### D-10 — CSRF protection

Because authentication is cookie-borne, every state-changing request across the
browser-to-BFF boundary carries CSRF protection. `SameSite` alone is not
sufficient.

### D-11 — Fail-closed behaviour

| Condition | Outcome |
| :--- | :--- |
| Invalid signature, issuer, audience, or expiry | 401 |
| `tenant_id` claim absent or invalid | **401 — never a default tenant** |
| `classification_clearance` absent or unknown | Resolve `UNCLASSIFIED`, continue (D-6) |
| Required role absent | Authenticate, then 403 from the PEP |
| Identity provider unreachable | 503 — **never** a cached-identity fallback |
| Session expires mid-journey | Re-authenticate — **never** a silent scope downgrade |

## 3. Non-goals

This ADR does **not**:

- implement authentication code;
- configure or modify any Keycloak realm;
- define UI screens;
- introduce a new identity provider;
- change `Principal`, `ServicePrincipal`, or `AuthorizedIdentity`;
- alter any authorization policy rule;
- introduce API keys or machine-to-machine authentication flows (governed by ADR-034);
- govern the Browser-to-BFF boundary (governed by ADR-036);
- govern delegated human identity beyond the BFF boundary, which is defined exclusively by ADR-038 (Human Identity Delegation Architecture);
- authorize any product capability.


## 4. Consequences

**Positive.** Discharges a reserved extension point without reopening ADR-025.
Every human persona in Freeze §4 becomes reachable. The browser holds no
credential of value. Enterprise SSO and MFA become possible because the flow is
delegated to the identity provider. The downstream delegated human identity architecture is governed separately by ADR-038.

**Negative — accepted.** A Keycloak realm change is a hard prerequisite; no
human can authenticate until it lands. Two divergent realm artifacts exist
(`tools/seed-data/keycloak/emg-realm.json` and
`docker/keycloak/import/emg-realm.json`, the latter defining only `admin`/`user`)
and must be reconciled before rollout. Server-side session state introduces a
component the platform did not previously operate.

**Neutral.** No existing service authentication path changes.

## 5. Acceptance criteria

- **AC-1.** Authorization Code + PKCE S256 is the only human browser flow;
  `plain` is rejected.
- **AC-2.** ROPC is documented as rejected for browser use, with rationale.
- **AC-3.** The OIDC client is confidential; no client secret reaches the browser.
- **AC-4.** A human `Principal` carries `subject`, `roles`, and
  `attributes["classification_clearance"]`, with no change to the `Principal` type.
- **AC-5.** Tenant is derived only from the verified `tenant_id` claim.
- **AC-6.** A request supplying a tenant identifier by any client-controlled
  means is rejected.
- **AC-7.** Absent or invalid `tenant_id` yields 401 and never a default tenant.
- **AC-8.** Unknown clearance resolves to `UNCLASSIFIED` and does not reject.
- **AC-9.** No change is made to any authorization call site or policy rule.
- **AC-10.** The browser holds no access, refresh, or ID token.
- **AC-11.** Logout revokes session and refresh token together.
- **AC-12.** CSRF protection covers every state-changing browser-to-BFF request.
- **AC-13.** Every condition in D-11 fails closed as specified.
- **AC-14.** No Keycloak configuration file is changed by this ADR.
