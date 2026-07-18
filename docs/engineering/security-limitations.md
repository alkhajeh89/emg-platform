# Identity Platform — Security Limitations & Deferred Items

Covers Sprint 2 (FEAT-02-1, FEAT-02-2), Sprint 3 (FEAT-02-3, FEAT-02-4),
Sprint 4 (FEAT-03-1, FEAT-03-2), Sprint 5 (FEAT-03-3, FEAT-03-4), and Sprint 6
(FEAT-04-1). Each item states what the current implementation does, what it
does not do, and when the gap is expected to close. Nothing here is silently
accepted — every limitation is a tracked, documented, deliberate scope
boundary.

## Controls implemented (Sprint 3)

- **No client secret in source control.** Every secret value committed to
  `tools/seed-data/keycloak/emg-realm.json` or `config.py`'s defaults is a
  clearly-labeled, non-production placeholder (`..._local_dev_secret_do_not_use_in_prod`
  suffix), used only by `docker-compose.yml`. Real environments source every
  secret from the centralized secrets store (Engineering Master Plan §5).
- **Secret redaction in logs.** Primary control is structural — no method on
  `AuditEventSink` (`audit.py`) accepts a raw secret or token as a
  parameter, so there is no call path that logs one. `redact.py` is the
  documented backstop for free-text values that might incidentally contain
  a secret-shaped string (e.g. an upstream error body), applied to the
  `/federation/providers` response's `connection_settings` and available for
  any future free-text logging.
- **Fail-closed token validation.** Both `SessionManager.verify` (HS256,
  human) and `ServiceTokenValidator.validate` (RS256, machine) raise
  `AuthorizationError` on every failure path — invalid signature, wrong
  issuer, wrong audience, expired, not-yet-valid, or (service tokens only)
  unrecognized client / missing required scope. There is no code path in
  either that returns a partially-trusted principal.
- **Separation between human and machine identities.** Enforced
  cryptographically, not by a flag: human EMG session tokens are HS256,
  service tokens are Keycloak-issued RS256 via JWKS — a human token
  presented to `ServiceTokenValidator` (or vice versa) fails signature
  verification before any claim is inspected. Enforced again structurally:
  `Principal` and `ServicePrincipal` are distinct dataclasses, and
  `get_current_principal` / `get_current_service_principal` are separate
  FastAPI dependencies, so a route cannot accidentally accept either
  identity kind interchangeably. See
  `services/identity/tests/test_separation_human_vs_service.py`.
- **Correlation identifiers for auth events.** Every `AuditEventSink` call
  site (both Sprint 2 human-auth events and Sprint 3 service-auth events)
  threads the request's `correlation_id` (ADR-015, `emg_telemetry`) through.
- **Structured allow/deny authentication telemetry.** `StructuredLogAuditSink`
  emits the ADR-015 actor/module/action/outcome shape for every login
  success/failure, refresh failure, and (Sprint 3) service-auth
  success/failure.
- **Rate-limiting readiness for token requests.** `InMemoryRateLimiter`
  (`rate_limit.py`) guards `/auth/login`, configurable via
  `EMG_IDENTITY_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` /
  `EMG_IDENTITY_LOGIN_RATE_LIMIT_WINDOW_SECONDS`.
- **Rotation-ready client-secret configuration.** Every client secret
  (`keycloak_client_secret`, `service_client_secret`, and every Keycloak
  client's `secret` in the realm seed) is sourced from environment
  variables / `Settings`, never hardcoded into logic — rotating a secret is
  an environment-variable/secrets-store change, not a code change.

## Controls implemented (Sprint 4)

- **Default-deny, fail-closed authorization.** `emg_policy_engine.PolicyEngine.evaluate()`
  denies a request with no matching rule and a request whose matching
  rules' conditions are all unsatisfied — both are the same code path as an
  explicit deny, not a fallthrough. `PolicyConfig` has no "default effect"
  field that could flip this; an empty or missing policy file
  (`load_policy_config`) denies everything, never allows everything.
- **Deny-overrides combining algorithm.** When a request matches both an
  allow rule and a deny rule, the deny rule wins — verified both at the
  `PolicyEngine` unit level
  (`libs/python/emg-policy-engine/tests/test_engine.py`) and end-to-end over
  real HTTP (`services/identity/tests/test_authz_router.py`).
  `PolicyConfig`/loader validation additionally flags any rule with zero
  conditions (`required_roles`/`required_attributes`/`required_scopes` all
  empty) as a configuration problem, since such a rule matches every
  principal unconditionally (`validate_policy_config`).
- **Structural support for both identity kinds without an import
  inversion.** `emg_auth_client.ServicePrincipalLike` is a `typing.Protocol`
  matching `services/identity`'s `ServicePrincipal` field-for-field; the
  shared PEP contract accepts either a human `Principal` or a machine
  `ServicePrincipal` (`AuthorizedIdentity = Principal | ServicePrincipalLike`)
  without `libs/python/emg-auth-client` ever importing from a service.
- **Allow and deny decisions are both audit-logged.** `AuditEventSink.record_authorization_decision`
  (extending the same interim, structured-logging-backed sink Sprint 2/3
  use) is called for every `/authz/check` request regardless of outcome —
  US-03's "denial and allow decisions are both logged" acceptance
  criterion.
- **`/authz/check` is explicitly introspection, not enforcement.** It always
  returns HTTP 200 with the `Decision` in the body rather than mapping deny
  to an HTTP error — a deliberate design choice (see `routers/authz.py`'s
  module docstring) that keeps this reference endpoint from being mistaken
  for a real enforcement gate on any resource.

## Controls implemented (Sprint 5)

- **Governed RBAC baseline role vocabulary.** `emg_policy_engine.roles.ROLE_CATALOG`
  (FEAT-03-3) is the single authoritative list of the platform's roles, each
  with a category (human/service), description, and governing reference. It
  is a *vocabulary* the ABAC engine's `required_roles` conditions draw from —
  deliberately not a second authorization mechanism, permission matrix, or
  role hierarchy. It exposes no `evaluate`/decision method, and it does not
  alter `services/identity`'s `SERVICE_REGISTRY`.
- **Policy configuration references are validated against the catalog.**
  `validate_policy_config` flags any `PolicyRule.required_roles` value not
  present in `ROLE_CATALOG`, so a misspelled or unknown role is surfaced to
  operators (see the advisory-only limitation below for the scope of this
  control).
- **Reusable authorization testing harness.** `emg_policy_engine.testing`
  (FEAT-03-4: `AuthorizationScenario`, `assert_scenario`, `run_scenarios`)
  gives every service a shared, declarative way to assert positive and
  negative authorization outcomes, adopted in
  `services/identity/tests/test_authz_scenarios.py`. No pytest runtime
  dependency and no YAML DSL, keeping the package's dependency and
  complexity footprint unchanged.

## Controls implemented (Sprint 6)

- **Append-only audit store with defense-in-depth immutability.** The audit
  event stores (`emg-audit-pipeline`) expose no update or delete method; the
  PostgreSQL application role (`emg_audit_app`) is granted INSERT and SELECT
  only (`tools/seed-data/postgres/001_audit_events.sql`). "No mutation or
  deletion" is an application-code and database-role guarantee.
- **Tamper-evident hash chain + integrity verification.** Every event carries
  a SHA-256 `event_hash` chained to the previous event's hash; `verify_chain`
  / `GET /audit/integrity` recompute the chain and report the first break,
  detecting out-of-band mutation, reordering, or gaps.
- **Centralized single-writer chain.** Sequence numbers and hash links are
  assigned by the store (inside `services/audit`), never by producers, so
  independent producer services cannot construct competing chains.
- **Idempotent ingestion.** `append` / `POST /audit/events` is idempotent by
  producer-supplied `event_id`.
- **No secrets or tokens in audit records.** Structural (no token/secret field
  on `SubmittedAuditEvent`) plus a pre-persistence guard that rejects
  sensitive-looking metadata keys and redacts secret-shaped substrings and
  bearer tokens from `reason`/metadata; raw access/refresh tokens, client
  secrets, passwords, and Authorization headers are never accepted.
- **Bounded metadata.** Metadata is size- and count-limited before
  persistence.
- **Authenticated, least-privilege audit APIs — no new roles.** Ingest
  requires a recognized service token; query and integrity require the
  existing `svc-audit` role (default-deny otherwise). No new role was
  invented; recognized clients/roles mirror the existing realm seed.
- **UTC server-assigned timestamps; correlation ids preserved end-to-end.**
- **Audit store kept distinct from `emg-telemetry`** (observability logs),
  per ADR-015 §Decision.
- **Non-blocking degraded-mode capture (Decision C).** `services/identity`'s
  `PipelineAuditSink` delivers to the audit service, and on transient failure
  spools durably, retries with bounded exponential backoff, dead-letters
  exhausted deliveries, keeps emitting ADR-015 telemetry, and — if it can
  neither deliver nor durably spool — emits critical telemetry and marks the
  service degraded (`GET /readyz`) rather than silently claiming the event was
  recorded.

## Known limitations (tracked, carried from Sprint 2 unless noted)

- **No session revocation** (Sprint 2). A compromised EMG refresh token
  cannot be actively revoked before its natural expiry (12h default) because
  there is no persistent session store yet. Revisit when Module 6 (audit /
  session storage, EPIC-04) lands.
- **`StructuredLogAuditSink` is not the real audit pipeline** (Sprint 2,
  extended Sprint 3 with service-auth events). It emits the same shape
  Module 6's append-only store will expect, so the swap is a one-line
  dependency change, not a rewrite — but until FEAT-04-1 ships, authentication
  and service-authentication events are durable only as long as log
  retention allows, not append-only-store-guaranteed.
- **`InMemoryRateLimiter` is readiness, not a production control** (Sprint
  3). Single-process, in-memory, resets on restart — unsuitable for a
  horizontally-scaled deployment (Engineering Master Plan §5, ADR-017 §2).
  The `RateLimiter` Protocol is the swap-in seam for a Redis- or
  gateway-backed limiter; no caller (`routers/auth.py`) needs to change when
  that swap happens.
- **The identity service does not issue or broker M2M tokens for other
  services** (Sprint 3, deliberate design choice, not a gap to close). See
  `routers/service_auth.py`'s module docstring. Each service is expected to
  hold and use its own Keycloak client credentials directly.
- **Federation is configuration-and-validation readiness only** (Sprint 3).
  No LDAP, Active Directory, external OIDC, or SAML client code is invoked
  by this service; actual protocol handling is Keycloak's own User
  Federation / Identity Brokering, configured per deployment. See
  `docs/engineering/federation-readiness.md`.
- **`redact_text`'s pattern matching is best-effort, not a guarantee**
  (Sprint 3). It catches common `"secret": "..."` / `key=value` shapes in
  free text; it is documented as a backstop specifically because call sites
  are expected to avoid logging raw upstream response bodies in the first
  place (`keycloak_client.py` never does).
- **No production LDAP/Active Directory connection, and no connection to a
  real government or production identity provider** (Sprint 3 — explicit
  scope exclusion, not a gap). `federation.example.yaml` contains
  placeholder values only.
- **No live, network-reachable authorization service** (Sprint 4 —
  deliberate library-first design choice, not a gap to close this sprint).
  `services/authz` remains scaffolded (`service.yaml` only); the PEP and
  ABAC engine are in-process libraries, consumed directly by whichever
  service embeds them.
- **Nothing in this codebase actually enforces a `/authz/check` decision
  yet** (Sprint 4). No Sprint 2/3 route in `services/identity` (or anywhere
  else) calls the PEP and rejects a request based on its `Decision` — that
  is each future adopting service's own responsibility, and has not been
  done anywhere as of Sprint 4.
- **`policy.example.yaml` is illustrative, local-development-only
  configuration** (Sprint 4), same status as `federation.example.yaml`. A
  real deployment authors its own policy file.
- **Unknown-role validation is advisory, not enforcing** (Sprint 5,
  FEAT-03-3). `validate_policy_config` *reports* a `required_roles` value not
  present in `ROLE_CATALOG`, but `load_policy_config` still loads the policy
  successfully — a typo'd role name is a warning, not a load-time rejection.
  Callers that want fail-closed behavior must inspect
  `validate_policy_config`'s output and act on it themselves. Hardening this
  into a load-blocking failure is a candidate for a future sprint once role
  governance is fully owned by the Policy Platform Team (ADR-016 §1). Note
  the ABAC engine remains fail-closed regardless: an unknown role in a rule
  simply never matches a real principal, so it cannot grant access — the
  advisory gap is about catching operator mistakes early, not about a
  privilege-escalation path.
- **The RBAC catalog is a vocabulary, not an enforcement layer** (Sprint 5,
  FEAT-03-3 — deliberate design boundary, not a gap). It does not define
  role→permission mappings, role hierarchy, or inheritance; all authorization
  decisions are made solely by the ABAC `PolicyEngine`.
- **No live authorization service** (Sprint 5). `services/authz` remains
  scaffolded (unchanged from Sprint 4); the PEP/ABAC engine are in-process
  libraries.
- **Immutability is application- and role-enforced, not absolute** (Sprint 6,
  FEAT-04-1 — honest boundary, not a gap to close by role grants alone). The
  append-only guarantee is enforced by the store contract (no mutate/delete
  method) and PostgreSQL INSERT/SELECT-only grants. It is **not** a claim that
  a PostgreSQL superuser, or anyone with direct storage/filesystem access, can
  never alter bytes. The hash-chain integrity verification exists precisely to
  *detect* such out-of-band mutation; cryptographic external anchoring /
  write-once media are later-sprint hardening.
- **Audit-capture degraded mode is fail-open for the business action, by
  approved design** (Sprint 6, Decision C). A transient audit-service outage
  does not fail login/authentication; events are durably spooled, retried, and
  dead-lettered, never silently dropped, and degradation is surfaced on
  `/readyz`. Hard fail-closed ("no governed action without a confirmed audit
  record") for designated higher-assurance actions requires security review
  and is a later-sprint decision — it is **not** implemented in Sprint 6.
- **The durable spool is a local file, not a production queue** (Sprint 6).
  `DurableSpool` (JSONL file + dead-letter file) is the durability floor so
  events are not lost during a brief audit outage; a real message queue /
  streaming pipeline and cross-node durability are later infrastructure
  (EPIC-11/12).
- **First-tier persistence only** (Sprint 6). Single-node PostgreSQL, plain
  idempotent init SQL (no Alembic — schema-migration tooling is a documented
  later production-hardening item), no table partitioning, retention, or
  HA/DR. Retention-*ready* fields (timestamp, classification) exist; retention
  *enforcement* is later.
- **Audit forwarding is disabled by default** (Sprint 6). To preserve Sprint
  2-5 behavior exactly, `EMG_IDENTITY_AUDIT_FORWARDING_ENABLED` defaults to
  False (telemetry-only); enabling it activates the durable-delivery path once
  the audit service is present. The plumbing is fully tested with a fake
  forwarder regardless.
- **Minimal query only, no human reporting surface** (Sprint 6). Only the
  US-04 query (by actor, time range, correlation id) is implemented, for
  `svc-audit` service principals. The richer human compliance-reporting
  interface is FEAT-04-4, a later Audit sprint.
- **Provenance is producer-asserted** (Sprint 7, FEAT-04-2 — trust-model note,
  not a gap). A producer supplies its own provenance (source system, originating
  actor, transformation history, parent references, evidence origin/collection
  method). The store assigns the event `schema_version`, sequence, and hash
  chain centrally, and provenance is tamper-*evident* once stored — but the
  store does not independently attest a producer's claimed origin. Cross-checking
  provenance against an external source of truth is later-sprint work.
- **Custody immutability is application/role-enforced, not absolute** (Sprint 7,
  FEAT-04-3 — same honest boundary as the audit store). `evidence_custody_events`
  is append-only via the store contract and INSERT/SELECT-only role grants; it is
  **not** a claim that a PostgreSQL superuser or direct storage access can never
  alter bytes. The custody hash chain + per-evidence sequence verification
  (`GET /audit/custody/integrity`) is the compensating control that *detects*
  mutation, deletion, and sequence gaps.
- **Custody integrity uses a hash chain, not digital signatures** (Sprint 7,
  FEAT-04-3 — deliberate scope boundary). FEAT-04-3's "digital signature *or*
  hash requirements" is satisfied with the established SHA-256 hash-chain
  approach; **no PKI / asymmetric signatures** were introduced (that would be a
  new architectural element requiring an ADR). External cryptographic anchoring
  and signature-based non-repudiation are later hardening.
- **Classification on reads is a *filter*, not clearance-based access
  enforcement** (Sprint 8, FEAT-04-4 — explicit scope boundary, not a gap).
  FEAT-04-4 lets an `svc-audit` reader *filter* audit and custody records by
  classification (and by module / action / outcome / source system /
  provenance-presence) and export them as JSON/CSV. It does **not** yet restrict
  *which* classifications a given principal may read: every audit/custody read is
  still gated only by the `svc-audit` service role, and a holder of that role can
  read and export records at any classification. Clearance-based
  classification-aware read *authorization* — a human compliance-officer/auditor
  principal whose clearance bounds the classifications returned, enforced via the
  policy engine — is a deliberate **follow-up**. It was intentionally not built
  this sprint because it needs a human reader role (none exists in
  `ROLE_CATALOG`; inventing one was out of scope) and an authorization-model
  decision (likely a new ADR). Until then, treat the audit read plane as a
  uniformly-trusted `svc-audit` surface. This is the single most important
  boundary a reviewer of FEAT-04-4 should note.
- **Report export is bounded, not streamed** (Sprint 8, FEAT-04-4). JSON/CSV
  export walks the filtered result set by keyset pagination (one store query per
  page, never per row — no N+1) and is capped at `EXPORT_MAX_ROWS` (100k). A
  result set larger than the cap is truncated rather than streamed; true
  streaming/chunked export for very large ranges is later hardening.

## Known technical debt (Sprint 6/7/8 — must be resolved for production)

These items are safe for the current scope (in-memory store + identity
forwarding disabled by default) but must be resolved before the PostgreSQL
path and real audit ingestion are enabled in a shared or production
environment. **Both were again carried forward unchanged in Sprint 8 (FEAT-04-4)
by explicit decision — FEAT-04-4 adds only read/query/report paths and
index-only SQL, so neither `emg-service-auth` consolidation nor connection
pooling was triggered by a proven Sprint-8 defect.** They should be resolved
before production load.

- **Duplicated service-token validator.** `services/audit`'s
  `ServiceTokenValidator` (`authn.py`) is a deliberate copy of
  `services/identity`'s Sprint 3 validator, to avoid a service→service import.
  The two can drift. Production use requires consolidating them into a single
  shared, independently-validated library (e.g. an `emg-service-auth`
  package). Both validators' negative paths (expired / wrong-audience /
  wrong-issuer / tampered-signature / unrecognized-client / insufficient-role)
  are covered by tests on each side, but the duplication itself remains debt.
  Sprint 7 added custody authorization (`svc-audit`-only) reusing the same local
  validator; consolidation was still intentionally **not** done, to avoid
  expanding scope.
- **PostgreSQL connection pooling / async-safe DB access.** The audit service
  holds a single `psycopg` connection per process and the ingest/query/
  integrity handlers (now including the Sprint 7 custody handlers) are
  `async def` invoking synchronous, blocking DB calls, which serialize on and
  block the event loop. Production hardening requires a connection pool
  (`psycopg_pool`) and offloading DB I/O (e.g. `run_in_executor`) or synchronous
  handlers. Correctness under concurrency is already ensured (transaction-level
  advisory locks — a distinct lock per chain — + `UNIQUE` sequence constraints +
  bounded retry), so this is a throughput/availability hardening item, not a
  correctness defect.

## Controls and limitations (Sprint 9, FEAT-05-1 Core Ontology)

Sprint 9 delivers the Core Ontology **library-first** (`emg-ontology`) — a model
+ conformance layer with **no persistence, no live service, and no Neo4j
binding**. Its security posture this sprint is about *modeling primitives* the
future write path (FEAT-05-2) will build on, not runtime enforcement.

**Controls implemented:**
- **Governance envelope by construction.** Every entity requires
  `classification`, `trust_score`, and a `provenance_reference` (a *reference*
  into Module 6, never a copy); models are frozen and `extra="forbid"`, so
  mass-assignment and missing-envelope "writes" fail at construction.
- **Conformance validator** — pure and storage-independent; rejects unknown
  types, missing/invalid envelope fields, out-of-range trust, invalid lifecycle,
  invalid effective dates, invalid source/target types, cardinality violations,
  dangling endpoints, prohibited self-loops, mass-assignment, and — for the
  inference/leakage concern — an **edge classification below either endpoint**
  (classification dominance).
- **Immutable history / no delete path.** Supersession + versioning + effective
  dating only; there is no mutate-in-place or delete API, so historical versions
  cannot be silently changed.
- **Deterministic, versioned descriptor** guarded by a golden gate — an
  unreviewed change to the ontology shape fails the build.
- **Single system-of-record.** The ontology links to Module 6 audit/provenance/
  custody by identifier only; no audit content is duplicated, and the
  audit-metadata helper carries identifiers/types only (no entity content).

**Limitations (deliberate Sprint 9 scope boundaries, not gaps):**
- **Classification is a modeling attribute, not read enforcement.** As with
  Module 6, Sprint 9 provides classification *tagging by construction* only. It
  does not enforce clearance-based reads of graph entities/relationships (no PEP
  integration, no new role, no human reader role). Traversal-authorization
  leakage, inference from restricted relationships, and business-unit/tenant
  isolation are addressed at the *substrate* level (every node and edge is
  classified, and the dominance rule prevents an under-classified edge) but are
  **not runtime-enforced** — enforcement arrives with the live query/traversal
  surface (FEAT-05-4) and the same clearance/role/ADR decision deferred out of
  FEAT-04-4.
- **Cardinality and dangling-endpoint checks are context-supplied.** The pure
  validator checks these only against the sibling edges / known-id universe the
  caller passes in; global graph-wide guarantees (uniqueness, orphan detection,
  DoS-via-expansion limits) are the persistence/traversal layer's job
  (FEAT-05-2 / FEAT-05-4).
- **No audit emission.** The graph-mutation audit contract is *defined* but
  nothing is emitted (no write service). "Fail-closed on degraded audit" for
  graph writes is a decision to be ratified with FEAT-05-2.
- **Trust score is a stored field only** — no scoring engine (FEAT-05-3).
  **Lifecycle status is a validated field only** — no managed state machine
  (FEAT-05-5).

## Controls and limitations (Sprint 10, FEAT-05-2 Knowledge Ingestion Pipeline)

Sprint 10 delivers the ingestion pipeline **library-first** and
**storage-independent** (`emg-knowledge-pipeline`), persisting through an
in-memory `GraphStore` adapter. There is **no Neo4j binding, no live service,
and no HTTP surface** this sprint.

**Controls implemented:**
- **Server-side assignment of trust boundaries.** `owner`,
  `provenance_reference`, and `trust_score` are assigned by the pipeline from the
  `IngestionContext`, never from the request — and they are **not fields on the
  request models at all**, so spoofing them is structurally impossible (the same
  posture as the Sprint 6 `SubmittedAuditEvent`). `source_principal` is part of
  every deterministic id, so one producer cannot overwrite or suppress another's
  nodes (Sprint 6 P5 posture).
- **Mass-assignment rejected** — request models are `extra="forbid"`, and an
  attempt to set a server-assigned/envelope field via `attributes` is a typed
  validation failure, not a silent drop.
- **Oversized-payload DoS prevention** — natural keys, attribute values,
  attribute counts, and batch sizes are all bounded; an over-limit request is
  rejected before any work.
- **No persistence before validation** — the validator runs ontology
  conformance + duplicate/dangling/cycle checks first; only a fully valid batch
  is persisted, atomically (rollback ⇒ no partial graph), and audit is emitted
  only after a durable commit.
- **Cycle detection is iterative (no recursion DoS)** — the `DERIVED_FROM`
  cycle check uses an explicit-stack DFS, so a long acyclic chain up to
  `MAX_BATCH_RELATIONSHIPS` cannot exhaust Python's recursion limit (Sprint 10
  review fix C1). A prohibited cycle is a typed `CODE_CYCLIC_DEPENDENCY`
  rejection, never an unhandled `RecursionError`.
- **Single system of record** — a persisted node's `provenance_reference` points
  at the Module-6 audit event emitted for its creation; no audit content is
  copied into the graph, and correlation ids ride on the audit event.

**Limitations (deliberate Sprint 10 scope boundaries, not gaps):**
- **Trust score is an interim server default, not a computed score** — the
  pipeline assigns a conservative source-type default; composite trust *scoring*
  is FEAT-05-3.
- **Classification is carried and dominance-checked on edges, but reads are not
  clearance-enforced** — there is no live read/traversal surface this sprint;
  clearance-based read authorization arrives with the Semantic Layer (FEAT-05-4)
  and the role/ADR decision deferred out of FEAT-04-4.
- **Cardinality is checked intra-batch only** — global (cross-store) cardinality
  and graph-wide traversal-DoS limits are the persistence/traversal layer's job
  (FEAT-05-4).
- **Supersession is a minimal primitive** — `supersede_entity`/
  `supersede_relationship` emit the `*.superseded` contracts and append a new
  version, but the managed lifecycle state machine and current-version
  resolution are FEAT-05-5.
- **Audit delivery is via an injected sink** — the default is an in-memory
  collecting sink; a production deployment injects a durable `AuditSink` (the
  Sprint 6 degraded-spool posture). "Fail-closed on degraded audit" for graph
  writes remains a decision to finalize when the live ingestion service is
  built.
- **In-memory store only** — the Neo4j adapter, the storage-independent Semantic
  Layer, and durability/HA are FEAT-05-4 / production. No other database is
  introduced.
- **Deferred hardening (Sprint 10 review C2) — commit-authoritative result +
  audit.** The `IngestionResult` `created`/`skipped` split and the audit
  emission are computed from the pre-commit validation snapshot, not the
  committed outcome. Under a genuine race, two callers can each report "created"
  for the same deterministic id and re-emit its audit event. This is **benign
  and bounded**: the persisted graph is always correct (the store's `_apply` is
  lock-serialized — never a fork or duplicate node), and mutation audit
  `event_id`s are deterministic so Module 6 deduplicates a re-emit. It is
  **not** fixed in Sprint 10 (no transaction/audit redesign). Deferred
  hardening: the graph transaction should report the *actually inserted* ids and
  the ingestion result + audit emission should be derived from the authoritative
  commit outcome — target phase: the **future persistent (Neo4j) adapter / live
  ingestion service** (FEAT-05-4 and the service). Not claimed as fixed.

## Controls and limitations (Sprint 11, FEAT-05-3 Validation & Trust Scoring)

Sprint 11 delivers the trust-scoring + advanced-validation engine **library-
first** (`emg-trust-scoring`) — pure, deterministic, storage-independent, with
no service.

**Controls implemented:**
- **Trust cannot be spoofed.** The input model `TrustSignals` has **no trust
  field** and forbids extra fields, so a caller supplies *observable signals*
  and the engine **computes** the score — there is no code path by which a
  caller sets a trust value. (This is the real replacement for the FEAT-05-2
  interim source-type default; it is not yet wired into the pipeline — see
  limitations.)
- **Deterministic + reproducible.** The engine is pure (no wall-clock, no
  randomness, no I/O; temporal decay uses an explicit `as_of`); identical
  signals + policy yield a byte-identical result, pinned by a golden test.
- **Immutable output.** `TrustScoreResult`, `QualityGateReport`, and the
  combined `TrustEvaluation` are frozen.
- **Bounded, non-dominating signals.** Every signal is bounded at construction
  (non-negative counts, a defined source type, a `[0, 1]` duplicate likelihood),
  and every factor is clamped to `[0, 1]` and combined as a *weighted average* —
  so a single manipulated signal (e.g. an inflated evidence count) caps at its
  factor's clamp and can contribute at most its weight, never dominating the
  composite.
- **Explainable by construction.** Each result carries a full per-factor
  breakdown (raw score, weight, contribution) and a human-readable explanation
  (Architecture Baseline: grounded, cited, explainable; Module 7 §34).
- **Versioned policy.** `policy_version` is pinned so a stored score can be
  interpreted against the exact scoring behaviour that produced it.

**Limitations (deliberate Sprint 11 scope boundaries, not gaps):**
- **The engine is not wired into the ingestion pipeline.** FEAT-05-2 still
  assigns its interim source-type default trust; replacing it with this engine
  would change merged FEAT-05-2 behaviour, so it is a follow-up for the future
  live ingestion service (which will call `signals_from_entity` + `evaluate`).
- **The engine scores the signals it is given; it does not attest them.** Signal
  *trustworthiness* is the ingestion pipeline's responsibility (server-side
  assignment of owner/provenance, bounds, conformance — FEAT-05-2). The scoring
  library computes deterministically over provided signals and does not
  independently verify, e.g., that a claimed evidence count is real.
- **Interim factor weights and source confidences.** The `DEFAULT_POLICY`
  weights and per-source-type confidences are reasonable defaults, not a
  calibrated model; a future sprint may re-tune them (bumping `policy_version`).
- **No persistence, no service, no Neo4j, no Semantic Layer** (FEAT-05-4), **no
  lifecycle management** (FEAT-05-5), and no retrieval/search/embeddings/AI/UI.

## Controls and limitations (Sprint 12, FEAT-05-4 Semantic Layer)

Sprint 12 delivers the Semantic Layer **library-first** and **storage-independent**
as `libs/python/emg-semantic-layer`. It **defines query/traversal semantics only
and executes nothing** — there is no store, no driver, no network, and no Neo4j —
so its security posture is about the *shape and bounds of a query*, not runtime
data access (which a future storage binding owns).

Controls:

- **Deeply immutable, self-validating query models.** Every model (`SemanticQuery`
  and its parts, the graph value objects, the plan, the result) is frozen
  (`extra="forbid"`) and validated at construction. Immutability is **deep**:
  `SemanticNode` / `SemanticRelationship` `properties` is stored as a read-only
  `MappingProxyType` over a private copy, so a caller can neither mutate a
  returned node's properties (item-assign / add / delete all raise) nor mutate the
  dict it passed in after construction.
- **Bounded by construction — in size, not only depth.** Every user-controlled
  quantity is hard-capped: traversal depth (`MAX_TRAVERSAL_DEPTH`), page limit
  (`[MIN_PAGE_LIMIT, MAX_PAGE_LIMIT]`), **page offset (`MAX_PAGE_OFFSET`)**,
  relationship-type fan-out (`MAX_RELATIONSHIP_TYPES_PER_STEP`), filter nesting
  (`MAX_FILTER_DEPTH`), **filter width (`MAX_FILTER_CONDITIONS`,
  `MAX_FILTER_GROUPS`)**, **selector-id count (`MAX_SELECTOR_IDS`)**,
  **projection-field count (`MAX_PROJECTION_FIELDS`)**, and **ordering-key count
  (`MAX_ORDERING_KEYS`)**; a fully-unbounded `NodeSelector` is rejected. An
  unbounded scan, an unbounded page, an arbitrarily deep offset, or an oversized
  collection is **not expressible**.
- **No arbitrary code, no injection surface.** Operators and directions come from
  **closed enums**, property/condition values are plain scalars, and every
  identifier/label (ids, type names, relationship-type names, filter/projection/
  ordering fields, property keys) passes `ensure_safe_label`, which rejects empty/
  whitespace-only strings and any NUL, ASCII control, CR/LF, or Unicode bidi
  override/control character (legitimate Unicode preserved). There is no free-form
  operator string, no raw query fragment, no callable, and nothing is `eval`'d. A
  malicious-looking *value* is stored as inert data. The `SemanticQueryExecutor`
  contract requires bindings to map operators onto their own **parameterised**
  query API and never string-concatenate query text.
- **Deterministic canonical step order.** `plan()` is pure — identical queries
  yield an identical plan — and `SemanticOrdering` defines a total, unambiguous
  order, so a conforming executor returns reproducible results across backends.
  The plan is a canonical *step order*, not an executable form: `PlanStep.detail`
  is human-readable text an executor must not parse.
- **Typed rejection.** Cross-model semantic violations raise `SemanticQueryError`
  (an `emg_errors.ValidationError` subclass with a stable code), including a
  defensive planner-level depth re-check.

Limitations / non-goals (by design this sprint):

- **The layer enforces query *structure* and *bounds*, not data-access
  authorization.** Classification / need-to-know filtering and result-level
  authorization (Module 7 §21) are the responsibility of the consuming service and
  the storage binding; `classification` is carried on `SemanticNode` as a label
  only, with no enforcement here.
- **Output DTOs are constructable.** `SemanticResult` / `PageInfo` are frozen but
  can be hand-built in Python (a documented trust boundary — they are still
  internally consistency-checked); a consumer must treat them as executor output
  and never fabricate one in place of a real query result.
- **Two storage seams, composed later.** The FEAT-05-4 `SemanticQueryExecutor`
  (read-query) is separate from FEAT-05-2's `GraphStore` (append-only
  persistence); a future adapter may implement both. An ontology→`SemanticNode`
  adapter is intentionally deferred to the binding sprint (it belongs with the
  binding, not the abstraction).
- **No persistence, no database driver, no networking, no Neo4j binding, no
  retrieval/search/embeddings/AI/LLM/REST/UI**, and **no lifecycle management**
  (FEAT-05-5). The layer is **not wired** into any service, the knowledge
  pipeline, or the trust-scoring runtime — integration happens only through the
  `SemanticQueryExecutor` extension point, which no binding implements yet.

## Controls and limitations (Sprint 13, FEAT-05-5 Knowledge Lifecycle & Versioning)

Sprint 13 delivers Knowledge Lifecycle & Versioning **library-first** and
**storage-independent** as `libs/python/emg-knowledge-lifecycle`. It **defines
lifecycle semantics only and executes nothing, stores nothing** — no persistence,
no scheduler, no execution engine, no networking, no Neo4j — so its security
posture is about the *validity and boundedness of lifecycle models*, not runtime
data movement (which a future storage binding owns).

Controls:

- **Immutable, self-validating models.** Every model (`KnowledgeVersion`,
  `VersionChain`, `LifecycleEvent`, the policies, the decisions, the report) is
  frozen (`extra="forbid"`) and validated at construction, so a malformed
  lifecycle model is rejected immediately.
- **Deterministic transitions.** The transition relation is a **fixed closed
  table** — no caller-supplied rule, no arbitrary code, no escape hatch. A
  `LifecycleEvent` can only describe a legal transition; an illegal or self
  transition is not representable.
- **Version-graph validation (single O(N) analysis).** Chains reject mixed
  entities, duplicate versions, orphaned parents, more than one active version,
  and cycles; `LifecycleValidator` additionally enumerates cross-entity/
  non-decreasing parents, inverted effective windows, and invalid states as typed
  issues (defensive even against `model_construct` bypass). There is one
  authoritative analysis shared by `validate_chain` and the `VersionChain`
  constructor — no duplicate cycle algorithm.
- **Linear-time, bounded validation.** Chain size is hard-capped
  (`MAX_CHAIN_SIZE = 10_000`) and chain analysis is **O(N)** (a single
  three-colour DFS over the parent graph; each version coloured at most once), so
  a legal within-bounds chain cannot cause a quadratic denial-of-service — a
  maximal deep chain validates in tens of milliseconds. Lineage walks are
  iterative and cycle-safe (a `visited` set). Version numbers and retention
  windows are bounded too. (Review fix: the earlier design re-walked the full
  lineage from every node — O(N²), tens of seconds at the size cap.)
- **Enforced transition-reason policy.** `LifecyclePolicy.require_reason` is
  enforced by `LifecycleValidator.validate_event` / `assert_event` (raising
  `MissingReasonError` when a required reason is absent); a whitespace-only reason
  is rejected at event construction.
- **No injection surface.** Identifiers and free-text metadata are validated by
  `ensure_safe_label` (empty/whitespace-only and NUL/ASCII-control/CR-LF/Unicode-
  bidi rejected; legitimate Unicode preserved). Values are plain data; nothing is
  `eval`'d.
- **Deterministic evaluation.** Retention/archive/restore use an explicit `as_of`
  (no wall clock, no randomness), so decisions are reproducible. Windows —
  including `restore_window_days` — are measured from a version's effective-end
  reference (`effective_to` if set, else `effective_from`), **not** from an
  archival timestamp (which this storage-independent library does not model).

Limitations / non-goals (by design this sprint):

- **The library validates and evaluates lifecycle models; it does not enforce,
  schedule, or persist anything.** Applying a transition, archiving, or purging a
  version is the responsibility of a future storage binding / service. There is no
  execution engine and no scheduler.
- **Decision DTOs are constructable.** `RetentionDecision` / `ArchiveDecision` /
  `RestoreDecision` are frozen but can be hand-built in Python (a documented trust
  boundary — obtain them from the evaluators, never fabricate one).
- **Not wired to the ontology.** `VersionState` aligns with (but does not import)
  `emg_ontology.LifecycleStatus` and adds the operational states
  `deprecated`/`archived`; mapping the managed state onto an ontology entity's
  `lifecycle_status` field is a future binding concern.
- **No persistence, database driver, networking, Neo4j, retrieval, embeddings, AI,
  LLM, REST, or UI.** The library is **not wired** into `emg-knowledge-pipeline`,
  `emg-trust-scoring`, or `emg-semantic-layer` — integration happens only through
  future extension points, none implemented yet.

## Controls and limitations (Sprint 14, EPIC-13 / FEAT-13-1 Universal Connector Framework)

Sprint 14 delivers the Universal Connector Framework **library-first** and
**storage-, vendor-, and protocol-independent** as `libs/python/emg-connectors`. It
is **contracts-only and executes nothing external**, so its posture concerns the
*validity and boundedness of connector/plugin declarations*, not runtime data
access (which a future storage binding / connector plugin owns).

> **Additive epic — frozen Backlog unchanged.** Filed under the next free ids
> (EPIC-13 / FEAT-13-1); `EPIC-06 = Search` / `FEAT-06-1 = Lexical Search` are
> untouched.

Controls:

- **No external anything.** No networking, persistence, authentication, HTTP
  client, message queue, cloud/vendor SDK, CLI, or UI. Verified by a
  clean-subprocess check that importing the framework pulls in **no** third-party
  network/SDK client or sibling package.
- **No vendor branching in the core.** A test strips string literals and comments
  from every core module and asserts no vendor token (`sap`, `oracle`,
  `sharepoint`, `jira`, …) appears in executable code — so there is no `if SAP`
  path; connectors are added only as plugins.
- **Immutable, self-validating models.** Descriptors, capabilities, configurations,
  events, decisions, and results are frozen (`extra="forbid"`) and validated at
  construction; nested mappings (`ConnectorConfiguration.values`,
  `ConnectorChange.attributes`, mapped attributes) are read-only.
- **No injection surface.** All identifiers/labels pass `ensure_safe_label`
  (empty/whitespace-only and NUL/ASCII-control/CR-LF/Unicode-bidi rejected;
  legitimate Unicode preserved). Values are plain scalars; nothing is `eval`'d.
- **No secrets.** `ConnectorAuthentication` records a mechanism + an **opaque
  credential reference**; a `secret` config field must be a string reference and
  cannot carry an inline default. The framework performs no auth and stores no
  secret.
- **Extensible capabilities without weakening validation.** Vendor-specific
  `extension_capabilities` are free-form but pass the same `ensure_safe_label`
  check (control/bidi/NUL rejected), are bounded by `MAX_EXTENSION_CAPABILITIES`,
  and cannot collide with a standard `ConnectorCapability` value — so the open
  extension point adds no injection or ambiguity surface.
- **Single source of truth for connectors.** `ConnectorPluginLoader` owns one
  registry and auto-publishes/withdraws a plugin's connectors atomically, so there
  is no second store to drift out of sync and no way to leave a partial
  registration after a rejected (colliding) plugin.
- **Bounded.** Every collection and string is length-capped (`limits.py`); version
  numbers are bounded; registries reject overflow.
- **Deterministic, fixed lifecycle machines.** Connector/plugin transitions come
  from fixed closed tables; negotiation, registration, discovery, and validation
  are pure and deterministic.
- **Static, in-memory plugin registration only.** No dynamic filesystem scanning,
  entry-point loading, package installation, remote marketplaces, or runtime code
  execution — so there is no arbitrary-code-loading surface this sprint.

Limitations / non-goals (by design this sprint):

- The framework validates and models; it does not connect, authenticate,
  synchronize, schedule, or persist. Those belong to future connector plugins and
  a synchronization runtime.
- Output/mapping DTOs are constructable (a documented trust boundary — obtain them
  from a connector, never fabricate one).
- Not wired into any service; `services/*` untouched.

## Deferred to later sprints (not started)

- Module 5 Authorization Platform: a live network-reachable authorization
  service, if a future sprint's design calls for one (EPIC-03 is otherwise
  complete after Sprint 5's FEAT-03-3/03-4). Hardening the advisory
  unknown-role check into a load-blocking failure is also deferred.
- Knowledge Graph (EPIC-05) remaining work: the **concrete Neo4j storage binding**
  and the **wiring** of the library-first knowledge layer into a live service.
  FEAT-05-1 (Core Ontology, Sprint 9), FEAT-05-2 (Knowledge Ingestion Pipeline,
  Sprint 10), FEAT-05-3 (Validation & Trust Scoring, Sprint 11), **FEAT-05-4
  (Semantic Layer, Sprint 12)**, and **FEAT-05-5 (Knowledge Lifecycle &
  Versioning, Sprint 13 — storage-independent, library-first)** are all
  implemented as libraries, so EPIC-05's knowledge-layer feature set is
  functionally complete. Not yet started: the Neo4j binding (a `GraphStore` +
  `SemanticQueryExecutor` implementation) and the live service. `services/
  knowledge-graph` remains scaffolded; the trust engine is not yet wired into
  ingestion; the Semantic Layer is not yet wired to any store or consumer; and the
  lifecycle library is not yet wired to the pipeline or any store.
- Module 6 Audit (EPIC-04) is now **functionally complete**: FEAT-04-1 (Audit
  Event Pipeline, Sprint 6), FEAT-04-2 (Provenance Record Model, Sprint 7),
  FEAT-04-3 (Digital Evidence Chain-of-Custody, Sprint 7), and FEAT-04-4 (Audit
  Query & Reporting Interface, Sprint 8) are all implemented. See
  `sprint-8-design.md` and `ARCHITECTURE_STATUS.md`. The one deliberate follow-up
  carried out of FEAT-04-4 is **clearance-based classification-aware read
  authorization** (a human reader role + policy-engine enforcement, likely a new
  ADR) — see the classification limitation above. Classification *filtering*
  ships in FEAT-04-4; classification *enforcement* does not.
- Search, GraphRAG, AI agents, Decision Intelligence (EPIC-06 onward; Modules
  8–10).
- Frontend features (EPIC-10 onward).
