# services/knowledge-graph

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
  (raises `pydantic.ValidationError` when the policy dependency is first
  resolved).
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

**Known limitation (flagged, not fixed by this change):** unlike
`services/audit`'s `_RECOGNIZED_CLIENTS` or `services/identity`'s
`SERVICE_REGISTRY`, this service's `TenantServiceTokenValidator`
(`authn.py`) does not check an inbound service token's `client_id` against
any allow-list — any validly-signed token for the configured Keycloak
realm/audience is accepted, and no service client is currently registered
anywhere specifically as a Knowledge Graph API consumer. Policy rules
granting a role (e.g. `service-account`) therefore grant that access to
*any* service holding that realm role, not to a specifically reviewed
Knowledge Graph consumer. Introducing a registry-based allow-list, mirroring
`identity`/`audit`, is a follow-up task outside this ADR's authorized scope.

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
