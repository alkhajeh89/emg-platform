# services/knowledge-graph

Mutation authorization is checked at preflight and revalidated through the
same PEP against the exact immutable graph snapshot read inside the write
transaction. Authorization-relevant drift returns a safe conflict. Stored
idempotent replays are reauthorized against current metadata.

PostgreSQL deployments use separate runtime and migration jobs and DSNs. The
serving container receives only the DML runtime credential. A one-shot
migration job receives `EMG_KNOWLEDGE_GRAPH_API_MIGRATION_POSTGRES_DSN`, exits
successfully before serving instances start, and never shares its owner
credential with the runtime process. The runtime role has no schema ownership
or DDL; its only delete permission is the narrowly required deletion of an
expired idempotency claim during conflict-aware replacement.

Scaffolded in Sprint 1 (FEAT-01-1). Governing architecture: Module 7 — Knowledge
Graph Platform. No business logic or API implementation exists yet — see
/services/README.md for target Epic/Sprint.

## Boundary scope

`services/knowledge-graph` is an application/orchestration boundary.
Graph-domain models and behavior belong to `emg-memory-graph`.

Tenant-scoped graph persistence is accessed through the platform-core
`emg_platform_core.ports.graph_store.GraphStore` port. Persistence adapters stay
behind `emg-persistence`.

The internal `KnowledgeGraphApplication.build_revision()` workflow accepts
validated ontology objects plus an explicit tenant, principal, and `as_of`
timestamp. It extends the tenant's current immutable graph through
`MemoryGraphBuilder` and commits through the platform `GraphStore` transaction.
The returned `BuildRevisionResult` is an immutable application DTO whose tenant,
principal, content hash, and graph counts are copied from the committed
`WriteReceipt`; the storage receipt itself is not exposed.
It is not an HTTP or production-ingress API; mutation-audit reconciliation
remains a prerequisite for production enablement under ADR-022.

## Authorization (ADR-025, Group C)

The Knowledge Graph Query API (`emg_knowledge_graph_api`) enforces
authorization on every route, in addition to the existing authentication
and tenant-resolution it already performed (Sprint 7.4). This section
documents the operational requirements; see
`docs/architecture/EMG_ADR-025_KNOWLEDGE_GRAPH_TENANT_AUTHORIZATION_MODEL.md`
for the full design rationale.

**Mechanism.** Authorization is enforced entirely in the HTTP layer
(`emg_knowledge_graph_api/authorization.py`, wired into
`routers/knowledge_graph.py`), reusing the platform's existing Policy
Enforcement Point contract (`emg-auth-client`) and ABAC evaluator
(`emg-policy-engine`) — the same stack `services/identity` uses for its
`GET /authz/check` reference endpoint. No new authorization framework was
introduced, and the Query Engine / domain layer (`emg_knowledge_graph`) has
no authorization concept and was not modified.

**Policy configuration.** `EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH`
(default: `services/knowledge-graph/config/policy.example.yaml`, resolved
relative to the process working directory) points at a
`emg_policy_engine.PolicyConfig` YAML file. The shipped
`config/policy.example.yaml` is **local-development-only, illustrative
configuration** — the same status as `services/identity`'s own
`policy.example.yaml`. **A real deployment must author its own policy file**
and point the environment variable at it (or replace the packaged example
in a custom image build).

**Fail-closed behavior (operationally important).** `PolicyEngine` is
unconditionally default-deny:

- A **missing** policy file is not a startup error — it is treated as an
  **empty ruleset**, which denies every request.
- A **malformed** (present but invalid) policy file *is* a startup error
  (raises during the mandatory startup gate).
- A structurally valid but semantically unsafe policy—such as an unknown
  field, duplicate rule identifier, unknown role, empty allow-list, or
  conditionless rule—is also a startup error.
- **No request is ever silently allowed** due to a configuration problem.

This means a deployment that forgets to supply (or mounts the wrong path
for) its policy file does not fail open — it fails **completely closed**:
every route returns `403 PERMISSION_DENIED` for every caller, including
callers who should legitimately be allowed. This is the correct,
intentional security posture, but it is an operational sharp edge worth
monitoring for (e.g. alert on a sustained 403 rate spike after a
deployment) rather than assuming a quiet deploy means "policy not yet
needed."

**Deployment requirements:**

- `EMG_KNOWLEDGE_GRAPH_API_STORE_BACKEND` accepts only `memory` and
  `postgres`. Unknown values fail validation, and production rejects
  `memory`; local compose values remain development-only.
- The container image must have `config/policy.example.yaml` (or the
  deployment's own policy file) present at the path
  `EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH` resolves to inside the
  running container. `Dockerfile` sets `WORKDIR /app` and copies
  `services/knowledge-graph/config` into the runtime image at that same
  relative path specifically so the packaged example resolves without
  requiring every deployment to override the env var just to get default
  (still dev-only) behavior.
- Before granting any new caller access, verify the caller's `client_id`
  is a real, reviewed, registered EMG service (see "Known limitation"
  below) and that the role(s) it is granted are the minimum required for
  its function — do not grant broad roles (e.g. a baseline "any
  authenticated user" role) merely for convenience.
- `docker-compose.yml`'s `knowledge-graph` service does not set
  `EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH` explicitly; it relies on the
  packaged example via the `Dockerfile` change above.

**Client allow-list (updated).** `TenantServiceTokenValidator` (`authn.py`)
now checks an inbound service token's `azp`/`client_id` against
`_RECOGNIZED_CLIENTS` and requires the registered roles for that client, in the
same shape as `services/audit` and `services/identity`. The broader
platform-wide client-registry follow-up remains recorded in
`docs/architecture/EMG_PRODUCTION_READINESS_ROADMAP.md`.

## Schema negotiation (ADR-033)

The production schema catalog is the reviewed, immutable artifact at
`services/knowledge-graph/config/schema-catalog.json`. ADR-033 Phase 3 ships
canonical version `2.1.0` under catalog generation `catalog-v2.1.0-gen1`.
It contains only that Published, Strict version and therefore uses identity
canonicalization; the production normalizer registration set is empty.

The production image packages the catalog and sets
`EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH` to its in-container location.
Startup loads and validates the catalog, runs the normalizer boot gate, and
fails before serving traffic if the artifact is missing, malformed, or
inconsistent. Production never falls back to the unconfigured placeholder.
The placeholder remains available only through explicit opt-in in an
explicitly identified development or test environment and rejects every
negotiation.

Deployments replacing the packaged catalog must point
`EMG_KNOWLEDGE_GRAPH_API_SCHEMA_CATALOG_PATH` at a version-controlled,
read-only artifact and redeploy the service; catalogs are never reloaded or
mutated at runtime. `Preferred-Schema-Version` remains mandatory on mutation
requests, and successful responses return the same accepted contract in
`Effective-Schema-Version`. Readiness, structured telemetry, and schema
metrics expose the canonical version and catalog generation without exposing
the catalog filesystem path.

## Mutation deployment requirements (ADR-027 Stage 5)

Deploying the five mutation routes requires the realm roles
`knowledge-steward` and `svc-knowledge-graph-writer`, the mutation policy rules
shipped in `config/policy.example.yaml`, and the `tenant_id` and
`classification_clearance` token claims. Full requirements, fail-closed
behaviour, and production prerequisites are documented in
`docs/specifications/ADR-027/ADR-027_STAGE5_DEPLOYMENT_AND_ROLLOUT.md`.

## Governed search operations (ADR-042)

The initial governed-search profile uses a 15-minute cursor TTL, a 30-minute
maximum permitted TTL, a 60-minute guaranteed representation-retention window,
and a 15-minute best-effort cleanup cadence. These are explicit settings:

- `SEARCH_CURSOR_DEFAULT_TTL_SECONDS=900`
- `SEARCH_CURSOR_MAX_TTL_SECONDS=1800`
- `SEARCH_REPRESENTATION_RETENTION_SECONDS=3600`
- `SEARCH_CLEANUP_INTERVAL_SECONDS=900`
- `SEARCH_CLEANUP_BATCH_SIZE=500`
- `SEARCH_CANDIDATE_BATCH_SIZE=200`
- `SEARCH_CANDIDATE_WORK_CEILING=10000`
- `SEARCH_CURSOR_ACTIVE_KEY_ID` and `SEARCH_CURSOR_KEYS_JSON`

Environment variable names use the service's
`EMG_KNOWLEDGE_GRAPH_API_` prefix. Startup rejects non-positive values,
`default TTL > maximum TTL`, `maximum TTL > retention`, malformed key rings,
missing active keys, non-256-bit AES keys, and the committed development key
identifier in production. Issuance uses the active key. There is no fixed prior
key count: every prior entry carries `status`, `retired_at`, and `accept_until`;
startup rejects an acceptance window shorter than the 60-minute retention
contract, a disabled key whose window is still open, or missing material for an
unexpired key. Once `accept_until` has passed, material may be removed and the
key fails closed. Production key material belongs in the approved
secret-injection path, never source control.

Candidate batch size and candidate-work ceiling are tunable internal safeguards,
not request parameters, response fields, ranking inputs, or public search
semantics. Their hard maxima are 1,000 and 10,000 respectively. Reaching the
ceiling fails the entire request generically without returning partial items,
counts, a cursor, or the number of candidates scanned or denied.

Every new revision transaction writes a hash- and node-count-verifiable search
manifest, entity documents, and normalized terms. The prior manifest becomes
eligible for retirement 60 minutes after it ceases to be current. Cleanup only
deletes expired manifests (cascading their derived rows). Each invocation repairs
at most `SEARCH_CLEANUP_BATCH_SIZE` unscheduled rows and deletes at most that many
expired rows using `SKIP LOCKED`; delayed or failed cleanup keeps excess data and
does not fail search. There is no fixed retained revision count. A missing or
unverifiable pinned representation fails a continuation without moving it to the
current head.

Operations should instrument manifest, document, and term rows by tenant and
revision, retained revision count, retirement lag, cleanup failures, and table
or index bytes where available. Alert when retained search storage within the
window exceeds twice the expected current-head footprint. This is an alerting
threshold only and must never trigger deletion needed by a valid cursor.
