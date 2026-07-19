# EMG™ Enterprise Memory Graph — Architecture Review & Production Roadmap

**Reviewer role:** Chief Software Architect / Principal Engineer / CTO
**Date:** 2026-07-18
**Repository:** `emg-platform` (monorepo)
**Scope reviewed:** entire tree — 15 shared libraries (~24,500 LOC), 2 live services, 5 scaffold services, infra, observability, docs, tooling, CI, tests, packaging.
**Method:** direct inspection. No assumptions. Findings are grounded in files actually read; where something is unverified, it is labelled as such.

> **How to read this document.** Sections 1–21 are the honest assessment. Sections 22–50 are the target architecture and recommendations. The final part is a phased, approval-gated execution plan. Nothing in this review commits, pushes, merges, or fabricates implementation. Grand claims are avoided; every "missing" item below was confirmed missing by inspection, not guessed.

---

## 0. A blocking finding that must be read first

> **STATUS UPDATE (2026-07-18): RESOLVED.** The repository has been permanently relocated to `/Users/mak/Developer/emg-platform` (outside any cloud-synced tree), the `.venv` was recreated on Python 3.10, bootstrap completed, all editable package imports resolve cleanly, and pre-commit hooks are installed — verified from the new path (`git`: on `develop`, clean, up to date with `origin/develop`). The root cause below is retained for the record. **One residual item remains for Phase 0:** the eight now-**empty** iCloud conflict-copy directories (`libs/python 3`, `services/audit 3`, …) travelled with the move; they are harmless (empty, untracked, cannot shadow packages) but should be removed and guarded against in `.gitignore`.

The repository previously lived at `~/Documents/GitHub/emg-platform`, inside a directory tree that **macOS iCloud Drive ("Desktop & Documents Folders") was actively syncing.** This is not a code problem, but it is corrupting the engineering environment in two proven ways:

1. **iCloud conflict-copy directories are polluting the source tree.** Inspection found eight duplicate directories created by iCloud's conflict resolution:
   `libs/python 3`, `services/ai-orchestration 3`, `services/audit 3`, `services/authz 3`, `services/decision-intelligence 3`, `services/identity 3`, `services/knowledge-graph 2`, `services/retrieval 2`. These are byte-copies iCloud made when it saw concurrent writes. They are not tracked intentionally and will silently shadow or duplicate real packages.

2. **iCloud is setting the `UF_HIDDEN` BSD file flag on files as it materialises them** — which is the exact root cause of the "`Skipping hidden .pth file`" failure diagnosed in the previous investigation. CPython's `site.py` `addpackage()` skips any `.pth` whose inode carries `UF_HIDDEN`, with no relation to the filename. That is why *every* `.pth` was skipped, including third-party `distutils-precedence.pth`: the hidden bit was applied at the filesystem level to files inside `site-packages`, which itself sits under the iCloud-managed tree.

**This single environmental fact explains the entire multi-day debugging saga.** The packaging, hatchling config, editable installs, and `.pth` contents were all correct the whole time. No amount of Python or packaging change can fix a filesystem attribute that an external sync daemon re-applies.

**Immediate remediation (Phase 0, before anything else):** move the working tree out of any cloud-synced location (e.g. `~/dev/emg-platform` or `~/src/emg-platform`), re-create the `.venv` there, and clear stray flags with `chflags -R nohidden .venv`. Delete the eight conflict-copy directories after confirming they contain no unique work. A repository of this ambition must never live inside iCloud/Dropbox/OneDrive-synced folders — those tools race the filesystem against git, node, and pip and will keep corrupting venvs and `.pth` files indefinitely. This is captured as a permanent guardrail in Section 23.

---

## 1. Executive Summary

EMG is an unusually **well-engineered library core** wrapped around a **largely unbuilt platform**. The shared-library layer (ontology, knowledge pipeline, knowledge lifecycle, trust scoring, semantic layer, connectors, memory graph) is genuinely high quality: deterministic, immutable, strictly typed, ~984 tests passing, contract-first, with disciplined provenance and evidence modelling. This is the hard, defensible part and it is already better than most enterprise codebases.

However, EMG is **not yet a platform**. It is a set of composable domain libraries plus two thin services (identity, audit). Everything that turns libraries into a product — persistence, live services, APIs, search, a UI, multi-tenancy, authorization enforcement, eventing, observability, CI/CD, and cloud deployment — is either a scaffold, a placeholder directory, or absent. To compete in the enterprise organizational-memory category, the work ahead is roughly **80% platform engineering on top of a 20% domain core that is already strong.**

The strategic recommendation: **do not rewrite the core.** Preserve the library-first architecture and deterministic discipline exactly as-is. Build the platform *around* it in disciplined phases, resolving the environment/CI foundation first, then persistence, then services and APIs, then search and AI, then UX and multi-tenancy. A realistic path to a credible v1.0 (single-tenant, cloud-deployable, with persistence, core APIs, search, and a minimal UI) is a multi-quarter effort, not a single sprint.

**Overall production readiness today: ~2/10.** Core-library maturity: ~8/10. The gap between those two numbers is the entire roadmap.

---

## 2. Current Repository Health

| Dimension | State | Evidence |
|---|---|---|
| Shared libraries | **Strong** | 15 packages, ~24.5k LOC, pydantic v2 frozen models, deterministic IDs, 984 tests |
| Live services | **Minimal** | Only `identity` (21 py files) and `audit` (12 py files) are real; both thin |
| Scaffold services | **Empty** | `ai-orchestration`, `authz`, `decision-intelligence`, `knowledge-graph`, `retrieval` — zero `.py` in `src/` |
| Frontend (`apps/`) | **Absent** | Only `.gitkeep` + README |
| Infrastructure (`infra/`) | **Placeholder** | All `.gitkeep` + README; no real Terraform/K8s manifests |
| Observability | **Placeholder** | All `.gitkeep` + README; no dashboards/alerts wired |
| CI/CD | **Absent** | No `.github/workflows/ci.yml` (referenced in docs, does not exist) |
| Persistence | **None wired** | docker-compose declares Postgres/Redis/Neo4j/Qdrant/Keycloak; nothing binds to them |
| Packaging/tooling | **Good, now stable** | hatchling pinned, `dev-mode-dirs` explicit, bootstrap idempotent |
| Environment hygiene | **Compromised** | iCloud sync corrupting `.venv` and creating conflict-copies (Section 0) |
| Documentation | **Excellent for a library, thin for a platform** | 30+ engineering docs, per-sprint status, ADR-style design docs |
| Test discipline | **Strong** | >95% coverage on memory-graph, deterministic, adversarial + performance categories |

**Net:** the *code you have* is production-grade; the *system you need* is mostly not yet present.

---

## 3. Architecture Review

The architecture is **library-first / contract-first**, and this is the right choice for this domain. Structure:

- `libs/python/*` — 15 shared libraries, each an independent hatchling package with `src/` layout, its own tests, and dependency-by-name on siblings. Clean separation: `emg-common-types`, `emg-errors`, `emg-telemetry`, `emg-api-contracts`, `emg-ontology`, `emg-knowledge-pipeline`, `emg-knowledge-lifecycle`, `emg-trust-scoring`, `emg-semantic-layer`, `emg-connectors`, `emg-memory-graph`, plus audit/auth client libs and policy engine.
- `services/*` — intended live services; only identity and audit are implemented.
- `apps/`, `infra/`, `observability/` — reserved, effectively empty.

**Key architectural strengths (real):** deterministic content-addressed identity, immutability by default (pydantic frozen), evidence/provenance as first-class and mandatory, temporal (never-overwrite) modelling, and composition-over-duplication (memory-graph *wraps* trust-scoring and semantic-layer rather than reimplementing them).

**Key architectural gap (structural):** there is **no runtime substrate.** The libraries model knowledge perfectly but nothing persists it, serves it, secures it at runtime, or emits/consumes events. The system is a beautifully specified engine with no chassis, wheels, or fuel line yet.

---

## 4. Strong Parts

1. **Deterministic, immutable domain model.** Frozen pydantic v2 everywhere, SHA-256 content addressing, no wall-clock in logic. This makes the system testable, reproducible, and auditable — exactly what an enterprise memory system needs.
2. **Evidence & provenance are mandatory and immutable.** Every assertion is evidence-linked. This is the product's defensible moat versus generic document stores.
3. **Temporal correctness.** Half-open validity intervals, never-overwrite history, historical reconstruction. Most competitors bolt this on later and get it wrong.
4. **Composition discipline.** Memory-graph composes five libraries without duplicating them. Low duplication overall (grep found no `TODO/FIXME/HACK` markers in `src`).
5. **Deterministic entity resolution** (union-find, near-linear) with a documented ML-ready extension seam — pragmatic and future-proof.
6. **Testing culture.** 984 tests, importlib mode, adversarial + performance + integrity categories, >95% coverage targets enforced.
7. **Documentation culture.** Design docs per sprint, data-model docs, integration docs, a technical-debt register, a roadmap. Rare and valuable.

---

## 5. Weak Parts

1. **No persistence layer.** The single largest gap. Everything is in-memory; nothing survives a process restart.
2. **No live service surface** for the core domain (knowledge-graph, retrieval, decision-intelligence, authz are empty scaffolds).
3. **No API gateway / public API / SDK.**
4. **No frontend of any kind.**
5. **No CI/CD** — quality gates exist as scripts but nothing enforces them on push/PR.
6. **Authorization is advisory, not enforced.** Classification *filtering* exists; clearance-based *enforcement* does not (documented in the debt register).
7. **No multi-tenancy** model anywhere.
8. **Environment fragility** (iCloud) actively corrupting local dev.
9. **Duplicate scaffold directories** (`services/*/`) from iCloud conflicts — repository hygiene risk.
10. **Single-process, single-timeline assumptions** baked into the graph engine — fine for a library, insufficient for a platform without an explicit persistence/concurrency story.

---

## 6. Technical Debt

The repository already maintains an honest `TECHNICAL_DEBT.md`. The material items, confirmed by inspection:

- **INT (integration/wiring):** no persistence binding; no live graph service; trust engine not wired into ingestion; no concrete connectors; no vector/search binding.
- **LIM (functional limits):** executor does not execute traversals (delegated); classification enforcement absent; in-memory single-process engine; single-timeline temporal model.
- **DX/CI:** no CI workflow; mypy `--strict` not wired into `make lint`; ruff/black version skew between pre-commit and dev; empty duplicate scaffold dirs; no dependency lock file.
- **QA:** performance tests are budget-based, not benchmarked; no persistent-store contract tests.

To this I add two newly-found items: **(a) iCloud-induced filesystem corruption of `.venv`/`.pth`**, and **(b) eight conflict-copy directories** that must be removed. Both are P0 environment debt.

---

## 7. Missing Components

Runtime graph store · event bus · API layer · search/index subsystem · embedding/vector service · background job/worker system · outbox/CDC · schema-migration system · secrets management · config service · tenancy/isolation layer · rate limiting · caching layer · feature flags · SDKs · admin/user web apps · mobile surface · deployment manifests · CI/CD pipelines · SSO/OIDC integration wiring (Keycloak declared, unused).

---

## 8. Missing APIs

No REST or GraphQL surface exists for the core domain. Needed: Graph write/ingest API; Graph query API (who-approved/why/lineage/evidence); Temporal query API; Decision-lineage API; Evidence API; Search API; Admin API (tenants, users, roles, connectors); Webhooks/Events API; Health/readiness/metrics endpoints. `emg-api-contracts` exists as a library — the contracts are partly modelled — but nothing serves them.

---

## 9. Missing Services

Of seven declared services, five are empty scaffolds and must be built: **knowledge-graph** (persistence + graph API — highest priority), **retrieval** (search/RAG), **authz** (policy enforcement point / PDP), **decision-intelligence** (analytics over lineage), **ai-orchestration** (LLM/agent orchestration). A **gateway/BFF** service is also missing entirely.

---

## 10. Missing UI

Everything. No web app, no design system, no component library, no auth flow, no graph explorer, no decision-timeline view, no evidence viewer, no admin console, no executive dashboard. `apps/` is empty. This is a full greenfield frontend program.

---

## 11. Missing Security

- **Authentication:** identity service exists but no end-to-end OIDC/SSO wiring to Keycloak; no session/token lifecycle at platform level.
- **Authorization:** no runtime PDP; classification enforcement absent; no ABAC/RBAC engine wired (policy-engine library exists, unused at runtime).
- **Multi-tenant isolation:** none.
- **Secrets management:** `.env` files only; no vault integration.
- **Data protection:** no encryption-at-rest strategy documented for the (nonexistent) stores; no field-level encryption for sensitive evidence.
- **Audit at platform scope:** audit service exists but is not the spine of every mutation yet.
- **Supply chain:** no lock file, no SBOM, no signed builds, `pip-audit` present but not enforced in CI.

---

## 12. Missing Enterprise Features

Multi-tenancy · org hierarchy & delegation · SSO/SCIM provisioning · fine-grained permissions · data residency / air-gapped deployment (declared in `infra/environments/air-gapped-production` but empty) · retention & legal hold · e-discovery export · compliance reporting (SOC2/ISO/GDPR tooling) · usage metering & billing · admin portal · SLAs/quotas · white-labelling · public API keys & developer portal.

---

## 13. Performance Risks

- **In-memory graph** will not scale past a single process's RAM; large tenants will OOM. Needs a real graph store (Neo4j is already declared in compose).
- **Rebuild-on-read** patterns in the builder are fine for library scale, risky at platform scale without incremental persistence.
- **No caching tier**; every query recomputes.
- **Performance tests are budget-based**, not benchmarked against realistic data volumes — real p95/p99 characteristics are unknown.

---

## 14. Scalability Risks

- **No horizontal scaling story** — the engine is single-process and stateful.
- **No sharding/partitioning by tenant.**
- **No async/event backbone** to decouple ingestion from query.
- **No back-pressure / queueing** for connector ingestion bursts.
- **Single-timeline temporal model** may need per-branch/per-tenant timelines at scale.

---

## 15. AI Readiness

**Deliberately and correctly ML-free at the core** — determinism is a feature, not a gap. The architecture is *AI-ready* via clean seams: the `Resolver` protocol for ML-assisted entity resolution, the semantic layer for retrieval, evidence linking for grounding. What's missing for an AI-first product: an embedding/vector service (Qdrant is declared, unused), a retrieval/RAG service, an `ai-orchestration` service for LLM/agent workflows, and a grounding contract that forces AI answers to cite EMG evidence. The right posture: **keep the memory core deterministic; add AI as a grounded consumer layer, never inside the source of truth.**

---

## 16. Cloud Readiness

Low today. Positives: 12-factor-friendly config via `.env`, docker-compose for local infra, `infra/environments` structure anticipating local/dev/staging/prod/air-gapped. Gaps: no Dockerfiles for most services (only identity/audit have them), no Kubernetes manifests, no Helm charts, no Terraform, no image build pipeline, no registry strategy, no health/readiness probes standardized.

---

## 17. Production Readiness

~2/10. No persistence, no CI, no deployment, no runtime auth enforcement, no observability wiring, environment corruption. The core libraries are production-grade; the *system* is pre-alpha.

---

## 18. Deployment Readiness

Not deployable as a platform. Two services containerize; five don't exist. No orchestration manifests, no pipeline, no environment promotion flow. docker-compose is a local-dev convenience only.

---

## 19. Code Quality Review

**High.** ruff (E/F/I/UP/B/SIM), black, mypy `--strict`, line-length 100, py310 target, pydantic v2 frozen models, no debt markers in `src`, disciplined naming, thorough docstrings. Improvements: wire mypy `--strict` into `make lint` (currently not enforced there); resolve ruff/black version skew between pre-commit and dev; add a lock file; remove iCloud conflict-copy dirs.

---

## 20. Testing Review

**Strong for libraries.** 984 tests, importlib mode, per-category suites (unit/integration/builder/resolution/temporal/evidence-integrity/lineage/traversal/query/versioning/performance/adversarial), >95% coverage on new work. Gaps: no service-level integration tests against real stores (because stores aren't wired), performance tests are budget-based not benchmarked, no end-to-end/contract tests across service boundaries (no services), no load/soak tests, no security tests (authz/tenant-isolation).

---

## 21. Documentation Review

**Excellent engineering documentation, for its stage.** 30+ docs, per-sprint design + status, data-model and integration docs, an honest debt register and roadmap, onboarding guide, coding standards, definition-of-done. Missing for a platform: API reference (no APIs yet), operator/runbook docs, security & compliance docs, SDK docs, deployment guides, architecture decision records as a formal ADR log (design docs are close but not indexed as ADRs).

---

## 22. Priority Matrix

| Priority | Theme | Why |
|---|---|---|
| **P0** | Environment integrity (move off iCloud, remove conflict-copies) + CI foundation | Everything else is unreliable until local + CI environments are deterministic |
| **P0** | Persistence binding for the memory graph (Neo4j + Postgres) | Without durability there is no product |
| **P1** | Knowledge-graph service + core Graph/Query/Evidence APIs | First real platform surface |
| **P1** | Authorization enforcement (PDP) + classification enforcement | Enterprise non-negotiable |
| **P1** | Event backbone + audit-as-spine | Decoupling, integrity, compliance |
| **P2** | Retrieval/search + vector service | Table stakes for "second brain" |
| **P2** | Minimal web app (graph explorer, decision timeline, evidence viewer) | Makes value visible |
| **P2** | Multi-tenancy | Required to sell to more than one org |
| **P3** | AI orchestration (grounded RAG, agents) | Differentiator, built on the above |
| **P3** | Executive dashboards, analytics, SDKs, mobile, marketplace | Expansion |

---

## 23. Immediate Fixes (do now, low risk)

1. ~~**Move the repo out of iCloud**, recreate `.venv`, `chflags -R nohidden .venv`.~~ **DONE** — relocated to `/Users/mak/Developer/emg-platform`; venv recreated on 3.10; imports clean; pre-commit installed.
2. **Delete the eight (now empty) iCloud conflict-copy directories** (`rmdir 'libs/python 3' 'services/'*\ [0-9]` after a final `find … -type f` confirms they are empty). *(Still pending — Phase 0.)*
3. **Add `.github/workflows/ci.yml`** running bootstrap → lint → mypy strict → test → pip-audit on push/PR.
4. **Add a lock file** (`pip-tools`/`uv`) for reproducible installs.
5. **Wire mypy `--strict` into `make lint`.**
6. **Resolve ruff/black version skew** (pin identically in pre-commit and `requirements-dev.txt`).
7. **Add `.gitignore` guards** for `* [0-9]/` conflict-copy patterns and `.venv`.
8. **Permanent guardrail doc:** "never develop inside a cloud-synced folder."

---

## 24. Short-term Roadmap (next quarter)

Persistence binding (Neo4j graph store + Postgres metadata/outbox) → knowledge-graph service exposing Graph/Query/Evidence/Temporal/Lineage APIs → authz PDP with classification enforcement → event backbone (outbox → broker) with audit-as-spine → CI/CD and containerization for all services → first thin web app (graph explorer + decision timeline + evidence viewer).

---

## 25. Long-term Roadmap (12–24 months)

Multi-tenancy & isolation → retrieval/search + vector/embedding service → grounded AI orchestration (RAG + agents that must cite EMG evidence) → executive dashboards & analytics → SDKs (Python/TypeScript) & public API + developer portal → admin/user portals → mobile → integration marketplace (Slack/Teams/Jira/SharePoint/Confluence/Google) → compliance certifications (SOC2/ISO27001/GDPR tooling) → air-gapped & data-residency deployments.

---

## 26. Suggested Architecture

**Hexagonal, event-driven, library-first.** Keep the deterministic domain libraries as the pure core (no I/O). Wrap them in services that own I/O through ports/adapters:

```
        ┌────────────────────────── Clients ──────────────────────────┐
        │  Web app · Admin portal · Mobile · SDKs · Public API · Bots  │
        └───────────────┬──────────────────────────────┬──────────────┘
                        │  (HTTPS / GraphQL / REST)     │
                 ┌──────▼───────┐               ┌───────▼───────┐
                 │  API Gateway │  authn/z, rate limit, tenant  │
                 │     / BFF    │  resolution, audit envelope   │
                 └──────┬───────┘               └───────┬───────┘
        ┌───────────────┼─────────────────┬─────────────┼───────────────┐
   ┌────▼────┐   ┌──────▼──────┐   ┌───────▼──────┐  ┌───▼────┐   ┌──────▼──────┐
   │knowledge│   │  retrieval  │   │   decision-  │  │ authz  │   │     ai-     │
   │ -graph  │   │  (search)   │   │ intelligence │  │ (PDP)  │   │orchestration│
   └────┬────┘   └──────┬──────┘   └───────┬──────┘  └───┬────┘   └──────┬──────┘
        │  (domain libs: ontology, memory-graph, lifecycle, trust, semantic) │
   ┌────▼─────────────────────────────────────────────────────────────────▼───┐
   │  Ports/adapters: GraphStore(Neo4j) · MetaStore(Postgres) · VectorStore    │
   │  (Qdrant) · Cache(Redis) · EventBus(Kafka/NATS) · Outbox · Blob(S3)       │
   └───────────────────────────────────────────────────────────────────────────┘
                         Event backbone (outbox → broker → consumers)
                    Cross-cutting: identity · audit(spine) · telemetry · config
```

**Principles:** domain core stays pure and deterministic; every mutation emits an event and an audit record; every read is authorization-checked; storage is behind ports so Neo4j/Postgres/Qdrant are swappable.

---

## 27. Suggested Folder Structure

Keep `libs/python/*` as-is. Add:

```
services/
  gateway/            # BFF: authn/z, tenant resolution, rate limiting, audit envelope
  knowledge-graph/    # graph persistence + Graph/Query/Evidence/Temporal/Lineage APIs
  retrieval/          # search + vector + RAG grounding
  authz/              # PDP (RBAC/ABAC + classification enforcement)
  decision-intelligence/
  ai-orchestration/
  identity/  audit/   # existing
libs/
  python/*            # existing domain libs
  ts/                 # shared TypeScript types generated from emg-api-contracts
apps/
  web/                # React/Next admin+user portal
  design-system/      # component library + tokens
platform/
  persistence/        # store adapters (neo4j, postgres, qdrant, redis, s3)
  events/             # outbox, broker bindings, event schemas
  migrations/         # schema migrations
infra/
  terraform/  kubernetes/  helm/   # replace placeholder dirs with real manifests
.github/workflows/    # CI/CD
```

---

## 28. Suggested Service Boundaries

- **gateway** — the only public ingress; owns authn, tenant resolution, rate limiting, request-scoped audit envelope. No domain logic.
- **knowledge-graph** — owns the graph store; sole writer of nodes/edges/evidence/versions; exposes graph, query, temporal, lineage, evidence APIs.
- **retrieval** — read-only over the graph + vector index; search & RAG grounding.
- **authz** — PDP; stateless policy decisions (RBAC/ABAC + classification clearance).
- **decision-intelligence** — analytics/reporting over lineage; read-only.
- **ai-orchestration** — LLM/agent workflows; may only answer with EMG-evidence citations.
- **identity / audit** — existing; audit becomes the write-spine every service emits to.

Boundary rule: **one writer per store**; everyone else reads or requests writes via events/APIs.

---

## 29. Suggested Domain Model

The domain model already exists and is strong (14+ node types, evidence, temporal validity, decisions, lineage). Recommendations: **do not change it** for storage reasons; instead add **tenant** and **principal** as first-class cross-cutting dimensions (every node/edge/evidence carries `tenant_id`), and formalize **branch/timeline** identity if per-tenant temporal isolation is needed. Keep everything else exactly as designed.

---

## 30. Suggested Database Strategy

**Polyglot persistence behind ports:**
- **Neo4j** — the graph of record (nodes, edges, lineage traversal). Already in compose.
- **Postgres** — metadata, tenancy, users/roles, connector configs, the **transactional outbox**, and an append-only **evidence ledger** (immutable, hash-chained — reuses the audit design).
- **Qdrant** — vector index for retrieval.
- **Redis** — cache + rate-limit counters + ephemeral job state.
- **S3/blob** — raw source documents backing evidence locators.

**Write path:** domain lib produces immutable objects → knowledge-graph service persists to Neo4j + Postgres in one unit of work → writes an outbox row → outbox relay publishes events. Evidence is never mutated, only appended. Use schema migrations from day one.

---

## 31. Suggested Event Architecture

**Transactional outbox → broker (Kafka or NATS JetStream) → consumers.** Every mutation writes domain state and an outbox event atomically; a relay publishes; consumers (search indexer, analytics, audit, AI grounding cache) subscribe. Events are immutable, versioned, evidence-referencing. This decouples ingestion from query, gives replayability (rebuild any projection from the log), and makes audit the natural spine.

---

## 32. Suggested Memory Graph Architecture

Keep `emg-memory-graph` as the **pure computational core**. Introduce a `GraphStore` port (the library already anticipates this) with a **Neo4j adapter** for durability and an **in-memory adapter** for tests. The service layer loads working subgraphs from Neo4j, runs the deterministic library algorithms, and persists results transactionally. Versioning/snapshots map to Neo4j + an append-only revision log in Postgres. Never put I/O in the library; the library stays deterministic and unit-testable forever.

---

## 33. Suggested AI Architecture

**Grounded, not generative-at-core.** The memory graph remains the deterministic source of truth. AI is a *consumer*: `ai-orchestration` runs RAG and agent workflows that (a) retrieve via the retrieval service, (b) must cite EMG evidence for every claim, (c) never write to the graph without human-approved, evidence-linked provenance. Use the `Resolver` protocol seam for optional ML-assisted entity resolution, gated behind confidence thresholds and always reversible. The product promise — "why was this decided" — is only credible if AI answers are provably grounded in stored evidence.

---

## 34. Suggested Knowledge Graph

Already the crown jewel. Productionize it: persist to Neo4j, expose lineage traversal as an API, index it for search, and enforce classification on every read. Add tenant partitioning. No model redesign needed.

---

## 35. Suggested Search Architecture

Hybrid: **keyword (Postgres FTS or OpenSearch) + vector (Qdrant) + graph-aware ranking.** The retrieval service fuses lexical and semantic recall, then re-ranks using graph signals (recency, evidence strength, decision centrality, trust score). Every result links back to nodes/evidence. This is where "second brain" recall becomes tangible.

---

## 36. Suggested Security Model

Defense in depth: **gateway** (authn, rate limit, tenant scoping) → **authz PDP** (RBAC + ABAC + classification clearance, enforced on every read/write) → **service-to-service auth** (mTLS or signed service tokens; identity service already models service tokens) → **data protection** (encryption at rest, field-level encryption for sensitive evidence, secrets in a vault) → **audit spine** (every action recorded immutably). Make classification *enforcement* (not just filtering) a launch blocker — it's currently the top security debt item.

---

## 37. Suggested Multi-tenancy Strategy

Start with **shared-schema, tenant-scoped rows** (`tenant_id` on every entity, enforced at the persistence and PDP layers) for speed to market; design ports so a **schema-per-tenant** or **DB-per-tenant** isolation tier can be offered to regulated/enterprise customers without domain changes. Neo4j: tenant property + composite indexes initially, database-per-tenant for premium isolation. Air-gapped/data-residency deployments (already anticipated in `infra/environments`) become a single-tenant instantiation of the same stack.

---

## 38. Suggested Permission System

RBAC for coarse roles (viewer/contributor/steward/admin) + ABAC for fine control (attributes: classification, department, evidence-source, tenant). The `emg-policy-engine` library already models policy; wire it into the authz PDP as the decision core. Permissions must cover node/edge/evidence read, graph write, connector management, and admin operations. Decisions are logged to audit.

---

## 39. Suggested Enterprise Dashboard

Operational console for stewards: ingestion health, connector status, graph growth, evidence coverage, unresolved entities, classification distribution, audit stream. Built on the event/analytics backbone.

---

## 40. Suggested Executive Dashboard

Decision-intelligence surface for leadership: "decisions made this quarter and *why*," decision-to-outcome lineage, institutional-memory coverage, risk exposure from policies, knowledge-loss indicators (people who left owning undocumented decisions). This is the board-level value story — build it once decision-intelligence and persistence exist.

---

## 41. Suggested Analytics Platform

Event-sourced projections feeding a warehouse (or Postgres materialized views initially): decision velocity, evidence quality trends, connector coverage, entity-resolution rates, query patterns. Powers both dashboards and product telemetry.

---

## 42. Suggested SDKs

**Python** (wraps the domain libs + API client) and **TypeScript** (generated from `emg-api-contracts`). Both: typed, evidence-first, with a local deterministic mode for testing. Publish to a developer portal.

---

## 43. Suggested APIs

Graph write/ingest · Graph query (who-approved/why/lineage/evidence/historical-owners/affected-projects/shortest-path) · Temporal query · Evidence · Search · Admin (tenants/users/roles/connectors) · Webhooks/Events · Health/metrics. Contract-first from `emg-api-contracts`; REST for CRUD, GraphQL for graph traversal.

---

## 44. Suggested Public APIs

A stable, versioned, rate-limited, key-authenticated subset for partners/integrations: ingest evidence, query decisions, subscribe to events. Backed by a developer portal, OpenAPI spec, and SDKs.

---

## 45. Suggested Admin Portal

Tenant & user management, role assignment, connector configuration & health, classification policy management, audit review, retention/legal-hold controls. Built in `apps/web` on the shared design system.

---

## 46. Suggested User Portal

Graph explorer, decision timeline, evidence viewer, natural-language "why" search (grounded), saved views, notifications. The primary end-user value surface.

---

## 47. Suggested Mobile Support

Deferred. When justified: read-first (search, decision lookup, notifications, approvals) via the public API; native or React Native on the same SDK. Do not build until web is proven.

---

## 48. Suggested Integrations

Connector framework (`emg-connectors`) already exists — build concrete connectors: Slack, Teams, Jira, Confluence, SharePoint, Google Workspace, Notion, email. Each maps source records to evidence with provenance. Prioritize by where decisions actually happen (Slack/Teams/Jira first).

---

## 49. Suggested AI Agents

Grounded agents on `ai-orchestration`: a "why" agent (answers decision-rationale questions with citations), an ingestion agent (proposes entity resolutions for human approval), a stewardship agent (flags undocumented decisions / knowledge-loss risk). All must cite evidence and route writes through human approval. Never autonomous mutation of the source of truth.

---

## 50. Final Production Roadmap

A credible path to **v1.0 = single-tenant, cloud-deployable, persistent, with core Graph/Query/Evidence/Search APIs, authz enforcement, audit spine, and a minimal web app.** Multi-tenancy, AI orchestration, dashboards, SDKs, and marketplace are **post-1.0**. Phases below.

---

# Part II — Phased Execution Plan

Each phase lists objective, deliverables, repo changes, tests, docs, complexity (S/M/L/XL), risk, and enterprise value. **Phases are approval-gated: one phase at a time, verified green, nothing merged without review.** No placeholders, no fabricated implementations, no skipped tests — consistent with this repo's existing standards.

### Phase 0 — Environment & CI Foundation *(complexity M, risk Low, value High — unblocks everything)*
- **Objective:** deterministic local + CI environments.
- **Deliverables:** repo moved off iCloud; conflict-copies removed; `.github/workflows/ci.yml` (bootstrap→lint→mypy strict→test→pip-audit); dependency lock file; mypy wired into `make lint`; ruff/black version alignment; `.gitignore` guards; guardrail doc.
- **Tests:** CI runs the full 984-test suite on every push/PR.
- **Docs:** update onboarding with the "never develop in cloud-synced folders" guardrail.

### Phase 1 — Platform Foundation *(M, risk Low, value High)* — ✅ COMPLETE (2026-07-19)
- **Re-sequencing note:** the original roadmap merged "foundation" and "persistence" into one XL Phase 1. Under the Phase 1 constraints (foundation only; preserve all tests/behaviour; no breaking changes), these were split: Phase 1 delivers the *storage seam* (ports + in-memory adapter) + identity value types + the TD-001 typecheck gate; **real Neo4j/Postgres binding moved to Phase 2** (below). Grounded in Freeze §32 (port + in-memory adapter now; Neo4j "for durability" next). Ordering change only — no frozen boundary altered.
- **Delivered:** `libs/python/emg-platform-core` — `GraphStore`/`GraphTransaction` ports, `InMemoryGraphStore`, `TenantId`/`PrincipalRef`/`WriteReceipt`; `make typecheck` (per-package mypy) + CI job (TD-001 resolved); docs (`platform-foundation-architecture.md`, `storage-ports.md`).
- **Validated:** ruff/black clean (315 files); pytest **1024 passed / 16 skipped** (984 preserved + 40 new); mypy --strict clean on 18 packages; new package **100% coverage**; setup-check OK. Purely additive — zero existing source changed.

### Phase 2 — Persistence Binding *(XL, risk Med, value Critical)*
- **Objective:** durable memory graph.
- **Deliverables:** Neo4j adapter + Postgres metadata/outbox/evidence-ledger behind the Phase 1 `GraphStore` port; migrations; transactional write path; `tenant_id`/`principal` retrofit onto domain models; store contract tests (in-memory ↔ Neo4j parity).
- **Tests:** store contract tests, migration tests, integrity tests against a real Postgres/Neo4j in CI (docker services).
- **Docs:** persistence architecture, data-model-to-store mapping, ADR.

*(Subsequent phases 3–8 renumber accordingly; scope unchanged. The Roadmap ⇄ Freeze reconciliation table above still holds — only the persistence work shifts from "Phase 1" to "Phase 2".)*

### Phase 2 — Knowledge-Graph Service + Core APIs *(XL, risk Med, value Critical)*
- **Objective:** first real platform surface.
- **Deliverables:** `knowledge-graph` service (FastAPI); Graph/Query/Temporal/Lineage/Evidence APIs from `emg-api-contracts`; health/readiness/metrics; Dockerfile.
- **Tests:** API contract tests, integration tests against persisted stores, auth-guard tests (stub PDP).
- **Docs:** API reference, service runbook.

### Phase 3 — Authorization Enforcement + Audit Spine *(L, risk Med, value Critical)*
- **Objective:** enterprise security floor.
- **Deliverables:** `authz` PDP (RBAC+ABAC+classification enforcement) wiring `emg-policy-engine`; every read/write authorization-checked; audit envelope on every mutation.
- **Tests:** authorization matrix tests, classification-enforcement tests, tenant-scoping tests, audit-completeness tests.
- **Docs:** security model, permission model, compliance mapping.

### Phase 4 — Event Backbone *(L, risk Med, value High)*
- **Objective:** decouple ingestion from query; enable projections.
- **Deliverables:** outbox relay → broker (NATS/Kafka); versioned event schemas; search-indexer + analytics consumers scaffolding.
- **Tests:** outbox atomicity, replay/rebuild tests, consumer idempotency tests.
- **Docs:** event architecture, event schema registry.

### Phase 5 — Retrieval & Search *(L, risk Med, value High)*
- **Objective:** "second brain" recall.
- **Deliverables:** `retrieval` service; Qdrant vector adapter; hybrid keyword+vector+graph ranking; Search API; embedding pipeline as an event consumer.
- **Tests:** ranking-quality fixtures, recall/precision harness, evidence-linkage on every result.
- **Docs:** search architecture.

### Phase 6 — Minimal Web App *(XL, risk Med, value High — makes value visible)*
- **Objective:** first end-user surface.
- **Deliverables:** `apps/web` (Next.js) + `design-system`; auth flow via identity/gateway; graph explorer, decision timeline, evidence viewer, grounded "why" search; generated TS SDK from contracts.
- **Tests:** component tests, e2e (Playwright) against a seeded stack.
- **Docs:** frontend architecture, design-system docs.

### Phase 7 — Gateway + Multi-tenancy *(L, risk Med, value High)*
- **Objective:** sell to more than one org.
- **Deliverables:** `gateway`/BFF (authn, tenant resolution, rate limiting); `tenant_id` end-to-end; shared-schema isolation enforced at persistence + PDP; per-tenant config.
- **Tests:** cross-tenant isolation tests (must prove no leakage), rate-limit tests.
- **Docs:** multi-tenancy strategy, isolation guarantees.

### Phase 8 — v1.0 Hardening *(L, risk Low, value Critical)*
- **Objective:** production launch readiness.
- **Deliverables:** K8s/Helm manifests replacing infra placeholders; observability wiring (dashboards/alerts); load/soak tests; security review; SBOM + signed builds; runbooks; SLOs.
- **Tests:** load, soak, chaos-lite, security/pen-test checklist.
- **Docs:** deployment guide, operations runbooks, SLO/SLA docs.

### Post-1.0 (sequenced later): AI orchestration (grounded RAG + agents) → executive/analytics dashboards → SDKs + public API + developer portal → admin/user portal depth → concrete connector marketplace → mobile → compliance certifications → air-gapped/data-residency GA.

---

## Roadmap ⇄ Product Freeze reconciliation (added 2026-07-18)

The **Product Architecture Freeze** (`EMG_PRODUCT_ARCHITECTURE_FREEZE.md`, v1.0-FROZEN) is now the authoritative product baseline. The phases above are confirmed to conform to it, with these bindings made explicit:

| Freeze concept | Realised by phase |
|---|---|
| MVP definition (§24) | Phases 1–2 + minimal slice of 6 (single-tenant, graph+query+evidence, keyword search, thin web app) |
| v1.0 definition (§25) | Phases 1–8 complete (persistence, APIs+SDKs, hybrid search, PDP+RBAC, events+audit spine, gateway+SSO, dashboards-basic, hardening) |
| Bounded contexts (§10) & service boundaries (§11) | Phase 2 (knowledge-graph), 3 (authz), 4 (events), 5 (retrieval), 7 (gateway) |
| Permission model (§16) + classification enforcement launch-blocker (§22) | Phase 3 (RBAC now; ABAC/classification enforced on the Enterprise track) |
| Multi-tenancy model (§17) | Phase 7 (shared-schema baseline; isolation tiers post-v1.0) |
| Event taxonomy (§13) | Phase 4 |
| Deployment models (§8) | Phase 8 (Helm; on-prem path); air-gapped GA is v2.0 |
| AI agent strategy (§21) | Post-1.0 (grounded consumer layer, never before persistence + evidence APIs exist) |
| Executive dashboard (§23) | Post-1.0 (requires decision-intelligence + analytics projections) |
| Editions & licensing (§6–7) | Feature-flagged across all phases; no forks |

**Two freeze-driven adjustments to the plan:**
1. `tenant_id` and `principal` provenance (Freeze §9) are introduced as **additive fields in Phase 1**, not retrofitted in Phase 7 — cheaper to carry from the first persisted write than to backfill.
2. **Classification enforcement** is elevated from "P1 debt" to a **v1.0 Enterprise-track launch blocker** (Freeze §16/§22), scheduled in Phase 3 rather than deferred.

No phase contradicts the freeze; the freeze does not introduce work outside the eight phases. Implementation may now proceed, Phase 0 first.

---

## How I will execute (and where I need you)

As acting CTO I will not fake this. Three honest constraints shape execution:

1. **Phase 0's environment blocker is now cleared.** The repository has been relocated off iCloud to `/Users/mak/Developer/emg-platform`, the venv is rebuilt on 3.10, and imports resolve cleanly — so the recurring corruption is behind us. What remains of Phase 0 (empty-dir cleanup, `.gitignore` guards, CI workflow, lock file, mypy-in-lint, ruff/black alignment, guardrail doc) is entirely mine to implement and carries no source-logic risk.

2. **This is quarters of work, not one turn.** Anyone promising to "implement everything to v1.0" in a single pass would be fabricating. I'll implement **one phase at a time**, each with real code, real tests, real docs, verified green, and stop for your review before the next — exactly the discipline that produced your 984 passing tests. Nothing gets committed, pushed, or merged without your explicit go-ahead.

3. **The core doesn't need rescuing — the platform needs building.** The most valuable thing I can protect is the deterministic, evidence-first library core. Every phase above builds around it without touching its purity.

Tell me to proceed with **Phase 0** (I'll produce the CI workflow, lock file, `.gitignore` guards, mypy-in-lint wiring, version alignment, and the guardrail doc now — all safe, no source-logic changes), or point me at whichever phase you want to start with, and I'll begin implementing it properly.
