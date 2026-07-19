# EMG™ — Product Architecture Freeze (v1.0-FROZEN)

**Status:** FROZEN — authoritative product & architecture baseline
**Date:** 2026-07-18
**Owner:** Office of the CTO / Chief Architect
**Supersedes for product scope:** `EMG_PRODUCT_VISION.md` (kept as narrative; this document governs)
**Relationship to engineering:** the `docs/architecture/EMG_Engineering_Backlog` remains the feature/epic system of record; this freeze defines the *product shape* those features must add up to. Where they diverge, this freeze wins on **product scope and boundaries**, the Backlog wins on **feature IDs and sequencing**.

> **Purpose of a freeze.** Before any infrastructure is built, the target must stop moving. This document fixes what EMG *is*, who it's for, how it's edition-ed and deployed, its bounded contexts, domain model, security and tenancy models, and the exact line between MVP, v1.0, and v2.0. After this is frozen, the roadmap is updated to conform, and only then does implementation begin. Changing anything in this document after freeze requires an explicit "unfreeze" decision and a version bump.

> **Grounding note.** Entity lists, the connector/plugin model, the policy engine, the audit spine, and the deterministic memory graph below are **not aspirational** — they reflect libraries that already exist in `libs/python/*` (ontology, memory-graph, knowledge-lifecycle, trust-scoring, semantic-layer, connectors, policy-engine, audit). The freeze defines the product *around* that real core.

---

## 1. Product Definition

**EMG (Enterprise Memory Graph) is the system of record for organizational memory** — the durable, queryable, evidence-linked graph of an organization's decisions, the context behind them, the people and projects they touch, and the institutional knowledge that normally evaporates when people leave.

It is **not** a document management system, **not** a wiki, **not** a generic knowledge base, and **not** a chatbot. Those store *artifacts*. EMG stores *why* — decisions, their evidence, their lineage, their owners, and their temporal truth — and lets an organization ask, at any future moment, "why did we decide this, who decided it, on what evidence, and what changed since?"

**One-sentence definition:** EMG is a deterministic, evidence-first, temporal knowledge graph that preserves and makes queryable the decision-level memory of an enterprise, with AI as a *grounded consumer* — never as the source of truth.

**Three product pillars (frozen):**
1. **Memory** — decisions, evidence, context, ownership, and relationships, never overwritten, always reconstructable to any point in time.
2. **Explainability** — every stored assertion is evidence-linked and auditable; every AI answer must cite that evidence.
3. **Governance** — classification, provenance, access control, and immutable audit are structural, not optional.

---

## 2. Target Customers

Frozen priority order (regulated + high-consequence first, where decision memory is legally and operationally critical):

1. **Government & public sector** — decision accountability, FOIA/e-discovery, continuity across administrations.
2. **Defense & aviation** — safety-critical decision lineage, air-gapped operation, chain-of-custody.
3. **Banking & financial services** — regulatory audit, model/decision governance, risk lineage.
4. **Healthcare & life sciences** — clinical/operational decision provenance, compliance.
5. **Energy & utilities** — long-lived asset decisions, regulatory memory.
6. **Large enterprises (10k+)** — institutional memory, M&A knowledge retention, reduced key-person risk.

**Deliberately deprioritized for v1.0:** SMB, consumer, and unregulated startups. EMG's value scales with organizational memory loss cost, which is highest in large, regulated, long-lived institutions.

---

## 3. Enterprise Use Cases (frozen canonical set)

1. **Decision rationale recall** — "Why did we choose vendor X in 2023, who approved it, on what evidence?"
2. **Knowledge-loss mitigation** — surface decisions owned by departing employees that lack documented rationale.
3. **Audit & compliance** — produce the immutable evidence chain behind any decision for regulators.
4. **Onboarding & context transfer** — new leaders inherit the *why*, not just the *what*.
5. **Risk & policy lineage** — trace which decisions a policy affected and which risks flow from it.
6. **M&A / reorg continuity** — preserve institutional memory through structural change.
7. **Cross-silo decision discovery** — find related decisions made independently across departments.
8. **Temporal reconstruction** — see the organizational state and ownership as it was on any historical date.

---

## 4. User Personas (frozen)

| Persona | Role | Primary need | Key surface |
|---|---|---|---|
| **Executive / Decision-maker** | VP, C-suite, agency head | "Why + who + when" at a glance; risk & knowledge-loss visibility | Executive dashboard |
| **Knowledge Steward** | Records/knowledge manager | Curate, resolve entities, ensure evidence coverage | Admin/steward console |
| **Analyst / Investigator** | Compliance, audit, risk | Deep lineage traversal, evidence export | Graph explorer, evidence viewer |
| **Contributor** | Any employee | Capture decisions/evidence with low friction | Connectors + light capture UI |
| **Auditor / Regulator** (external) | Oversight body | Immutable, exportable evidence chains | Scoped audit export API/portal |
| **Platform Admin** | IT / security | Tenants, SSO, roles, connectors, policy | Admin portal |
| **Developer / Integrator** | Partner engineer | Build on EMG data | Public API + SDKs |
| **AI Agent** (non-human) | Grounded assistant | Retrieve + answer with citations | ai-orchestration, retrieval |

---

## 5. Feature Matrix (by edition)

| Capability | Community | Professional | Enterprise |
|---|:--:|:--:|:--:|
| Deterministic memory graph (core) | ✅ | ✅ | ✅ |
| Evidence linking & provenance | ✅ | ✅ | ✅ |
| Temporal history & reconstruction | ✅ | ✅ | ✅ |
| Decision lineage & query engine | ✅ | ✅ | ✅ |
| Persistence (single-node) | ✅ | ✅ | ✅ |
| REST/GraphQL core APIs | Read-only | ✅ | ✅ |
| Connectors | 1 (manual) | Up to 5 | Unlimited + custom |
| Search (keyword) | ✅ | ✅ | ✅ |
| Hybrid semantic + graph search | — | ✅ | ✅ |
| Grounded AI "why" assistant | — | Limited | ✅ |
| RBAC | Basic | ✅ | ✅ |
| ABAC + classification enforcement | — | — | ✅ |
| Multi-tenancy | — | Single tenant | ✅ (isolated tiers) |
| SSO / SCIM | — | SSO | SSO + SCIM |
| Immutable audit spine | ✅ | ✅ | ✅ + exports |
| Executive & analytics dashboards | — | Basic | ✅ |
| Public API + SDKs | — | ✅ | ✅ |
| On-prem deployment | — | — | ✅ |
| Air-gapped deployment | — | — | ✅ |
| Data residency controls | — | — | ✅ |
| SLA / support | Community | Business | 24×7 + TAM |

---

## 6. Licensing Strategy (frozen)

- **Core domain libraries** (`emg-*`): **source-available, proprietary license** (already `license = "Proprietary"` in every pyproject). Not open source; not on PyPI.
- **Community edition:** free, self-hosted, single-node, limited connectors — adoption & evaluation funnel.
- **Commercial editions:** subscription (per-seat + per-tenant + usage tiers). Government/defense via **term licensing** and **on-prem/air-gapped** contracts.
- **AI modules & premium connectors:** marketplace add-ons, metered.
- **Professional services:** implementation, migration, custom connectors, compliance packaging.

No component is GPL/AGPL-encumbered; dependency licenses are audited in CI (Phase 0 adds `pip-audit` + license check) to keep on-prem/air-gapped redistribution clean.

---

## 7. Editions (frozen definitions)

- **Community** — single-node, durable, core graph + evidence + lineage + keyword search + basic RBAC + audit. One manual connector. Free. Purpose: adoption.
- **Professional** — multi-connector, semantic search, limited grounded AI, SSO, basic dashboards, public API + SDKs, single-tenant SaaS. Purpose: mid-market & departmental.
- **Enterprise** — full ABAC + classification enforcement, multi-tenancy with isolation tiers, unlimited/custom connectors, full grounded AI, executive/analytics dashboards, on-prem/air-gapped/data-residency, SCIM, 24×7. Purpose: regulated & large enterprise.

Editions are **feature-flagged from one codebase**, never forks.

---

## 8. Deployment Models (frozen)

1. **Cloud (SaaS, multi-tenant)** — EMG-hosted; default for Community/Professional.
2. **On-Prem (single-tenant)** — customer Kubernetes; Enterprise. Full stack via Helm.
3. **Air-Gapped** — no external network; bundled images, offline model weights for AI, no telemetry egress; defense/gov. (`infra/environments/air-gapped-production` already anticipates this.)

**Non-negotiable:** the *same* container images and Helm charts deploy all three; air-gapped is a configuration, not a fork. AI features degrade gracefully offline (local models or disabled), never breaking core memory.

---

## 9. Domain Model (frozen — reflects `emg-ontology` + `emg-memory-graph`)

The domain model is **already implemented and strong; it is frozen as-is** with two additive cross-cutting dimensions.

**Core objects (immutable, evidence-linked, temporal):** Node, Edge, Evidence, Version, TemporalValidity/History, Decision lineage.

**Node required fields (frozen):** `id` (deterministic, content-addressed), `type`, `created_at`/`updated_at`, `source`, `confidence`, `evidence[]`, `metadata`, `tenant_id` *(additive)*.

**Edge required fields (frozen):** `type`, `direction`, `evidence_refs[]`, `confidence`, `valid_from`, `valid_until`, `metadata`, `tenant_id` *(additive)*.

**Two additive dimensions introduced at freeze (no redesign of existing model):**
- `tenant_id` on every node/edge/evidence — the multi-tenancy spine.
- `principal` provenance on every mutation — who/what asserted it.

**Frozen invariants:** facts are never overwritten (temporal supersession only); evidence is mandatory and immutable; identity is deterministic; the domain core performs **no I/O** and **no ML**.

---

## 10. Core Bounded Contexts (frozen)

1. **Identity & Access** — principals, sessions, service tokens, SSO.
2. **Authorization** — RBAC/ABAC/classification decisions (PDP).
3. **Memory Graph** — nodes, edges, evidence, temporal, versioning, lineage (the core).
4. **Knowledge Ingestion** — connectors → normalized knowledge objects → graph.
5. **Retrieval & Search** — keyword + semantic + graph-ranked recall.
6. **Decision Intelligence** — analytics/insight over lineage.
7. **AI Orchestration** — grounded RAG & agents.
8. **Audit & Provenance** — immutable spine, chain-of-custody, exports.
9. **Governance & Administration** — tenants, policy, retention, legal hold.

Each context maps to a service (or the identity/audit services already built). Contexts own their data; they never reach into each other's stores.

---

## 11. Service Boundaries (frozen)

| Service | Owns | Writes to | Reads from |
|---|---|---|---|
| **gateway/BFF** | ingress, authn, tenant resolution, rate limit | — | all (via API) |
| **identity** | principals, sessions, service tokens | identity DB | — |
| **authz (PDP)** | policy decisions | — | policy config |
| **knowledge-graph** | the graph of record | Neo4j + Postgres + outbox | its stores |
| **ingestion** (in knowledge-graph or standalone) | connector runs, normalization | via knowledge-graph API/events | connector sources |
| **retrieval** | search & vector index | Qdrant index (projection) | graph events |
| **decision-intelligence** | analytics projections | analytics store | graph events |
| **ai-orchestration** | RAG/agent workflows | — (proposes, never writes directly) | retrieval + graph |
| **audit** | immutable audit ledger | audit store | — |

**Boundary law (frozen):** one writer per store; all cross-context change flows through APIs or events; every mutation emits an audit record.

---

## 12. Data Ownership (frozen)

- **Graph of record:** knowledge-graph service → Neo4j (topology) + Postgres (metadata, versions, evidence ledger).
- **Search projections:** retrieval → Qdrant + lexical index. Derived, rebuildable from events. **Never a source of truth.**
- **Analytics projections:** decision-intelligence → warehouse/materialized views. Derived.
- **Identity/authz config:** identity + authz stores.
- **Audit ledger:** audit service, append-only, hash-chained.
- **Raw evidence blobs:** object store (S3/compatible), referenced by evidence locators.

Every datum carries `tenant_id`. Derived stores are always reconstructable from the event log + graph of record.

---

## 13. Event Taxonomy (frozen top-level)

Events are immutable, versioned, tenant-scoped, evidence-referencing. Namespaces:

- `graph.node.*` — `asserted`, `superseded`, `evidence_added`, `resolved`, `versioned`
- `graph.edge.*` — `asserted`, `superseded`, `evidence_added`
- `decision.*` — `recorded`, `approved`, `lineage_linked`
- `ingestion.*` — `connector_run_started/completed/failed`, `record_ingested`, `entity_proposed`
- `evidence.*` — `captured`, `linked`, `exported`
- `authz.*` — `access_granted`, `access_denied`, `policy_changed`
- `identity.*` — `principal_created`, `session_started`, `token_issued`
- `audit.*` — `action_recorded` (spine; mirrors every mutation)
- `tenant.*` — `provisioned`, `suspended`, `config_changed`
- `ai.*` — `answer_generated` (with citations), `resolution_suggested`

Delivered via transactional outbox → broker. Every consumer is idempotent; the log is replayable.

---

## 14. Memory Graph Entities (frozen — matches implemented `emg-memory-graph`)

Node types (14+, frozen; extensible via governed ontology, never ad hoc):
**Entity, Relationship, Evidence, Observation, Decision, Meeting, Project, Department, Person, Risk, Action, Policy, Document, Version.**

Each is immutable, deterministic-ID'd, evidence-linked, temporally valid, tenant-scoped. New node types require an ontology change (governed), not a code hack — preserving the conformance guarantees `emg-ontology` already enforces.

---

## 15. Knowledge Graph Entities (frozen — governed ontology layer)

The **knowledge/ontology layer** (`emg-ontology`) defines the *governed vocabulary*: entity types, relationship types, allowed classifications, and conformance rules that the memory graph instances must satisfy. Frozen principles:
- Ontology is **governed and versioned** — types are added deliberately, with migration.
- Every memory-graph node/edge **conforms** to an ontology-declared type.
- Classification is an ontology-level concern enforced downstream by authz.
- Provenance references (source principal, event, correlation) are first-class on every entity.

The distinction is frozen: **ontology = the schema of allowed knowledge; memory graph = the temporal, evidence-linked instances.**

---

## 16. Permission Model (frozen)

- **RBAC roles (baseline):** Viewer, Contributor, Steward, Admin, Auditor (read-only export), plus per-tenant custom roles (Enterprise).
- **ABAC attributes:** classification, department, evidence-source, tenant, node-type, decision-sensitivity.
- **Classification clearance:** enforced (not merely filtered) on every read — the current top security-debt item, promoted to a launch blocker.
- **Decision core:** `emg-policy-engine` (already implemented) is the PDP's policy evaluator.
- **Enforcement points:** gateway (coarse, tenant) + authz PDP (fine, per-object) + persistence (row/edge scoping).
- **Every decision audited.** Deny-by-default.

---

## 17. Multi-tenancy Model (frozen)

- **v1.0 baseline:** shared-schema, `tenant_id`-scoped rows/edges, enforced at persistence + PDP. Fast to market.
- **Enterprise isolation tiers (design-ready from day one via ports):** schema-per-tenant (Postgres) and database-per-tenant (Neo4j) for regulated customers; single-tenant instance = on-prem/air-gapped.
- **Cross-tenant leakage is a P0 test category** (must be proven impossible before any multi-tenant release).
- No domain-model change is permitted to achieve isolation — only persistence/PDP configuration.

---

## 18. Plugin Architecture (frozen — extends implemented `emg-connectors`)

- **Connector plugins** ingest external sources → normalized knowledge objects → evidence-linked graph assertions. The framework (registry, discovery, lifecycle, validation, capability model) already exists and is frozen as the extension substrate.
- **Extension capabilities** are declarative and validated (the extensible capability model already shipped).
- **Plugin trust:** plugins run with declared capabilities only; ingested data is evidence-tagged with connector provenance; no plugin can bypass classification or audit.
- **Marketplace (post-v1.0):** signed, versioned plugins; premium/metered.
- Frozen rule: **plugins produce evidence, never authority** — nothing a plugin ingests is trusted beyond its declared provenance and confidence.

---

## 19. Public APIs (frozen surface)

Contract-first from `emg-api-contracts`. Public, versioned, key-authenticated subset:
- **Ingest** — submit evidence/decisions (async, returns tracking).
- **Query** — decision/why/lineage/evidence/temporal/affected-projects/shortest-path.
- **Search** — hybrid recall.
- **Events** — subscribe (webhooks) to tenant-scoped events.
- **Admin** (scoped) — connectors, roles (Enterprise).

REST for CRUD/ingest; GraphQL for graph traversal. OpenAPI + GraphQL schema published. Rate-limited, tenant-scoped, audited.

---

## 20. SDK Strategy (frozen)

- **Python SDK** — wraps domain libs + API client; deterministic local mode for testing.
- **TypeScript SDK** — generated from `emg-api-contracts`; powers the web app and partners.
- Both: typed, evidence-first, versioned with the API, published to a developer portal.
- Post-v1.0: Java/.NET for enterprise integration teams if demand warrants.

---

## 21. AI Agent Strategy (frozen)

**Grounded-only. The memory graph is the deterministic source of truth; AI never mutates it autonomously.**
- **"Why" agent** — answers decision-rationale questions; **must cite EMG evidence** for every claim; refuses to answer beyond evidence.
- **Ingestion/resolution agent** — proposes entity resolutions/merges via the existing `Resolver` protocol seam; **human-approved, reversible, evidence-linked**.
- **Stewardship agent** — flags undocumented decisions and knowledge-loss risk.
- **Guardrails (frozen):** no ungrounded generation into the graph; every AI write is human-approved with provenance; confidence-thresholded; fully audited; air-gapped-capable with local models or graceful disablement.

AI is a **consumer layer**, structurally separated from the source of truth. This is the product's credibility guarantee.

---

## 22. Security Architecture (frozen)

Defense in depth:
1. **Gateway** — TLS, authn, rate limiting, tenant scoping, request-scoped audit envelope.
2. **Service-to-service** — mTLS or signed service tokens (identity service already models these).
3. **Authz PDP** — RBAC + ABAC + classification enforcement, deny-by-default, on every read/write.
4. **Data protection** — encryption in transit + at rest; field-level encryption for sensitive evidence; secrets in a vault (no `.env` in prod).
5. **Audit spine** — immutable, hash-chained; every action recorded.
6. **Supply chain** — lock file, SBOM, signed images, `pip-audit` + license checks in CI.
7. **Tenant isolation** — enforced and continuously tested.

Classification *enforcement* (not just filtering) and cross-tenant isolation are **launch blockers**.

---

## 23. Executive Dashboard Vision (frozen)

The board-level value surface. Frozen content:
- **"Decisions & why"** — recent decisions with rationale, approver, evidence strength.
- **Decision-to-outcome lineage** — trace a decision forward to its consequences.
- **Institutional-memory coverage** — % of decisions with documented rationale/evidence.
- **Knowledge-loss risk** — decisions owned by departing/departed people lacking documentation.
- **Risk & policy exposure** — risks flowing from active policies.
- **Audit & compliance posture** — evidence completeness, classification distribution.

Built on decision-intelligence projections + the event backbone. This is the artifact that justifies enterprise pricing to leadership.

---

## 24. MVP Definition (frozen)

**MVP = the smallest thing that proves the core promise end-to-end for one tenant.**
- Durable memory graph (Neo4j + Postgres).
- Ingest via one connector + manual capture → evidence-linked assertions.
- Core query APIs (why / who-approved / lineage / evidence / temporal).
- Keyword search.
- Basic RBAC + immutable audit.
- Thin web app: graph explorer + decision timeline + evidence viewer + grounded keyword "why".
- Single-tenant, single-node, cloud-deployable.

**Explicitly out of MVP:** multi-tenancy, ABAC/classification enforcement, semantic/AI search, dashboards, SDKs, on-prem/air-gapped. MVP exists to validate value, not to sell to regulated customers.

---

## 25. Version 1.0 Definition (frozen)

**v1.0 = production-grade, single-tenant-capable, sellable to Professional-tier customers.** MVP plus:
- Persistence hardened + migrations + backups.
- Full core REST/GraphQL APIs + Python/TS SDKs + public API (Professional).
- Hybrid semantic + graph search (retrieval service + Qdrant).
- Authz PDP with RBAC (ABAC/classification enforcement **designed and testable**, enforced for Enterprise track).
- Event backbone + audit spine complete.
- Gateway + SSO.
- CI/CD, containerization, Helm, observability wired, load/soak/security tested.
- Basic dashboards.
- SSO, on-prem deployment path validated.

**v1.0 does not require:** full multi-tenant isolation tiers, full grounded-AI agents, executive analytics depth, marketplace, mobile — those are v1.x/v2.0.

---

## 26. Version 2.0 Vision (frozen direction)

- **Full multi-tenant isolation tiers** (schema/DB-per-tenant) + data residency GA.
- **Grounded AI orchestration at depth** — "why" agent, resolution agent, stewardship agent, all cited & audited.
- **Executive & analytics platform** — the leadership value surface at full fidelity.
- **Connector marketplace** — signed, metered, partner-built.
- **Air-gapped GA** with offline AI.
- **Public developer platform** — portal, keys, SDKs across languages.
- **Compliance certifications** — SOC2 / ISO 27001 / sector-specific (gov/defense/health).
- **Mobile** (read-first) if validated.

v2.0 is where EMG becomes a *platform ecosystem*, not just a product.

---

## Freeze Control

This document is **frozen**. Any change requires:
1. An explicit "unfreeze" decision recorded here,
2. A version bump (`v1.1-FROZEN`, …),
3. A note of what changed and why.

All roadmap and implementation work must **conform to this freeze**. The execution roadmap in `EMG_ARCHITECTURE_REVIEW.md` is updated in the same change to align its phases to these frozen boundaries (see next section of work). Implementation begins only after the roadmap is reconciled to this freeze.

**Frozen by:** Office of the CTO, 2026-07-18.
**Re-verified:** 2026-07-19 against the relocated repository at `/Users/mak/Developer/emg-platform` (branch `develop`, clean, up to date with `origin/develop`); entity lists, connector/plugin model, policy engine, audit spine, and deterministic memory graph confirmed present in `libs/python/*`. No freeze content changed on re-verification.
