EMG™ — Engineering Master Plan

**EMG™**

**Engineering Master Plan**

*(Engineering Phase — Official Execution Plan)*

Document Classification: Internal — Engineering Leadership

Document Type: Engineering Master Plan

Covers: Architecture Baseline v1.0 through Enterprise Production

Status: Official — Engineering Phase Active

Date: 2026-07-15

**Prepared For:**

CTO  •  VP Engineering  •  Chief Software Architect

Principal Platform Engineer  •  DevOps Lead  •  Technical Program Manager

# Table of Contents

Preface

1. Engineering Strategy

2. Repository Bootstrap Plan

3. Monorepo Structure

4. Technology Stack Selection

5. Infrastructure Plan

6. CI/CD Plan

7. DevSecOps Plan

8. Sprint Planning

9. Engineering Milestones

10. Team Structure

11. Module Implementation Order

12. Repository Creation Checklist

13. Development Environment Checklist

14. Coding Standards

15. Definition of Done

16. Testing Strategy

17. Release Strategy

18. Lab Prototype v1 Scope

19. MVP Scope

20. Enterprise Production Scope

# Preface

Architecture Phase is closed. Architecture Baseline v1.0 — the Product Vision through the ADRs accepted at
baseline publication — is frozen and is not reopened, redesigned, or modified by this document. This plan answers a different question than the baseline documents: not "what is the architecture" but "in what order, by whom, and to what standard do we build it." Every technology, sequencing, and staffing decision below is a build-execution decision made *within* the frozen baseline's contracts (Modules 1–10 and the accepted ADRs recorded in
`EMG_ARCHITECTURE_DECISION_REGISTER.md`); none of it redefines a contract those documents already settled. Where this plan names a specific technology (Section 4), it does so because Technology Stack Selection is an engineering-execution decision the architecture baseline deliberately left open — consistent with ADR-014 through ADR-017 and every module's technology-agnostic design.

# 1. Engineering Strategy

EMG™ engineering proceeds in three scope tiers — Lab Prototype v1 (Section 18), MVP (Section 19), Enterprise Production (Section 20) — each a fuller realization of the same frozen architecture, never a different architecture. The strategy rests on four commitments:

- **Foundation before capability.** Modules 1–6 (repository, dev environment, shared libraries, identity, authorization, audit) are built and hardened before any Module 7–10 capability work begins, because every later module depends on their guarantees (Consolidation Review, Architecture Dependency Review).

- **Risk-first sequencing within capability layers.** Within Modules 7–10, the riskiest, least-proven architectural bets — Knowledge Graph ontology modeling and GraphRAG grounding — are validated earliest, in the Lab Prototype, before AI Orchestration and Decision Intelligence are built on top of them.

- **No quality bar deferral.** Government/defense-grade requirements (audit, provenance, explainability, human oversight) are built in from the Lab Prototype onward, not retrofitted at MVP or Production. A prototype that fakes provenance to move faster produces a false validation signal.

- **Architecture conformance is a release gate, not a suggestion.** Every sprint's Definition of Done (Section 15) includes explicit conformance checks against the module and ADR it implements; architecture drift is treated as a defect, escalated per ADR-016's ownership registry, not quietly absorbed.

# 2. Repository Bootstrap Plan

Bootstrap executes Module 1 (Repository Structure), Module 2 (Development Environment), and Module 3 (Shared Libraries, extended by ADR-012) in that order, as a single first sprint before any service code is written:

- Provision the monorepo (Section 3) per Module 1's approved repository structure, including branch protection, CODEOWNERS derived from ADR-016's ownership registry, and license/notice files.

- Scaffold the shared libraries workspace (Module 3, ADR-012): common types, error handling, logging/telemetry client (ADR-015), auth client (Module 4/5), and API client conventions (Enterprise API Architecture) — as empty, versioned packages other services will depend on from day one.

- Stand up the local development environment (Module 2): containerized local orchestration, seed/mock data fixtures (Section 18), and the pre-commit/tooling baseline (Section 14).

- Stand up the CI skeleton (Section 6) so every subsequent commit, from the first service onward, runs against real gates rather than being retrofitted later.

- Bootstrap Module 4 (Identity) as the first real service, since every other module depends on it.

No step above modifies Module 1, 2, or 3's approved design; each step is an execution of what those modules already specify.

# 3. Monorepo Structure

EMG™ adopts a single monorepo, organized by architectural layer to keep Module boundaries (and therefore ADR-016 ownership boundaries) visible in the repository structure itself:

- **/apps** — deployable applications: the web client and BFF layers (ADR-014), organized per screen family (Search, Knowledge Authoring, Agent Interaction, Decision Workspace).

- **/services** — one directory per backend module: identity (Module 4), authz (Module 5), audit (Module 6), knowledge-graph (Module 7), retrieval (Module 8), ai-orchestration (Module 9), decision-intelligence (Module 10).

- **/libs** — shared libraries (Module 3, ADR-012): common types, telemetry client (ADR-015), auth client, API contracts.

- **/infra** — infrastructure-as-code definitions (Section 5), environment configuration, and deployment manifests, organized per environment tier.

- **/observability** — shared dashboard and alerting definitions (ADR-015), owned centrally rather than duplicated per service.

- **/docs** — a reference copy of the frozen Architecture Baseline v1.0 document set, for engineering traceability; the authoritative copy remains under Architecture Board control.

- **/tools** — internal developer tooling: scaffolding generators, local environment scripts, and CI helper scripts.

This structure is engineering's operationalization of Module 1's approved repository structure; any apparent conflict between this layout and Module 1's original specification is resolved in Module 1's favor and raised to the Architecture Board, not silently reconciled here.

# 4. Technology Stack Selection

The following stack is selected to satisfy each module's technology-agnostic contract; no module or ADR is modified by naming a concrete technology here, consistent with Section 6 of ADR-014, Module 8's index architecture, and Module 9's provider-abstraction principle.

| **#** | **Layer** | **Selected Technology** | **Governing Contract** |
| --- | --- | --- | --- |
| 1 | Backend services | Python, FastAPI | Enterprise API Architecture; Modules 4–10 |
| 2 | Frontend / BFF | Next.js, React, TypeScript | ADR-014 (component composition, BFF strategy) |
| 3 | Relational / system-of-record store | PostgreSQL | Enterprise Data Architecture; Module 6 audit store |
| 4 | Knowledge graph store | Neo4j Enterprise | Module 7, Section 10 (Semantic Layer — storage-independent contract) |
| 5 | Vector / semantic index | Qdrant | Module 8, Section 8 (Semantic Index role) |
| 6 | Cache / session memory | Redis | Module 9, Section 8 (Working/Session Memory) |
| 7 | AI model provider | Azure OpenAI, with on-premises/air-gapped model routing target | Module 9, Section 7 (provider abstraction, air-gapped support) |
| 8 | Identity & access management | Keycloak | Module 4 (Identity & Authentication) |
| 9 | API styles | REST and GraphQL | Enterprise API Architecture |
| 10 | Containerization / orchestration | Docker, Kubernetes | Section 5 (Infrastructure Plan); ADR-017 |

Every selection above is replaceable without architectural rework, per each module's storage- and provider-independence design; this table is an engineering decision, reviewable and changeable by engineering leadership without Architecture Board involvement, provided the replacement continues to satisfy the same governing contract.

# 5. Infrastructure Plan

Infrastructure is Kubernetes-based across four environment tiers — local development (Section 13), shared development/integration, staging, and production — plus a fifth, air-gapped production variant satisfying Module 9 Section 7's disconnected deployment requirement. Infrastructure is defined as code, versioned in /infra (Section 3), and environment-promoted rather than hand-configured per environment. Networking enforces Zero Trust at every tier consistent with Module 5 and Module 9 Section 16: no service-to-service call bypasses authenticated, policy-evaluated access, including within a single Kubernetes cluster. Secrets (model credentials, database credentials, signing keys) are managed through a centralized secrets store with per-service, least-privilege access, never embedded in images or configuration files. Capacity and scaling configuration for each tier follows ADR-017's compounded-load model, not independent per-service sizing.

# 6. CI/CD Plan

Every change proceeds through a single pipeline with staged gates: lint and static analysis → unit tests → build → security scanning (Section 7) → integration tests → deployment to shared development → automated regression and contract tests → promotion to staging (requiring the Definition of Done, Section 15) → manual release approval → production deployment (Section 17). No stage may be skipped, and no service has a bespoke pipeline outside this shared template — pipeline definitions live in /tools (Section 3) and are versioned like any other shared library. Deployment is progressive (canary or rolling, per service risk tier) rather than all-at-once, with automated rollback triggered by ADR-015's SLO/error-budget signals (ADR-015, Section 13) rather than manual observation alone.

# 7. DevSecOps Plan

Security is enforced at every pipeline stage (Section 6), not as a pre-release audit: static application security testing and dependency/software-composition scanning on every commit; secrets scanning on every commit; infrastructure-as-code scanning on every /infra change; container image scanning before any deployment; and dynamic application security testing against staging before production promotion. Policy-as-code tests validate Module 5's ABAC rules and Module 7/8/9/10's respective classification and need-to-know enforcement (Modules 7 §21, 8 §10, 9 §16, 10 §15) as part of the standard test suite, not a separate security-team-only activity. Each module's STRIDE threat model (Module 7 §25, Module 8 §18, Module 9 §17, Module 10 §16) is the source of truth for required negative security test cases; DevSecOps maintains traceability from each named threat to at least one automated test. Production promotion requires a clean security-gate result; a failed security gate blocks release regardless of feature completeness.

# 8. Sprint Planning

EMG™ engineering runs two-week sprints with standard ceremonies (planning, daily sync, review, retrospective) plus one addition specific to this program: an Architecture Conformance Check at the end of every sprint, where the implementing team confirms against the relevant module/ADR section that no unintentional architectural drift occurred. Sprint roadmap phases, at a relative level (concrete calendar dates are a program-management, not architecture, artifact and are maintained outside this document):

| **Phase** | **Sprint Range** | **Focus** |
| --- | --- | --- |
| Bootstrap | Sprint 1 | Repository, dev environment, shared libraries (Section 2) |
| Foundation | Sprints 2–5 | Module 4 (Identity), Module 5 (Authorization), Module 6 (Audit) |
| Knowledge | Sprints 6–9 | Module 7 (Knowledge Graph), Lab Prototype ontology and mock data |
| Retrieval | Sprints 10–12 | Module 8 (Search/GraphRAG) |
| AI Orchestration | Sprints 13–16 | Module 9 (AI Orchestration & Agents) |
| Decision Intelligence | Sprints 17–19 | Module 10 (Decision Intelligence) |
| Presentation & Hardening | Sprints 20–23 | ADR-014 surfaces, ADR-015/016/017 operationalization, MVP hardening |

# 9. Engineering Milestones

| **#** | **Milestone** | **Exit Criteria** |
| --- | --- | --- |
| 1 | Bootstrap Complete | Repository, CI/CD, dev environment, and shared libraries operational (Section 2) |
| 2 | Trust Foundation Complete | Modules 4–6 implemented and passing their respective acceptance criteria |
| 3 | Lab Prototype v1 Delivered | Section 18 scope demonstrated end-to-end on mock government data |
| 4 | Knowledge & Retrieval Complete | Modules 7–8 implemented and passing acceptance criteria |
| 5 | AI & Decision Complete | Modules 9–10 implemented and passing acceptance criteria |
| 6 | MVP Delivered | Section 19 scope live for pilot government customer |
| 7 | Enterprise Production Readiness | Section 20 scope complete; all ADR-014–017 operationalized |
| 8 | Enterprise Production Launch | Full platform live under production SLOs (ADR-015) |

# 10. Team Structure

| **Team** | **Scope** | **Reports To (ADR-016 alignment)** |
| --- | --- | --- |
| Platform & Foundation | Modules 1–3, shared libraries, dev environment | CTO |
| Identity & Security | Module 4, Module 5, DevSecOps (Section 7) | CISO |
| Audit & Provenance | Module 6 | CISO / Chief Data Officer |
| Knowledge Graph | Module 7 | Chief Data Officer |
| Retrieval & Search | Module 8 | Chief Data Officer / Chief AI Officer |
| AI Orchestration | Module 9 | Chief AI Officer |
| Decision Intelligence | Module 10 | Chief AI Officer / Executive Decision Board |
| Presentation | ADR-014 surfaces and BFF layer | CIO |
| Platform SRE / Observability | ADR-015, infrastructure (Section 5) | CTO |
| Program Management | Sprint planning (Section 8), milestone tracking (Section 9) | VP Engineering |

Team boundaries mirror ADR-016's ownership registry exactly, so accountability for a defect or change request is never ambiguous between engineering and the governing architecture registry.

# 11. Module Implementation Order

Implementation strictly follows the dependency order validated in the Architecture Consolidation Review (Section 3, Architecture Dependency Review): Modules 1–3 (Foundation) → Module 4 (Identity) → Module 5 (Authorization) → Module 6 (Audit) → Module 7 (Knowledge Graph) → Module 8 (Search/GraphRAG) → Module 9 (AI Orchestration) → Module 10 (Decision Intelligence). Presentation (ADR-014) is built incrementally alongside each backend module's screen family (ADR-014, Section 5) rather than deferred to the end, so every module reaches a genuinely demonstrable state as it completes. Observability (ADR-015) and ownership-registry-driven alerting (ADR-016) are instrumented starting with Module 4, not added retroactively, per the Engineering Readiness Statement in Architecture Baseline v1.0, Section 9. No module begins implementation before every module it depends on (per the dependency table in the Consolidation Review) has passed its own acceptance criteria.

# 12. Repository Creation Checklist

- Monorepo created per Section 3's structure and Module 1's approved specification.

- Branch protection enabled on the main integration branch; no direct pushes.

- CODEOWNERS file populated from ADR-016's Ownership Registry (Section 1, Modules table).

- CI/CD pipeline skeleton (Section 6) wired and passing on an empty scaffold commit.

- Security scanning tools (Section 7) enabled from the first commit, not added later.

- License, notices, and classification-handling documentation in place.

- Shared libraries workspace (Module 3, ADR-012) scaffolded with versioned, empty packages.

- Observability client library (ADR-015) scaffolded and wired into the shared libraries workspace.

# 13. Development Environment Checklist

- Containerized local orchestration available and documented (Module 2).

- Mock government data fixtures available for Lab Prototype development (Section 18).

- Local identity/authorization stub or lightweight Keycloak instance available for Module 4/5 development without requiring shared infrastructure.

- Pre-commit hooks installed: lint, format, secrets scan (Section 14).

- IDE/editor configuration standardized and documented (Section 14).

- Local observability stack (or lightweight equivalent) available so engineers can see telemetry (ADR-015) during development, not only in shared environments.

- Onboarding documentation validated by a new engineer completing full setup in under one working day.

# 14. Coding Standards

Python services (FastAPI, Section 4) follow PEP 8 with automated formatting and linting enforced in CI (Section 6); TypeScript/React code (ADR-014) follows a standardized linting and formatting configuration shared across all presentation-layer packages. API design follows the Enterprise API Architecture's conventions for both REST and GraphQL surfaces; no service defines an ad hoc API style. Every service change includes updated documentation-in-code (docstrings/type annotations) sufficient for another engineer to understand intent without reading implementation line by line. Commit messages follow a standardized, conventional format enabling automated changelog generation. Secure coding baseline (input validation, output encoding, dependency hygiene) follows OWASP guidance and is enforced by the DevSecOps gates in Section 7, not left to individual reviewer judgment alone. Every pull request requires at least one review from an engineer outside the author's immediate team when the change touches a shared library (Section 3) or a cross-module contract.

# 15. Definition of Done

A change is Done only when: code is reviewed and approved per Section 14; automated tests (Section 16) pass, including any new tests the change required; code coverage meets the team's governed threshold; all DevSecOps gates (Section 7) pass; observability instrumentation (ADR-015) is present for any new service boundary, event, or decision point; the change's behavior is traceable to a specific module/ADR section, and that traceability is recorded; documentation (in-code and, where relevant, /docs) is updated; accessibility conformance (ADR-014, Section 9) is verified for any presentation-layer change; and, for any change touching classification, provenance, or audit behavior (Modules 6, 7 §21, 8 §10, 9 §16, 10 §15), a security reviewer has explicitly signed off. A change that is "feature complete" but fails any of the above is not Done.

# 16. Testing Strategy

Testing follows a standard pyramid — unit tests for business logic, integration tests across service boundaries, and end-to-end tests for full user-journey scenarios — layered with the specific testing obligations each module already defined: Module 7 Section 26 (knowledge quality, semantic consistency, provenance, replay, authorization, performance, security), Module 8's Explainable Retrieval and grounding validation tests, Module 9 Section 17's AI/agentic threat test cases, and Module 10's Decision Replay reconstruction tests. Engineering does not redefine these obligations; it implements them as automated test suites traceable back to their originating module section. Performance and load testing is planned against ADR-017's capacity model (compounded cross-layer load), not per-service load alone. User acceptance testing for the Lab Prototype (Section 18) and MVP (Section 19) includes structured government stakeholder review sessions, given the platform's target customer base.

# 17. Release Strategy

Services are versioned independently using semantic versioning, with a platform-level release train marking coordinated milestones (Section 9). Releases are promoted through environment tiers (Section 5) with staged rollout (canary/rolling) and automated rollback tied to SLO/error-budget breach (ADR-015, Section 13). Feature flags gate incomplete or partially-validated capability so a module can be deployed to production infrastructure ahead of its full feature set being enabled, supporting the incremental milestone structure in Section 9. Air-gapped deployments (Module 9, Section 7; ADR-017, Section 5) receive a separately packaged, versioned release artifact validated against a disconnected installation procedure, not merely the same artifact assumed to work offline.

# 18. Lab Prototype v1 Scope

Lab Prototype v1 demonstrates EMG™'s core thesis — institutional knowledge captured, grounded, and made decision-relevant — end-to-end, on mock government data, without full module depth. In scope: minimal Module 4/5/6 (authentication, coarse authorization, basic audit logging); a small, hand-curated Module 7 knowledge graph populated with representative mock government entities (Person, Organization, Investigation, Risk, Policy, Decision) sufficient to demonstrate the ontology, not the full Module 7 ingestion pipeline; basic Module 8 hybrid search over that graph; a single Module 9 agent (Search Assistant or Decision Support Agent) demonstrating grounded, cited GraphRAG responses; and a minimal Module 10 Decision Briefing view demonstrating evidence correlation and a human approval step. Explicitly out of scope: multi-tenant isolation, full observability (ADR-015 is instrumented but not operationally monitored), air-gapped packaging, and any AI agent role beyond the one selected. The Lab Prototype's purpose is validating the architecture's core value proposition, not production readiness.

# 19. MVP Scope

MVP scope is frozen at `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §24
and is not restated here. Target customers are frozen at Freeze §2; this plan
names no individual customer. This section records only the engineering
sequence by which the frozen MVP is delivered; where this plan and Freeze §24
differ, the Freeze governs.

# 20. Enterprise Production Scope

Enterprise Production realizes Modules 1–10 and the accepted ADRs recorded in
`EMG_ARCHITECTURE_DECISION_REGISTER.md` in full: complete Module 7 ontology and knowledge domains across all target verticals (government, aviation, public safety, and any additional vertical pursued); complete Module 8 federated search; the complete Module 9 agent roster with full AI safety and observability operations; complete Module 10 decision intelligence including full Decision Analytics and organizational learning feedback; ADR-014's presentation layer including future desktop/mobile strategy evaluation (ADR-014, Section 12); ADR-015's SLI/SLO/error-budget model fully operational with governed alerting; ADR-016's ownership registry fully populated and actively used for change routing; and ADR-017's capacity, HA, and disaster recovery model fully implemented, including a validated air-gapped deployment path. Enterprise Production additionally pursues the government readiness posture each module's Government Readiness Assessment section described — without claiming formal certification, consistent with every module's explicit scope boundary — as a program-level activity coordinated with, but outside, this engineering plan.

**End of EMG™ — Engineering Master Plan.**

Per instruction, this document creates no new architecture, modifies no approved module or ADR, and introduces no Module 11. It is the official engineering execution plan under the frozen Architecture Baseline v1.0.

Page 1 of 2

---
*Reference copy for engineering traceability (Engineering Master Plan §3). The authoritative copy remains under Architecture Board control.*
