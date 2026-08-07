# EMG ADR-036 — Application and BFF Boundary

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-03
**Baseline:** `develop` at `dd84fa9`.
**Related:** ADR-014 (presentation architecture),
ADR-025 (authorization placement),
ADR-026 Revision 2 (denial shapes),
ADR-034 (service trust),
ADR-035 (human authentication),
ADR-038 (Human Identity Delegation Architecture),
Freeze §16, §17, §19, §22.
**Closes:** frontend decision **D-F-006** (BFF Integration).

> **This ADR authorizes an application boundary contract only.** It implements
> no code, creates no service, defines no screen, and amends no accepted ADR.
> ADR-021 (Enterprise API Strategy) remains **Proposed** and is not relied upon.

---

## 1. Context

**FACT.** `emg_knowledge_graph_api.authn.TenantServiceTokenValidator` recognizes
four registered **service** clients and requires each client's registered realm
roles (`authn.py:63-74`, `:201-213`). ADR-034 establishes that a service token
denotes a reviewed, registered backend service.

**FACT AT THE ACCEPTED BASELINE.** No application layer existed: `apps/`
contained only `.gitkeep` and a README. Current implementation status is
recorded separately in `ARCHITECTURE_STATUS.md` and the architecture decision
register.

**INFERENCE.** A browser cannot become a registered service client without
granting a client-side artifact the trust level of a backend service, which
would break ADR-034's trust model. **There is therefore no architecture in which
the browser calls a Knowledge Graph, Audit, or Identity service API directly.**

## 2. Decision

### D-1 — A Backend-for-Frontend is MANDATORY

The BFF is not an optional convenience or a performance optimization. It is the
only boundary at which a browser session can be exchanged for a credential
acceptable to the platform's services. Any design in which the browser calls a
service API directly is rejected.

### D-2 — Browser-to-BFF boundary

- Same-origin HTTPS only.
- Authentication is the ADR-035 opaque session cookie. **No bearer token of any
  kind crosses this boundary.**
- Every state-changing request carries CSRF protection (ADR-035 D-10).
- The browser sends no tenant, no clearance, and no principal identity.

### D-3 — Boundary handoff beyond the BFF

The BFF calls services over HTTP only. It authenticates its own registered
Service Principal under ADR-034 and, for delegated human execution, uses the
Delegated Credential governed by ADR-038.

**The BFF must not impersonate the Human Principal as a Service Principal.**
The Human Principal and Acting Service remain independently attributable.

ADR-036 does not govern the Delegated Principal or Delegated Credential beyond
the BFF. Those downstream delegation semantics are governed exclusively by
accepted ADR-038, which resolves the former open sub-decision recorded in §5.

### D-4 — The BFF is NOT a Policy Enforcement Point

Authorization remains where ADR-025 §8.3 places it: in the service HTTP layer,
evaluated by `emg-policy-engine` through the existing PEP contract.

The BFF may hide navigation or controls for user experience, but such hiding
**grants nothing and proves nothing**. Every authorization decision is re-made
server-side on every request. A BFF that permits an action the service would
deny is a defect; a BFF that hides an action the service would permit is
cosmetic.

### D-5 — Tenant propagation

The tenant is derived from the human's verified token (ADR-035 D-5), held
server-side, and propagated by the BFF.

**A BFF route that accepts a tenant identifier from the browser — as parameter,
path segment, body field, header, or cookie — is a defect.** There is no
default, fallback, or inferred tenant at any layer.

### D-6 — Classification-safe responses

The BFF forwards service responses. It **must not** re-derive, merge, enrich,
re-rank, or aggregate classified content, and it applies no clearance logic of
its own.

ADR-026 Revision 2 uniform denial shapes are preserved end-to-end: a denied
entity surfaces as not-found, a denied list item is silently pruned, a denied
path returns `found=false`, a denied history fact returns an empty item. The BFF
**must not** add counts, totals, "N results hidden" hints, or any other signal
from which the existence of a denied object could be inferred — the same class
of leak closed by the ADR-026 pagination-metadata remediation.

### D-7 — Session cookies

Per ADR-035 D-8: `HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` prefix, bounded
idle and absolute lifetimes, rotated on privilege change. Session state is held
server-side by the BFF.

### D-8 — Caching

- **Cacheable.** Server-side responses for immutable historical revisions, keyed
  by `(tenant, entity, revision)` **and** the requesting principal's clearance.
- **Not cacheable.** Current-head reads, any classified payload, and any
  authorization decision. These carry `Cache-Control: private, no-store`.
- **Never.** No shared cache, CDN, or intermediary may hold tenant-scoped or
  classified content. A cache entry is never reused across principals or tenants.
- **Browser storage.** No classification-bearing payload, token, or tenant
  identifier is written to `localStorage`, `sessionStorage`, or IndexedDB.

### D-9 — Degraded behaviour

| Condition | Behaviour |
| :--- | :--- |
| Neo4j unavailable | Reads continue from PostgreSQL (P-01); informational banner only. Not an error state |
| Policy configuration missing | Services return 403 for every request. The UI must say **"access configuration unavailable"**, never "you lack permission" |
| Audit service unavailable | **Block** governed actions — fail closed |
| Service 5xx | Generic error surface; never a stack trace, internal identifier, or payload fragment |
| Session expired | Re-authenticate; never a silent scope downgrade |
| BFF unable to obtain a service credential | Fail closed — no anonymous or degraded-privilege fallback |

### D-10 — Absolute prohibitions

1. **No service token in the browser**, in any form or storage.
2. **No direct datastore access from the browser or the BFF** — PostgreSQL,
   Neo4j, Qdrant, Redis, or any repository class.
3. **No SQL or Cypher construction** in the browser or the BFF.
4. **No classification or authorization logic** in the browser or the BFF.
5. **No tenant identifier** accepted from client input.
6. **No import of `emg_persistence`, `emg_memory_graph` internals, or any
   service-internal repository** by application-layer code.

These are enforceable by test and should be guarded the way
`services/knowledge-graph/tests/test_dependency_boundary.py` already guards the
service layer.

## 3. Non-goals

This ADR does **not**: select a frontend framework, UI library, design system,
build tool, routing model, or client-state library (D-F-001…D-F-005, D-F-008…
D-F-010 remain open); define screens or wireframes; introduce real-time or
websocket transport; define a public API or SDK (Freeze §19/§20, ADR-021 remains
Proposed); introduce GraphQL; authorize any product capability; or implement any
code or configuration.

## 4. Consequences

**Positive.** The browser holds no credential of value. ADR-034's service trust
model is preserved intact. Authorization and classification remain enforced in
one place. Tenant isolation extends to a new caller type without a new
mechanism. Closes D-F-006 with real authority.

**Negative — accepted.** A new deployable component the platform does not
currently operate, with its own session store, availability, and scaling
profile. One additional network hop on every request. Downstream delegation is
governed separately by ADR-038. Phase 2B remains blocked until ADR-038's
mandatory capability verification succeeds; acceptance of ADR-038 does not
constitute implementation.

**Neutral.** No existing service changes. No existing API contract changes.

## 5. Historical Note — Downstream Human Delegation

This section records the architectural context that existed when ADR-036 was originally accepted.

At the time of publication, the downstream human delegation mechanism had not yet been selected. Two candidate approaches were identified for future evaluation:

- OAuth 2.0 Token Exchange (RFC 8693).
- Cryptographically signed propagated identity assertions.

That architectural decision has subsequently been completed.

The authoritative delegation architecture is now defined by **ADR-038 — Human Identity Delegation Architecture**, which formally adopts OAuth 2.0 Token Exchange (RFC 8693), subject to the capability verification requirements and architectural constraints defined therein.

Accordingly:

- ADR-036 continues to govern the Browser-to-BFF architectural boundary.
- ADR-038 exclusively governs delegated human identity beyond the BFF boundary.
- All delegation semantics, trust requirements, security invariants, credential requirements, capability verification, audit semantics, and implementation constraints are defined exclusively by ADR-038.

This section is retained solely for historical traceability and shall not be interpreted as defining the current delegated identity architecture.


## 6. Acceptance criteria

- **AC-1.** The BFF is recorded as mandatory, with structural rationale.
- **AC-2.** No browser holds a service token, in any form or storage.
- **AC-3.** No direct datastore access exists from browser or BFF, enforceable
  by test.
- **AC-4.** The BFF is documented as not a PEP; every authorization decision is
  re-made service-side.
- **AC-5.** Tenant is never accepted from client input at any layer.
- **AC-6.** ADR-026 denial shapes are preserved end-to-end; no count, total, or
  hint reveals a denied object.
- **AC-7.** Session cookies conform to ADR-035 D-8.
- **AC-8.** Caching is keyed by tenant and clearance; classified payloads and
  head reads are `private, no-store`; no shared cache holds tenant-scoped data.
- **AC-9.** The degraded-mode matrix in D-9 is implemented as specified,
  including the "access configuration unavailable" wording.
- **AC-10.** All six D-10 prohibitions hold.
- **AC-11.** The downstream human delegation mechanism is governed exclusively by ADR-038. No alternative delegation mechanism may be implemented outside ADR-038.
- **AC-12.** No frontend framework, design system, or build decision is made
  here.
