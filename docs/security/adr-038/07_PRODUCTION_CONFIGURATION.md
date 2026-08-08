# Phase 2B — Production Configuration Record

Companion to `06_FINAL_VERIFICATION_REPORT.md`. Records the configuration
decisions Phase 2B implementation actually made, and the ones it
deliberately left as open deployment/security-baseline decisions rather
than encoding an arbitrary number into application code, realm config, or
any ADR.

## Canonical realm source

`tools/seed-data/keycloak/emg-realm.json` is the sole canonical runtime
artifact — it is what `docker-compose.yml` mounts into the running
`emg-keycloak` container (`./tools/seed-data/keycloak:/opt/keycloak/data/import:ro`).
All Phase 2B realm additions (Batch 1) were made there exclusively.

`docker/keycloak/import/emg-realm.json` is **confirmed non-canonical and
unused by the current runtime** — not mounted or referenced by
`docker-compose.yml` or any other build/deploy path found in this repo. Per
explicit instruction, it was **not deleted** in this batch; destructive
cleanup is out of scope for a security-implementation PR. It should be
treated as **deprecated** and is flagged here for a future, separate
cleanup PR after a full reference/history review — in particular, it
declares a client (`emg-frontend`) with `publicClient: true`, which would
directly contradict ADR-035 D-3 if anyone ever pointed a real deployment at
it. Until removed, nothing in this repository's build or deploy path
consumes it.

## Required claim mappings (Batch 1)

| Client scope | Attached to | Purpose |
| :--- | :--- | :--- |
| `emg-human-tenant-claim` | `emg-identity-service`, `emg-studio-bff` | Projects `tenant_id` into human-issued tokens — closed a real gap (no human user previously carried any tenant claim). |
| `emg-human-delegated-claims` | `emg-knowledge-graph-audience` | Restores `sub` (not carried by default during Keycloak 25 token exchange — capability verification Finding 2), plus `tenant_id`/`classification_clearance`/`realm_access.roles`, on the exchanged Delegated Credential. |

`dev.investigator` and `dev.decisionmaker` were given a `tenant_id` user
attribute (`tenant-dev`) so the existing seed users are usable end-to-end
through the new human-auth path without further setup.

## Final correction sprint Finding 3 — human access-token claims, verified against a real Authorization Code flow

The first correction sprint's `azp`-based audience check (`oidc.py::verify_access_token`)
was reasoned about but never driven against a real Keycloak instance. This
sprint actually did: a fresh Keycloak 25 container was imported from the
canonical realm and a genuine Authorization Code + PKCE exchange was
performed end-to-end (form-based login, real authorization code, real token
exchange) for `dev.investigator` via `emg-studio-bff`. Findings:

- **`azp` is confirmed correct** — the human access token's `azp` is
  `emg-studio-bff`. The existing check stands, now confirmed rather than
  assumed.
- **`aud` is confirmed absent entirely** from the human access token for
  this client's scope configuration — validates the prior decision NOT to
  add a strict `audience=` check (it would have rejected every legitimate
  token).
- **Two real, previously-undetected bugs were found and fixed**, because no
  existing test exercised a genuinely Keycloak-issued human access token
  (every unit test builds its own locally-signed token that always happens
  to already have the right shape):
  1. `emg-studio-bff`'s `defaultClientScopes` entirely replaced Keycloak's
     built-in scope set (no `basic`/`roles` scopes exist in this realm at
     all), so the access token carried **no `sub` and no `realm_access` at
     all** — every real human login would have failed PyJWT's own
     `require: ["sub", ...]` check immediately. Fixed by adding a new
     `emg-human-identity-claims` client scope (mirrors the `sub` and
     `realm_access.roles` mappers already proven in
     `emg-human-delegated-claims`) and setting `emg-studio-bff`'s
     `fullScopeAllowed: true` — matching the pre-existing
     `emg-identity-service` client's own convention for a human-facing
     client (the realm-role mapper does not emit any roles for a client
     with `fullScopeAllowed: false` unless the roles are separately scoped
     to that client, confirmed empirically, not assumed).
  2. `classification_clearance` arrives as a Keycloak multivalued-attribute
     **list** (`["INTERNAL"]`), not a bare string, because the pre-existing
     `emg-human-classification-attributes` mapper (not part of Phase 2B)
     never set `multivalued: false`. `oidc.py::verify_access_token` did not
     unwrap this, so every real human's clearance silently defaulted to
     `UNCLASSIFIED` regardless of their actual clearance — fail-closed in
     effect but functionally broken. Fixed with the same unwrap
     `services/identity/routers/auth.py::_extract_human_attributes` already
     established for the identical claim shape. (The Delegated Credential
     path, `emg-human-delegated-claims`'s `emg-delegated-clearance-mapper`,
     already correctly sets `multivalued: false` and was already validated
     scalar-shaped by the ADR-038 capability verification suite — this bug
     was isolated to the BFF's own login path.)
- **Unrelated but blocking, also found during this verification**: three
  pre-existing client-scope/client/role `description` fields in the
  canonical realm exceed Keycloak's 255-character DB column limit — one
  predates Phase 2B entirely (`svc-knowledge-graph-writer`'s role
  description). A genuinely fresh `docker compose up` against the canonical
  realm has apparently never actually succeeded until this fix — the shared
  long-running `emg-keycloak` instance never surfaced it because its
  persistent volume was never dropped and re-imported from scratch. All
  three descriptions were shortened; verified by a clean `down -v` + `up`
  producing a clean import with zero errors.

## Per-audience token-exchange grant (Batch 1 — deployment step, not realm-import syntax)

Keycloak 25's fine-grained authorization model has **no declarative
realm-import syntax** for token-exchange permissions — confirmed
experimentally during ADR-038 capability verification
(`02_KEYCLOAK_VERIFICATION_CONFIG.md`, Finding 3) and unchanged by this
batch. Granting `emg-studio-bff` → `emg-knowledge-graph-audience` exchange
rights is a **required, one-time Admin REST API deployment step**, following
the exact procedure `tests/security/adr_038/provision.py` already
implements and proved correct: enable fine-grained permissions on the
source client (`emg-studio-bff`) and the audience client
(`emg-knowledge-graph-audience`), create a client policy naming the
authorized Acting Service, and attach that policy to each client's
auto-generated `token-exchange` scope permission — being careful never to
overwrite that permission's auto-generated name (the documented dead end in
Finding 3.2). This step has **not** been executed against the shared
`emg-keycloak` instance by this implementation batch (see "What was not
done," below) — it must be run once, deliberately, as part of standing up
Phase 2B for real use.

## Confidential BFF setup

`emg-studio-bff` (Batch 1): confidential, `standardFlowEnabled: true`,
`pkce.code.challenge.method: S256`, no public client anywhere in the
canonical realm. Secret stored as a clearly-labeled local-dev-only value in
the canonical realm file, matching every other client in that file's
existing convention — production overrides via the centralized secrets
store, never via this file (unchanged convention, not a Phase 2B decision).

## Token / session / Delegated Credential lifetime

**No production number is set anywhere in this batch.** Every lifetime
value introduced is an explicit, configurable `Settings` field with a
short, clearly-labeled development/test default:

- `apps/studio-bff/.../config.py::Settings.session_ttl_seconds` (default
  `300`) — the BFF's own server-side session lifetime.
- Keycloak's `emg-studio-bff` / `emg-knowledge-graph-audience` client
  `access.token.lifespan` attributes (default `300`, matching the realm's
  existing `300`s convention already used by every other client in this
  file) — this is also, per capability-verification Finding 4, the lifetime
  Keycloak 25 applies to an exchanged Delegated Credential (there is no
  separate requested-lifetime mechanism to configure).

ADR-038 §7.5 requires only that the lifetime be "bounded" and "as short as
operationally practical" — it does not name a number, and this batch does
not invent one either, per explicit instruction. **The production value is
an undetermined deployment/security-baseline decision requiring its own
evidence** (threat model of credential leakage window vs. operational
friction) before it is set — it is not decided by this implementation
batch, and no ADR was amended to contain one.

## Authorization Authority key custody / rotation

**Unchanged, still an open production-security requirement**, not
addressed by this implementation batch (external Concern A, tracked
continuously since the prior architecture review through the ADR-038
capability verification). No ADR governs Keycloak's own signing-key
rotation, storage/HSM posture, or compromise/recovery procedure. This
remains true after Phase 2B's implementation and is restated here for
continuity rather than re-litigated or designed here.

## Correlation ID propagation, and the one hop it structurally cannot cross (Final correction sprint Finding 7)

Verified end-to-end: Browser -> BFF (the BFF's own `correlation_id_middleware`
establishes/reads one id per incoming request) -> Knowledge Graph (the proxy
forwards the BFF's own established id, not a raw re-read of whatever the
browser did or didn't send) -> Audit (KG's outbound audit-producer call now
also sets the `x-correlation-id` HTTP header, not only the JSON body field —
the persisted audit *event* was always correct since audit's event schema
reads the body field, but audit's own HTTP-level request logs previously
carried a different, freshly-generated id for that one call).

**Keycloak is the one hop this cannot cross, structurally, not as a defect.**
Keycloak is an unmodified third-party OpenID Provider. Its
`/protocol/openid-connect/{auth,token,logout}` endpoints have no mechanism to
accept or echo back a custom `x-correlation-id` (or any application-defined)
header through the OAuth flows this platform uses — Authorization Code,
token exchange, refresh, revocation. Correlation continuity is therefore two
separate, internally-continuous chains: Browser<->BFF, and
BFF<->KG<->Audit — with the Keycloak hop in between necessarily breaking
continuity between them, for as long as Keycloak remains an unmodified
third-party IdP. This is not something to work around (there is no
supported extension point for it); it is recorded here so it is never
mistaken for an implementation gap in this platform's own code.

## KG's new outbound audit-producer credential

`services/knowledge-graph/.../config.py::Settings.audit_producer_client_id`
defaults to the already-registered `emg-svc-knowledge-graph-writer` client
— **no new Keycloak client was created** for this purpose; Knowledge Graph
reuses its own existing, reviewed service identity to authenticate its
outbound calls to the audit service (an ordinary ADR-034 service-to-service
call, independent of the ADR-038 delegation chain).

## Final correction sprint Finding 6 — the exchange grant is now automated, and verified end-to-end

The per-audience exchange grant described above is no longer a manual
deployment step: `tools/scripts/provision-keycloak-realm.py` (a stdlib-only
script, no dependency install needed) runs automatically via the new
`keycloak-provision` one-shot service in `docker-compose.yml`, which
`studio-bff` now depends on (`condition: service_completed_successfully`)
before it starts. A completely fresh `docker compose up` therefore now
produces a working delegated identity path with zero manual steps.

**Verified for real, not assumed**: an isolated Keycloak 25 was started
from a genuinely empty volume, importing only the canonical realm; the
provisioning script was run against it exactly as the compose service
would; a real human Authorization Code login was performed
(`dev.investigator`); the resulting access token was exchanged via a real
RFC 8693 call to `emg-knowledge-graph-audience` — **`200 OK`**, with a
correctly single-audience, `azp`-identified, subject/tenant/clearance/roles-
preserved Delegated Credential. This is the same real-Keycloak verification
discipline Finding 3 used, applied here to the exchange-grant automation
specifically. The previous version of this document reported this step as
manual and unverified against a live instance; both are now resolved.

What remains genuinely out of this batch's scope: this was verified against
an *isolated* instance seeded from the canonical realm (to avoid modifying
the shared running `emg-keycloak`, per the standing constraint on this
correction sprint) — not the shared stack itself, which still needs an
operator to restart Keycloak against the updated `emg-realm.json` (now also
requiring `--features=token-exchange,admin-fine-grained-authz`, correction-
sprint Finding 2) the next time it's recreated. The mechanics proven here
are identical either way; only the shared instance's own lifecycle
(recreating its persistent volume) is outside this sprint's authority.

## Known limitation — session storage is in-process for this batch (correction-sprint Finding 1)

The Studio BFF originally shipped with a `RedisSessionStore` that connected
to the platform's Redis directly from `apps/studio-bff`. An independent
review correctly identified this as a confirmed violation of ADR-036
D-10.2, which names Redis explicitly and unconditionally among the
datastores a BFF may never access directly: "No direct datastore access
from the browser or the BFF — PostgreSQL, Neo4j, Qdrant, Redis, or any
repository class." `RedisSessionStore` has been removed; the `redis`
Python dependency was removed from `apps/studio-bff/pyproject.toml` and the
now-unnecessary addition to the shared `requirements-production.in`/`.lock`
was reverted.

**`InMemorySessionStore` is the only session-storage adapter for this
batch, in every environment including production.** This is a real,
disclosed limitation: sessions do not survive a process restart and are
not shared across multiple Studio BFF instances, so this batch does not yet
support horizontal scaling of the BFF. Durable/shared session storage
requires a Platform-Service-fronted HTTP session API — the BFF calling a
service over HTTP for session storage, per ADR-036 D-1/D-3, never a
datastore connection of its own — which is explicitly deferred as future
work, not designed here.

## Correction-sprint summary

An independent review (Codex) produced 13 findings against the initial
Batch 1–6 implementation. 11 were confirmed and fixed (with new/updated
tests); 2 were rejected with direct ADR citation (a "required scope" check
and a "reject invalid classification_clearance" check would each have
contradicted ADR-038 §7.6 and ADR-035 D-6 respectively, which this batch
must not reopen). Full finding-by-finding evidence, fixes, and test names
are in the correction-sprint's own final report delivered alongside this
document. No ADR was modified. No PolicyEngine, persistence, or mutation-route
changes were made. Delegated-credential caching remains unimplemented, as
required.

## Final correction sprint summary

A second, final review produced 10 further findings before merge. All 10
were independently confirmed against the current code (not accepted
blindly) and fixed, with new/updated tests: session pending-authorization
expiry and bounded-growth eviction; session rotation on subject/tenant
mismatch (fail-closed) or clearance/roles change (rotate) during refresh;
human access-token claims verified against a real Authorization Code flow
against a fresh Keycloak import — which surfaced and fixed two real,
previously-undetected bugs (missing `sub`/`realm_access` entirely, and an
unwrapped multivalued-attribute list for `classification_clearance`) plus
three pre-existing realm description fields exceeding Keycloak's DB column
limit that had silently prevented any genuinely fresh realm import from
ever succeeding; full 6-outcome delegated audit attribution (classification
denial and genuine not-found are now distinguished in the audit record,
though identical in the HTTP response; unhandled errors are audit-attributed
before the 500 propagates); production startup now fails fast on the
committed dev-placeholder secrets; the token-exchange grant is now
automated and verified end-to-end against a fresh checkout; correlation ID
now also reaches the audit service's own HTTP-level header, with the
Keycloak hop's structural break documented rather than worked around; logout
revocation failures are now logged; downstream `Set-Cookie` headers can no
longer be forwarded to the browser; and `apps/studio-bff` now genuinely
participates in `make lint`/`make typecheck`/CI's container vulnerability
scan, none of which previously covered it. No ADR was modified. No
PolicyEngine, persistence, or mutation-route changes were made.
Delegated-credential caching remains unimplemented.
