# ADR-038 Capability Verification — Security Findings & External-Concern Tracking

## New findings from this verification

1. **Keycloak 25's legacy token-exchange does not project `sub` by default**
   (Finding 2, `02_KEYCLOAK_VERIFICATION_CONFIG.md`) — required-configuration
   item, not an architecture gap. Production implementation must include an
   equivalent `sub`-projecting mapper on every registered downstream
   audience client, or AC-2 (Human Subject Preservation) silently fails at
   the exact moment it matters most.
2. **Fine-grained exchange permissions require both legs (source client
   AND each audience client) to be individually enabled and
   policy-attached** (Finding 3) — required-configuration item for Phase 2B;
   easy to under-provision (grant only the audience side) and get a
   confusing "exchange denied" with no obvious cause.
3. **Auto-generated fine-grained permission names must never be
   overwritten** (Finding 3.2) — a genuine, non-obvious Keycloak footgun
   discovered and fixed during this verification; recorded so Phase 2B
   provisioning tooling doesn't rediscover it the hard way.
4. **`emg_audit_service.authn._RECOGNIZED_CLIENTS` has no entry for any BFF
   client type yet.** Confirmed structurally: the allowlist is a hardcoded,
   reviewed 4-entry dict with no "Acting Service" / BFF category. This
   verification worked around it (see below) rather than modifying
   production code, but **Phase 2B implementation will need to add a
   reviewed BFF/Acting-Service entry to that allowlist** — this is expected,
   ordinary Phase 2B scope, not a defect found here.
5. **Audit contract required zero schema changes** to carry both identities
   — `source_principal` (Acting Service, server-assigned) and
   `actor`/`actor_type` (Human Principal, producer-supplied) already exist
   and were proven sufficient end-to-end against the real, unmodified audit
   app. This closes what was previously an open question in the repository
   baseline (`00_REPOSITORY_BASELINE.md`).

## Repository-faithful test-harness note (audit attribution)

Per the approved plan's Required Change #1, the shared running `emg-audit`
container (:8002) was never posted to. Instead, `audit_harness.py` imports
the real, unmodified `emg_audit_service.create_app()`, backs it with
`InMemoryAuditEventStore`/`InMemoryCustodyEventStore` (isolated,
in-process, throwaway test persistence — the audit service's own
established pattern from `services/audit/tests/conftest.py`), and validates
producer tokens against the real isolated verification Keycloak's JWKS over
HTTP (not a locally injected key, for stronger evidence than that service's
own unit tests use). This satisfies "prove that both Human Principal and
Acting Service can be represented independently in the existing audit
contract" without spinning up a second containerized service or touching
shared infrastructure. Recorded as the deliberate, disclosed choice it is,
not a shortcut.

**`emg-svc-knowledge-graph-writer` client-id reuse**, also disclosed here:
`_RECOGNIZED_CLIENTS` is hardcoded in production source this verification
may not modify. To exercise the real, unmodified audit ingest path (not a
mock of it), the isolated `emg-verification` realm contains a client whose
`clientId` string is literally `emg-svc-knowledge-graph-writer` — own
random, non-committed secret, isolated realm, no other overlap with
production. This validates the audit contract's structural capacity; it
does **not** validate that a not-yet-registered production BFF client id
would be accepted by that allowlist — registering one is explicitly
Phase 2B implementation scope (see finding 4 above), not verification scope.

## External concerns from the prior architecture review — tracked, not reopened

### Concern A — Authorization Authority key custody / rotation

**Classification: Production Security / IdP Hardening.** Nothing in this
verification touched, exercised, or depends on Keycloak's own signing-key
lifecycle — the verification realm uses whatever signing key Keycloak
generated on realm creation, exactly as production would use whatever
Keycloak provisions. This verification neither confirms nor worsens the
prior finding (no ADR governs the Authorization Authority's own key
rotation/custody). **No ADR created. Remains open, tracked in
`06_FINAL_VERIFICATION_REPORT.md`'s remaining-configuration list, not
escalated further by this work.**

### Concern B — Shared-realm tenant topology

**Not modified, not escalated.** This verification's own realm
(`emg-verification`) is itself a single shared realm carrying multiple
tenants (`tenant-verification-a`, `tenant-verification-b`) via a `tenant_id`
claim — the same topology already used in production's `emg` realm.
Verification found no security or architectural contradiction in this
topology; tenant isolation held correctly end-to-end (property 5 above,
plus the existing structural `TenantId`/`GraphQueryScope` mechanism this
verification did not need to touch). **ADR-025 is not modified. The prior
finding — that this topology was never an explicit "considered options"
decision — remains open as a low-severity documentation item, unchanged by
this work.**

### Concern C — Classification caching

**No production BFF cache was built or exercised here** — the verification
environment has no cache anywhere in it. The future test obligation
recorded in the prior architecture review stands unchanged and is restated
here for continuity: once a real BFF/cache exists, add an automated test
asserting classified/current-head responses carry `Cache-Control: private,
no-store` and that any cacheable-revision key includes clearance. **Not
addressed by this verification; not in scope; correctly deferred.**
