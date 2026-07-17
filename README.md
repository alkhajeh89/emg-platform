# EMG™ — Enterprise Memory Graph Core Platform

Monorepo for the EMG™ Core Platform, implementing **Architecture Baseline v1.0**
(Product Vision through ADR-017, frozen) under the **Engineering Master Plan**
and **Engineering Backlog v1.0**.

## Status

| Phase | Status |
| --- | --- |
| Architecture Phase | Closed — Architecture Baseline v1.0 frozen |
| Engineering Phase | Active — Sprint 11 (EPIC-05 Knowledge Graph: FEAT-05-3 Knowledge Validation & Trust Scoring, library-first, in progress) |

**Sprint 1** (EPIC-01 Foundation — complete): repository bootstrap, monorepo
structure, local development environment, CI pipeline skeleton, branch
protection, CODEOWNERS, shared library scaffolding, documentation folders,
developer tooling, and infrastructure folders.

**Sprint 2** (EPIC-02 Identity, FEAT-02-1 + FEAT-02-2 — complete): the
`identity` service (Module 4) — Keycloak-backed authentication and EMG
session issuance/refresh. See `services/identity/README.md` and
`SPRINT-2-STATUS.md`.

**Sprint 3** (EPIC-02 Identity, FEAT-02-3 + FEAT-02-4 — complete): service
identity & OAuth 2.0 Client Credentials (M2M) authentication, and identity
federation readiness (LDAP/AD/external OIDC/SAML configuration + validation,
no external directory connected). See `services/identity/README.md`,
`docs/engineering/service-identity-registration.md`,
`docs/engineering/federation-readiness.md`,
`docs/engineering/security-limitations.md`, and `SPRINT-3-STATUS.md`.

**Sprint 4** (EPIC-03 Authorization Platform, FEAT-03-1 + FEAT-03-2 —
complete): a library-first Policy Enforcement Point and ABAC policy engine —
`libs/python/emg-auth-client`'s `PolicyEnforcementPoint` contract and
`Decision`/`AuthorizationRequest` types, and the new
`libs/python/emg-policy-engine` package (default-deny, fail-closed,
deny-overrides evaluation, supporting both human `Principal` and machine
`ServicePrincipal` callers). `services/identity` wires the PEP as a
reference integration only (`GET /authz/check`) — there is no live
`services/authz` HTTP service; `services/authz` remains scaffolded. See
`docs/engineering/sprint-4-design.md`, `services/identity/README.md`, and
`SPRINT-4-STATUS.md`.

**Sprint 5** (EPIC-03 Authorization Completion, FEAT-03-3 + FEAT-03-4 —
complete): completing the authorization baseline — a governed RBAC baseline
role catalog (`libs/python/emg-policy-engine`'s `ROLE_CATALOG`, a versioned
role vocabulary the ABAC engine's `required_roles` conditions draw from, not
a second enforcement mechanism) and a reusable authorization testing harness
(`AuthorizationScenario`, `assert_scenario`, `run_scenarios`) proven by real
adoption in `services/identity`. See `docs/engineering/sprint-5-design.md`
and `SPRINT-5-STATUS.md`.

**Sprint 6** (EPIC-04 Audit Platform, FEAT-04-1 — complete, merged as PR #6,
merge commit `1fe6bc7`): the Audit Event Pipeline — a library-first core
(`libs/python/emg-audit-client` contract and `libs/python/emg-audit-pipeline`
implementation: `AuditEvent` model, append-only store, centralized hash chain
and sequence assignment, integrity verification, event-id idempotency) with
`services/audit` activated as a minimal live service that owns the append-only
PostgreSQL store, authenticated ingestion, minimal US-04 query (by actor, time
range, correlation id), and integrity verification. `services/identity`
migrates from `StructuredLogAuditSink` to a Protocol-preserving
`PipelineAuditSink` with a durable degraded-mode spool, so existing
login/authentication behavior is never coupled to the audit service's
availability. See `docs/engineering/sprint-6-design.md` and `SPRINT-6-STATUS.md`.

**Sprint 7** (EPIC-04 Audit Platform, FEAT-04-2 + FEAT-04-3 — complete, merged
as PR #7): the **Provenance Record Model** (a versioned `ProvenanceRecord` on
the audit event, with version-aware canonical hashing that keeps every Sprint 6
version-1 record byte-for-byte verifiable) and the **Digital Evidence
Chain-of-Custody** ledger (a separate append-only custody store with a global
hash chain, per-evidence custody sequence, tamper/gap detection, and
`(source_principal, custody_event_id)` idempotency). See
`docs/engineering/sprint-7-design.md` and `SPRINT-7-STATUS.md`.

**Sprint 8** (EPIC-04 Audit Platform completion, FEAT-04-4 — complete, merged as
PR #8, merge commit `79eaae6`): the **Audit Query & Reporting Interface** —
classification-aware audit and custody query filters (actor, module, action,
outcome, correlation id, source system, classification, provenance-presence;
evidence id / custodian for custody), stable **opaque-cursor keyset pagination**
(deterministic, no duplicates, no skipped records), and **backend JSON/CSV
report export** (no HTML, no UI). Reuses the existing `svc-audit` role; a new
index migration (`004`) is index-only and changes no stored hash (the golden
gate stays green). Classification is a *filter* dimension this sprint —
clearance-based read authorization is a documented follow-up. With FEAT-04-4
delivered, **EPIC-04 (Audit Platform) is complete** (FEAT-04-1 → FEAT-04-4). See
`docs/engineering/sprint-8-design.md` and `SPRINT-8-STATUS.md`.

**Sprint 9** (EPIC-05 Knowledge Graph, FEAT-05-1 — complete, merged as PR #9,
merge commit `2fcbaa9`): the **Core Ontology**, delivered **library-first** as
`libs/python/emg-ontology`. It defines the governed ontology model — an abstract
`Entity` and the `Actor`/`Artifact`/`Event`/`Relationship` archetypes, plus the
**Organizational** (Organization, BusinessUnit, Person, Role, System, Project,
Process) and **Risk & Safety** (Risk, Control, Policy, Regulation, Incident,
Evidence) domains — where every entity carries `classification`, `trust_score`,
and a `provenance_reference` **by construction**, alongside a pure,
storage-independent **conformance validator** and a deterministic,
pinned-version ontology descriptor (golden-tested). See
`docs/engineering/sprint-9-design.md` and `SPRINT-9-STATUS.md`.

**Sprint 10** (EPIC-05 Knowledge Graph, FEAT-05-2 — complete, merged as PR #10,
merge commit `bf8d460`): the **Knowledge Ingestion Pipeline**, delivered
**library-first** as
`libs/python/emg-knowledge-pipeline`. It is the **storage-independent** pipeline
that turns validated ontology models into persistent graph operations: ingestion
request models (server-assigned `owner`/`provenance_reference`/`trust_score` —
caller values are not trusted; free-text is length-bounded; mass-assignment is
rejected), an ingestion validator (ontology conformance + uniqueness +
relationship/classification/effective-date checks + duplicate and cyclic-
dependency rejection — no persistence before validation), deterministic
idempotent id generation, entity/relationship resolvers, batch dependency
ordering, a `GraphStore` + transaction abstraction (rollback / no partial graph)
with an **in-memory adapter**, an ingestion result model, typed ingestion
errors, and **Module-6 audit-contract emission** for `entity.created` /
`relationship.created` / `entity.superseded` / `relationship.superseded`
(provenance referenced into Module 6, correlation preserved, no audit record
duplicated). It is storage-independent — a `GraphStore` Protocol lets Neo4j be
added later without coupling business logic — so there is **no Neo4j binding**
this sprint (that, and the Semantic Layer, are FEAT-05-4), and no retrieval,
search, embeddings, AI, or UI. `services/knowledge-graph` remains scaffolded.
See `docs/engineering/sprint-10-design.md` and `SPRINT-10-STATUS.md`.

**Sprint 11** (EPIC-05 Knowledge Graph, FEAT-05-3 — in progress): **Knowledge
Validation & Trust Scoring**, delivered **library-first** as
`libs/python/emg-trust-scoring`. It is a **deterministic, storage-independent**
engine that computes an immutable, **explainable composite confidence (trust)
score** from observable **signals** — source confidence, provenance quality,
evidence completeness, validation status, ownership confidence, temporal
freshness, relationship consistency, and ingestion quality — under a versioned
**scoring policy** (per-factor weights, a temporal-decay half-life, thresholds).
Trust is **computed, never caller-supplied** (the input model has no trust
field), so it cannot be spoofed; calculations are pure and reproducible and the
output is frozen. It also runs a suite of typed **quality-gate validation**
checks (evidence completeness, provenance integrity, ownership/identifier/
ontology/relationship consistency, duplicate-confidence, temporal, lifecycle).
It has **no persistence, no service, no Neo4j, no Semantic Layer, and no
retrieval/search/embeddings/AI/UI**; wiring the engine into the ingestion
pipeline (replacing the FEAT-05-2 interim source-type default) is a follow-up for
the future live ingestion service. See `docs/engineering/sprint-11-design.md`
and `SPRINT-11-STATUS.md`.

Business logic so far covers Module 4 (Identity), Module 5 (Authorization
PEP/ABAC/RBAC), Module 6's complete FEAT-04-1 through FEAT-04-4 audit platform,
and Module 7's **FEAT-05-1 Core Ontology** (`emg-ontology`), **FEAT-05-2
Knowledge Ingestion Pipeline** (`emg-knowledge-pipeline`), and — beginning in
Sprint 11 — **FEAT-05-3 Validation & Trust Scoring** (`emg-trust-scoring`,
deterministic, library-only). There is still no graph persistence to Neo4j, no
semantic layer, no search or retrieval, no AI orchestration, and no frontend
code. Those land in later sprints per
`docs/architecture/EMG_Engineering_Backlog_v1.0.md`, Section 6 (Sprint
Planning). FEAT-05-4/05-5, EPIC-06+, and Modules 8–10 have not been started.

## Repository Structure

Per Engineering Master Plan §3 (Monorepo Structure), operationalizing Module 1
— Repository Structure (frozen):

```
/apps            Deployable applications: web client + BFF layers (ADR-014).
                  Scaffolded only; implementation begins EPIC-10 (Sprint 21+).
/services        One directory per backend module (Modules 4–10).
                  identity/ implemented (Sprint 2 FEAT-02-1/02-2, Sprint 3
                  FEAT-02-3/02-4, Sprint 4 FEAT-03-1/03-2 reference PEP
                  integration); audit/ activated Sprint 6 (FEAT-04-1 Audit
                  Event Pipeline — minimal live service over the shared
                  audit libraries); authz/ remains scaffolded by design
                  (Module 5 is library-first, no live authorization
                  service); all other services remain scaffolded until
                  their sprint lands.
/libs             Shared libraries (Module 3, ADR-012). FEAT-01-2 scaffold,
                  extended Sprint 4 with the PEP contract
                  (emg-auth-client) and the ABAC policy engine
                  (emg-policy-engine), Sprint 5 with the RBAC baseline
                  role catalog and authorization testing harness
                  (emg-policy-engine), Sprint 6 with the audit event
                  contract (emg-audit-client) and pipeline
                  (emg-audit-pipeline), Sprint 9 with the Module 7
                  Core Ontology model + conformance library
                  (emg-ontology, FEAT-05-1 — library-first, no persistence),
                  Sprint 10 with the Module 7 storage-independent
                  Knowledge Ingestion Pipeline (emg-knowledge-pipeline,
                  FEAT-05-2 — in-memory graph adapter, no Neo4j binding),
                  and Sprint 11 with the Module 7 deterministic
                  Validation & Trust Scoring engine (emg-trust-scoring,
                  FEAT-05-3 — library-only, no persistence).
/infra            Infrastructure-as-code, per environment tier. Folder
                  structure only this sprint; IaC content lands EPIC-11.
/observability    Shared dashboards and alerting definitions (ADR-015).
                  Folder structure only this sprint; content lands EPIC-12.
/docs             Reference copy of the frozen Architecture Baseline v1.0
                  document set, plus engineering process documentation.
/tools            Internal developer tooling: scaffolding generators, local
                  environment scripts, CI helper scripts.
```

## Governing Documents

- `docs/architecture/EMG_Architecture_Baseline_v1.0_Final.md` — frozen architecture of record
- `docs/architecture/EMG_Engineering_Master_Plan.md` — build execution plan
- `docs/architecture/EMG_Engineering_Backlog_v1.0.md` — sprint-by-sprint backlog
- `docs/architecture/EMG_ADR-016_Enterprise_Ownership_Registry.md` — ownership registry (source for CODEOWNERS)
- `docs/architecture/EMG_ADR-015_Unified_Enterprise_Observability.md` — observability model
- `docs/architecture/EMG_ADR-017_Enterprise_Capacity_Scalability_Model.md` — capacity/HA/DR model

## Getting Started (Local Development)

See `docs/engineering/onboarding.md`. Quick start:

```bash
make bootstrap   # installs pre-commit hooks, brings up local infra containers
make up          # start local orchestration (Postgres, Redis, Keycloak, Neo4j, Qdrant)
make down        # stop local orchestration
```

## Contributing

See `CONTRIBUTING.md`. All changes are reviewed per `CODEOWNERS`
(ADR-016-derived) and must pass the CI pipeline (`.github/workflows/ci.yml`)
before merge. Direct pushes to `main` are blocked (see `.github/settings.yml`).

## Classification

Internal — Engineering Delivery. See `NOTICE.md` for classification-handling
guidance.
