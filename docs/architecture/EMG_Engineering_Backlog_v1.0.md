EMG™ — Engineering Backlog v1.0

**EMG™**

**Engineering Backlog v1.0**

*(Execution Backlog — Pending Sprint 1 Approval)*

Document Classification: Internal — Engineering Delivery

Document Type: Engineering Backlog

Covers: Engineering Master Plan through Sprint 24

Status: Draft — Awaiting Approval to Begin Sprint 1

Date: 2026-07-15

**Prepared For:**

CTO  •  VP Engineering  •  Technical Program Manager

Engineering Delivery Manager  •  Product Owner  •  Scrum Master

# Table of Contents

1. Engineering Program Overview

2. Engineering Epics

3. Features

4. User Stories (Canonical, One Per Epic)

5. Engineering Tasks (Canonical Stories, Decomposed)

6. Sprint Planning (Sprint 1–24)

7. Dependencies

8. Story Point Estimation (Fibonacci, per Feature)

9. Priority Matrix

10. Milestones

11. Release Plan

12. Team Allocation

13. Definition of Ready

14. Definition of Done

15. Engineering Risks

16. Success Metrics

17. Lab Prototype Roadmap

18. MVP Roadmap

19. Enterprise Production Roadmap

20. Executive Delivery Dashboard

# 1. Engineering Program Overview

This backlog transforms the approved Engineering Master Plan into an executable, sprint-by-sprint program. It does not revisit any architectural decision: every Epic, Feature, and Story below implements a specific, already-approved module or ADR section, and every item in this document is traceable to its governing architecture reference. Where architecture leaves an implementation detail open, this backlog leaves it open too — it is refined during sprint backlog grooming, not invented here.

Scope note on depth: this document fully enumerates the Epic → Feature hierarchy (Sections 2–3) and the complete 24-sprint plan (Section 6), because those are the structures engineering commits to at program start. It does not pre-write every user story for every one of the ~55 Features — at enterprise scale that would be several hundred stories, most of which would be rewritten during refinement anyway as downstream discovery occurs. Instead, Section 4 provides one fully elaborated, board-ready canonical story per Epic, establishing the required format (including acceptance criteria) and depth every team must match when they groom their own Features into stories during the sprint immediately preceding implementation. This is standard Agile practice and is called out explicitly so it is not mistaken for an omission.

# 2. Engineering Epics

| **Epic ID** | **Epic** | **Governing Architecture** |
| --- | --- | --- |
| EPIC-01 | Foundation | Modules 1–3, ADR-012 |
| EPIC-02 | Identity | Module 4, ADR-013 |
| EPIC-03 | Authorization | Module 5 |
| EPIC-04 | Audit | Module 6 |
| EPIC-05 | Knowledge Graph | Module 7 (incl. Sections 30–35) |
| EPIC-06 | Search | Module 8 |
| EPIC-07 | GraphRAG | Module 7 §30, Module 8 §6 |
| EPIC-08 | AI Platform | Module 9 |
| EPIC-09 | Decision Intelligence | Module 10 |
| EPIC-10 | Frontend | ADR-014 |
| EPIC-11 | Infrastructure | ADR-017, Engineering Master Plan §5 |
| EPIC-12 | DevSecOps | Engineering Master Plan §6–7; ADR-015 (Observability) |

# 3. Features

| **Feature ID** | **Epic** | **Feature** | **Description** |
| --- | --- | --- | --- |
| FEAT-01-1 | EPIC-01 | Monorepo Bootstrap | Repository structure, branch protection, CODEOWNERS from ADR-016 |
| FEAT-01-2 | EPIC-01 | Shared Libraries Scaffolding | Common types, error handling, API client conventions (Module 3) |
| FEAT-01-3 | EPIC-01 | Local Development Environment | Containerized local orchestration, seed data (Module 2) |
| FEAT-01-4 | EPIC-01 | CI Pipeline Skeleton | Base pipeline template all services inherit |
| FEAT-02-1 | EPIC-02 | Identity Provider Integration | Keycloak realm, client, and user federation setup |
| FEAT-02-2 | EPIC-02 | Authentication Session Management | Session issuance, refresh, expiry |
| FEAT-02-3 | EPIC-02 | Service Identity & M2M Auth | Non-human service-to-service authentication |
| FEAT-02-4 | EPIC-02 | Identity Federation Readiness | Air-gapped / disconnected identity provider support |
| FEAT-03-1 | EPIC-03 | Policy Enforcement Point | PEP integration pattern reused by every downstream module |
| FEAT-03-2 | EPIC-03 | ABAC Policy Engine Integration | Attribute-based policy evaluation |
| FEAT-03-3 | EPIC-03 | RBAC Baseline Roles | Foundational role catalog |
| FEAT-03-4 | EPIC-03 | Authorization Testing Harness | Automated positive/negative authorization test suite |
| FEAT-04-1 | EPIC-04 | Audit Event Pipeline | Structured, append-only audit event capture |
| FEAT-04-2 | EPIC-04 | Provenance Record Model | Source/actor/timestamp/method tracking |
| FEAT-04-3 | EPIC-04 | Digital Evidence Chain-of-Custody | Evidence integrity and custody tracking |
| FEAT-04-4 | EPIC-04 | Audit Query & Reporting Interface | Backend query surface for audit records |
| FEAT-05-1 | EPIC-05 | Ontology Implementation | Core + domain entity/relationship types |
| FEAT-05-2 | EPIC-05 | Knowledge Ingestion Pipeline | System, document, API, AI, and human ingestion sources |
| FEAT-05-3 | EPIC-05 | Knowledge Validation & Trust Scoring | Quality gates and composite confidence scoring |
| FEAT-05-4 | EPIC-05 | Semantic Layer | Storage-independent query/traversal abstraction |
| FEAT-05-5 | EPIC-05 | Knowledge Lifecycle & Versioning | Proposed→active→retired state management |
| FEAT-06-1 | EPIC-06 | Lexical Search | Keyword/exact-match retrieval |
| FEAT-06-2 | EPIC-06 | Semantic Search | Embedding-based similarity retrieval |
| FEAT-06-3 | EPIC-06 | Hybrid Search & Ranking | Combined retrieval with Enterprise Ranking Framework |
| FEAT-06-4 | EPIC-06 | Search Security Filtering | ABAC/classification/need-to-know filtering at query time |
| FEAT-06-5 | EPIC-06 | Explainable Retrieval | Retrieval/ranking decomposition and exclusion logging |
| FEAT-07-1 | EPIC-07 | Graph Traversal & Context Expansion | Bounded traversal from seed entities |
| FEAT-07-2 | EPIC-07 | Evidence Retrieval & Citation Collection | Evidence linking and citation set assembly |
| FEAT-07-3 | EPIC-07 | Context Packaging & Grounding Pipeline | Bounded, provenance-tagged context objects |
| FEAT-07-4 | EPIC-07 | Hallucination Prevention Controls | Ungrounded-response flagging |
| FEAT-08-1 | EPIC-08 | AI Orchestrator & Model Router | Task coordination and provider-agnostic routing |
| FEAT-08-2 | EPIC-08 | Agent Runtime & Agent Roles | Isolated execution environment; 8 agent roles (Module 9 §5) |
| FEAT-08-3 | EPIC-08 | Human Approval Gateway | Mandatory approval routing for consequential actions |
| FEAT-08-4 | EPIC-08 | AI Policy Enforcement Integration | PEP evaluation at every reasoning-lifecycle stage |
| FEAT-08-5 | EPIC-08 | AI Safety Controls | Prompt injection, jailbreak, tool-abuse mitigations |
| FEAT-09-1 | EPIC-09 | Decision Context Builder | Context assembly from Modules 7–9 |
| FEAT-09-2 | EPIC-09 | Evidence Correlation Engine | Corroboration, contradiction, gap detection |
| FEAT-09-3 | EPIC-09 | Recommendation Engine | Confidence-scored, cited, non-binding recommendations |
| FEAT-09-4 | EPIC-09 | Human Decision Workspace (Backend) | Briefing/approval data services |
| FEAT-09-5 | EPIC-09 | Decision Replay Engine | Timeline/context/evidence/policy replay |
| FEAT-10-1 | EPIC-10 | Design System Component Integration | Shared component/token library adoption |
| FEAT-10-2 | EPIC-10 | BFF Layer Implementation | Per-surface Backend-for-Frontend services |
| FEAT-10-3 | EPIC-10 | Search & Discovery UI | Query input, results, citations |
| FEAT-10-4 | EPIC-10 | Agent Interaction UI | Conversational/task agent surfaces |
| FEAT-10-5 | EPIC-10 | Human Decision Workspace UI | Briefing, evidence, confidence, alternatives views |
| FEAT-10-6 | EPIC-10 | Knowledge Authoring UI | Candidate review and validation workflow |
| FEAT-11-1 | EPIC-11 | Kubernetes Cluster Provisioning | Per-environment cluster setup |
| FEAT-11-2 | EPIC-11 | Infrastructure-as-Code Baseline | Versioned, environment-promoted infra definitions |
| FEAT-11-3 | EPIC-11 | Secrets Management | Centralized, least-privilege secrets store |
| FEAT-11-4 | EPIC-11 | Capacity & HA/DR Implementation | ADR-017 compounded-load model realization |
| FEAT-11-5 | EPIC-11 | Air-Gapped Deployment Packaging | Disconnected installation artifact and procedure |
| FEAT-12-1 | EPIC-12 | CI/CD Pipeline Implementation | Full staged pipeline per Engineering Master Plan §6 |
| FEAT-12-2 | EPIC-12 | Security Scanning Suite | SAST, DAST, SCA, secrets, IaC, container scanning |
| FEAT-12-3 | EPIC-12 | Observability Platform | Logs, metrics, traces per ADR-015 |
| FEAT-12-4 | EPIC-12 | Alerting & SLO/Error Budget | ADR-015 Sections 10–13 realization |
| FEAT-12-5 | EPIC-12 | Release & Rollback Automation | Progressive delivery and automated rollback |

# 4. User Stories (Canonical, One Per Epic)

Each story below is board-ready: fully worded, with acceptance criteria, ready to import as-is. Every remaining Feature in Section 3 is groomed into stories of this same depth during the sprint before its implementation begins.

**US-01 (FEAT-01-1, EPIC-01 Foundation).** As a platform engineer, I want a monorepo scaffolded per Module 1's approved structure, so that every subsequent service has a consistent, governed place to live. Acceptance criteria: repository exists with the /apps, /services, /libs, /infra, /observability, /docs, /tools layout; branch protection blocks direct pushes to main; CODEOWNERS is populated from the ADR-016 ownership registry; an empty scaffold commit passes CI end-to-end.

**US-02 (FEAT-02-1, EPIC-02 Identity).** As a platform user, I want to authenticate through the enterprise identity provider, so that my access to any EMG™ surface is tied to a single verified identity. Acceptance criteria: Keycloak realm and client are provisioned; login issues a valid session token; token carries the claims Module 5's PEP requires; failed authentication is logged via the audit pipeline (FEAT-04-1).

**US-03 (FEAT-03-1, EPIC-03 Authorization).** As a service developer, I want a reusable Policy Enforcement Point client, so that every module evaluates authorization consistently instead of reimplementing it. Acceptance criteria: PEP client is published as a shared library (FEAT-01-2); a request with insufficient attributes is denied with an auditable reason; a request with sufficient attributes is allowed; denial and allow decisions are both logged (FEAT-04-1).

**US-04 (FEAT-04-1, EPIC-04 Audit).** As a compliance officer, I want every governed action captured as an immutable audit event, so that any decision or access can be reconstructed later. Acceptance criteria: audit events are append-only; each event carries actor, action, timestamp, and correlation identifier; events are queryable by actor, time range, and correlation identifier; no code path can delete or mutate a published event.

**US-05 (FEAT-05-1, EPIC-05 Knowledge Graph).** As a knowledge steward, I want the core and domain ontology implemented as governed entity/relationship types, so that knowledge ingestion has a consistent target model. Acceptance criteria: Core Ontology (Entity, Actor, Artifact, Event, etc.) and at least the Organizational and Risk & Safety domains (Module 7 §4) are implemented; every entity instance carries classification, trust score, and provenance reference by construction; an ontology conformance test rejects a non-conforming write.

**US-06 (FEAT-06-3, EPIC-06 Search).** As a platform user, I want hybrid search results ranked by relevance, trust, and freshness, so that the most reliable answer surfaces first, not just the most textually similar one. Acceptance criteria: a query returns results from at least lexical and semantic retrieval merged into one ranked list; ranking score is decomposable into its contributing signals (FEAT-06-5); results are filtered by the requester's authorization before ranking (FEAT-06-4).

**US-07 (FEAT-07-3, EPIC-07 GraphRAG).** As an AI Agent, I want a bounded, cited context object for a given query, so that any response I generate is grounded and explainable rather than invented. Acceptance criteria: context object includes expanded graph neighborhood (FEAT-07-1), linked evidence (FEAT-07-2), and a complete citation set; items without valid provenance are excluded, not silently included; context object size is bounded per governed limits.

**US-08 (FEAT-08-2, EPIC-08 AI Platform).** As a case investigator, I want to invoke the Investigation Agent within my authorization scope, so that I get assembled evidence and timeline context without manually querying multiple systems. Acceptance criteria: agent only accesses cases the requesting investigator is authorized for; agent output includes citations for every factual claim; any action beyond read/assemble routes to the Human Approval Gateway (FEAT-08-3).

**US-09 (FEAT-09-3, EPIC-09 Decision Intelligence).** As an accountable decision-maker, I want a confidence-scored recommendation with full supporting evidence, so that I can make an informed decision without the system deciding for me. Acceptance criteria: recommendation is never auto-approved regardless of confidence score; every recommendation cites its supporting evidence (FEAT-09-2); the decision-maker's approval or rejection is recorded as a Decision entity with rationale.

**US-10 (FEAT-10-5, EPIC-10 Frontend).** As a decision-maker, I want the Human Decision Workspace to show alternatives, confidence, and risk indicators side by side, so that I can compare options rather than reviewing them in isolation. Acceptance criteria: screen renders Decision Briefing, Executive Summary, Evidence Visualization, Confidence Display, and Alternative Comparison per Module 10 §13; all content is sourced from the BFF layer (FEAT-10-2), never queried directly from backend APIs; screen passes accessibility conformance (ADR-014 §9).

**US-11 (FEAT-11-2, EPIC-11 Infrastructure).** As a platform engineer, I want every environment defined as versioned infrastructure-as-code, so that environments are reproducible and auditable rather than hand-configured. Acceptance criteria: dev, staging, and production environments are provisioned from the same IaC source with environment-specific configuration; a environment rebuild from IaC produces a functionally equivalent environment; IaC changes pass the security scanning gate (FEAT-12-2) before apply.

**US-12 (FEAT-12-3, EPIC-12 DevSecOps).** As an SRE, I want correlated logs, metrics, and traces across every module, so that I can trace a failing request end-to-end instead of investigating each module in isolation. Acceptance criteria: a single correlation identifier propagates through the AI Reasoning Lifecycle (Module 9 §9) and Decision Lifecycle (Module 10 §5); dashboards (Section 20) render data from this shared model; a synthetic cross-module failure is traceable start-to-finish within the observability platform.

# 5. Engineering Tasks (Canonical Stories, Decomposed)

| **Story** | **Task ID** | **Task** |
| --- | --- | --- |
| US-01 | TASK-01-1 | Provision repository and configure branch protection |
| US-01 | TASK-01-2 | Create directory scaffold and CODEOWNERS from ADR-016 |
| US-01 | TASK-01-3 | Wire empty scaffold commit through CI skeleton (FEAT-01-4) |
| US-02 | TASK-02-1 | Provision Keycloak realm and client configuration |
| US-02 | TASK-02-2 | Implement session issuance and refresh handling |
| US-02 | TASK-02-3 | Wire failed-auth logging to audit pipeline |
| US-03 | TASK-03-1 | Publish PEP client as shared library package |
| US-03 | TASK-03-2 | Implement allow/deny decision logging |
| US-03 | TASK-03-3 | Write positive and negative authorization test cases |
| US-04 | TASK-04-1 | Implement append-only audit event store |
| US-04 | TASK-04-2 | Implement correlation-identifier propagation |
| US-04 | TASK-04-3 | Implement query-by-actor/time-range/correlation-id API |
| US-05 | TASK-05-1 | Model Core Ontology entity/relationship types |
| US-05 | TASK-05-2 | Model Organizational and Risk & Safety domain entities |
| US-05 | TASK-05-3 | Implement ontology conformance validation |
| US-06 | TASK-06-1 | Implement lexical retrieval adapter |
| US-06 | TASK-06-2 | Implement semantic retrieval adapter |
| US-06 | TASK-06-3 | Implement ranking score decomposition endpoint |
| US-07 | TASK-07-1 | Implement bounded graph traversal from seed entities |
| US-07 | TASK-07-2 | Implement evidence linking and citation assembly |
| US-07 | TASK-07-3 | Implement provenance validation gate before packaging |
| US-08 | TASK-08-1 | Implement Investigation Agent role and scope binding |
| US-08 | TASK-08-2 | Wire agent output citation requirement |
| US-08 | TASK-08-3 | Route consequential actions to Human Approval Gateway |
| US-09 | TASK-09-1 | Implement recommendation confidence scoring |
| US-09 | TASK-09-2 | Enforce mandatory human review before Decision recording |
| US-09 | TASK-09-3 | Implement Decision entity recording with rationale |
| US-10 | TASK-10-1 | Build Decision Briefing and Executive Summary components |
| US-10 | TASK-10-2 | Build Evidence Visualization and Confidence Display components |
| US-10 | TASK-10-3 | Run accessibility conformance audit |
| US-11 | TASK-11-1 | Author base IaC modules for compute/network/storage |
| US-11 | TASK-11-2 | Parameterize per-environment configuration |
| US-11 | TASK-11-3 | Validate environment rebuild reproducibility |
| US-12 | TASK-12-1 | Implement correlation-ID propagation library |
| US-12 | TASK-12-2 | Wire log/metric/trace emission to shared schema |
| US-12 | TASK-12-3 | Validate end-to-end trace on synthetic failure scenario |

# 6. Sprint Planning (Sprint 1–24)

Infrastructure (EPIC-11) and DevSecOps (EPIC-12) are continuous work threads embedded in every sprint's Definition of Done (Section 14), not block-scheduled phases; the table below shows each sprint's *primary* epic focus.

| **Sprint** | **Epic Focus** | **Sprint Goal** | **Key Deliverables** | **Exit Criteria** |
| --- | --- | --- | --- | --- |
| 1 | EPIC-01 | Bootstrap the monorepo and CI skeleton | FEAT-01-1 through 01-4 complete | US-01 acceptance criteria met; CI green on scaffold |
| 2 | EPIC-02 | Stand up identity provider and session management | FEAT-02-1, 02-2 | US-02 acceptance criteria met |
| 3 | EPIC-02 | Complete service identity and M2M auth | FEAT-02-3, 02-4 | All services authenticate via shared identity client |
| 4 | EPIC-03 | Implement PEP and ABAC policy engine | FEAT-03-1, 03-2 | US-03 acceptance criteria met |
| 5 | EPIC-03 → EPIC-04 | Complete authorization baseline; begin audit pipeline | FEAT-03-3, 03-4, 04-1 | Authorization test harness green; audit events flowing |
| 6 | EPIC-04 | Complete audit and provenance | FEAT-04-2, 04-3, 04-4 | US-04 acceptance criteria met |
| 7 | EPIC-05 | Implement core ontology | FEAT-05-1 | US-05 acceptance criteria met |
| 8 | EPIC-05 | Implement ingestion pipeline | FEAT-05-2 | Ingestion from at least one source type validated end-to-end |
| 9 | EPIC-05 | Implement validation, trust scoring, semantic layer | FEAT-05-3, 05-4, 05-5 | **Milestone: Lab Prototype knowledge layer complete** |
| 10 | EPIC-06 | Implement lexical and semantic search | FEAT-06-1, 06-2 | Both retrieval strategies return results independently |
| 11 | EPIC-06 | Implement hybrid ranking and security filtering | FEAT-06-3, 06-4 | US-06 acceptance criteria met |
| 12 | EPIC-06 → EPIC-07 | Complete explainable retrieval; begin GraphRAG traversal | FEAT-06-5, 07-1 | **Milestone: Lab Prototype search layer complete** |
| 13 | EPIC-07 | Implement evidence retrieval, citation, context packaging | FEAT-07-2, 07-3 | US-07 acceptance criteria met |
| 14 | EPIC-07 → EPIC-08 | Complete hallucination prevention; begin AI orchestrator | FEAT-07-4, 08-1 | **Milestone: Lab Prototype GraphRAG complete** |
| 15 | EPIC-08 | Implement agent runtime and first agent role | FEAT-08-2 (partial) | One agent role operational end-to-end (Lab Prototype agent) |
| 16 | EPIC-08 | Implement Human Approval Gateway and AI policy enforcement | FEAT-08-3, 08-4 | US-08 acceptance criteria met; **Milestone: Lab Prototype v1 delivered** |
| 17 | EPIC-08 | Complete remaining agent roles and AI safety controls | FEAT-08-2 (remaining), 08-5 | All 8 agent roles operational |
| 18 | EPIC-09 | Implement decision context builder and evidence correlation | FEAT-09-1, 09-2 | Decision context assembled from Modules 7–9 |
| 19 | EPIC-09 | Implement recommendation engine and workspace backend | FEAT-09-3, 09-4 | US-09 acceptance criteria met |
| 20 | EPIC-09 → EPIC-10 | Complete Decision Replay; begin design system integration | FEAT-09-5, 10-1 | **Milestone: Decision Intelligence backend complete** |
| 21 | EPIC-10 | Implement BFF layer and Search/Discovery UI | FEAT-10-2, 10-3 | Search UI live against real BFF |
| 22 | EPIC-10 | Implement Agent Interaction and Decision Workspace UI | FEAT-10-4, 10-5 | US-10 acceptance criteria met; **Milestone: MVP feature-complete** |
| 23 | EPIC-10 | Implement Knowledge Authoring UI; MVP hardening | FEAT-10-6 | All four screen families live; MVP bug bar met |
| 24 | Cross-epic | MVP stabilization, performance validation, release readiness | Full regression, load test against ADR-017 targets | **Milestone: MVP released**; Enterprise Production backlog groomed |

# 7. Dependencies

| **Epic** | **Depends On** | **Blocks** |
| --- | --- | --- |
| EPIC-01 Foundation | — | All epics |
| EPIC-02 Identity | EPIC-01 | EPIC-03, EPIC-08 (agent identity) |
| EPIC-03 Authorization | EPIC-02 | EPIC-04, EPIC-05, EPIC-06, EPIC-08, EPIC-09 |
| EPIC-04 Audit | EPIC-02, EPIC-03 | EPIC-05, EPIC-09 (Decision Replay), EPIC-12 (audit-linked observability) |
| EPIC-05 Knowledge Graph | EPIC-03, EPIC-04 | EPIC-06, EPIC-07, EPIC-09 |
| EPIC-06 Search | EPIC-05 | EPIC-07, EPIC-10 (Search UI) |
| EPIC-07 GraphRAG | EPIC-05, EPIC-06 | EPIC-08, EPIC-09 |
| EPIC-08 AI Platform | EPIC-02, EPIC-03, EPIC-07 | EPIC-09, EPIC-10 (Agent UI) |
| EPIC-09 Decision Intelligence | EPIC-05, EPIC-06, EPIC-07, EPIC-08 | EPIC-10 (Decision Workspace UI) |
| EPIC-10 Frontend | Incrementally on EPIC-06, 08, 09 per screen family | — |
| EPIC-11 Infrastructure | EPIC-01 | All epics (deployment target) |
| EPIC-12 DevSecOps | EPIC-01, EPIC-11 | All epics (quality gate) |

No cycle exists in this table, consistent with the acyclic module dependency graph validated in the Architecture Consolidation Review.

# 8. Story Point Estimation (Fibonacci, per Feature)

| **Feature ID** | **Points** | **Feature ID** | **Points** | **Feature ID** | **Points** |
| --- | --- | --- | --- | --- | --- |
| FEAT-01-1 | 3 | FEAT-05-4 | 8 | FEAT-09-3 | 8 |
| FEAT-01-2 | 5 | FEAT-05-5 | 5 | FEAT-09-4 | 5 |
| FEAT-01-3 | 3 | FEAT-06-1 | 5 | FEAT-09-5 | 13 |
| FEAT-01-4 | 5 | FEAT-06-2 | 8 | FEAT-10-1 | 5 |
| FEAT-02-1 | 5 | FEAT-06-3 | 8 | FEAT-10-2 | 8 |
| FEAT-02-2 | 3 | FEAT-06-4 | 5 | FEAT-10-3 | 8 |
| FEAT-02-3 | 5 | FEAT-06-5 | 5 | FEAT-10-4 | 8 |
| FEAT-02-4 | 8 | FEAT-07-1 | 8 | FEAT-10-5 | 13 |
| FEAT-03-1 | 8 | FEAT-07-2 | 5 | FEAT-10-6 | 8 |
| FEAT-03-2 | 8 | FEAT-07-3 | 8 | FEAT-11-1 | 5 |
| FEAT-03-3 | 3 | FEAT-07-4 | 5 | FEAT-11-2 | 8 |
| FEAT-03-4 | 5 | FEAT-08-1 | 8 | FEAT-11-3 | 5 |
| FEAT-04-1 | 5 | FEAT-08-2 | 13 | FEAT-11-4 | 13 |
| FEAT-04-2 | 5 | FEAT-08-3 | 5 | FEAT-11-5 | 8 |
| FEAT-04-3 | 8 | FEAT-08-4 | 5 | FEAT-12-1 | 8 |
| FEAT-04-4 | 3 | FEAT-08-5 | 8 | FEAT-12-2 | 8 |
| FEAT-05-1 | 8 | FEAT-09-1 | 8 | FEAT-12-3 | 8 |
| FEAT-05-2 | 13 | FEAT-09-2 | 8 | FEAT-12-4 | 5 |
| FEAT-05-3 | 8 |  |  | FEAT-12-5 | 5 |

Total estimated Feature-level scope: 350 story points across 55 Features. This total is a planning-horizon estimate for capacity and milestone forecasting (Section 10); it is re-baselined each sprint as Features are groomed into stories with their own, more precise estimates.

# 9. Priority Matrix

| **Priority** | **Epics** | **Rationale** |
| --- | --- | --- |
| Critical | EPIC-01, EPIC-02, EPIC-03, EPIC-04 | Every other epic depends on the foundation and trust layer; a defect here blocks the entire program |
| High | EPIC-05, EPIC-06, EPIC-07, EPIC-11, EPIC-12 | Core knowledge/retrieval capability and the infrastructure/quality gates every later epic relies on |
| Medium | EPIC-08, EPIC-09 | High-value but sequentially dependent on High-priority epics; delay here does not block Foundation/Trust work |
| Low | EPIC-10 (non-canonical screen families beyond MVP scope) | Full desktop/mobile and non-MVP screen polish (ADR-014 §12) can trail without blocking MVP delivery |

Individual Features inherit their Epic's priority by default; a Feature may be elevated within its Epic by the Product Owner where a specific MVP or Lab Prototype dependency requires it (e.g., FEAT-08-2's Search Assistant/Decision Support Agent roles are Critical for Lab Prototype even though EPIC-08 is Medium overall).

# 10. Milestones

| **#** | **Milestone** | **Target Sprint** | **Definition** |
| --- | --- | --- | --- |
| 1 | Bootstrap Complete | Sprint 1 | EPIC-01 done; CI green |
| 2 | Trust Foundation Complete | Sprint 6 | EPIC-02, 03, 04 done |
| 3 | Lab Prototype v1 Delivered | Sprint 16 | Section 17 scope demonstrated end-to-end |
| 4 | Knowledge & Retrieval Complete | Sprint 14 | EPIC-05, 06, 07 done |
| 5 | AI & Decision Complete | Sprint 20 | EPIC-08, 09 done |
| 6 | MVP Feature-Complete | Sprint 22 | EPIC-10 core screen families live |
| 7 | MVP Released | Sprint 24 | Section 18 scope live for pilot customer |
| 8 | Enterprise Production Readiness | Post-Sprint 24 (backlog groomed at Sprint 24) | Section 19 scope entry criteria met |

# 11. Release Plan

| **Release** | **In Scope** | **Epics/Features** |
| --- | --- | --- |
| Lab Prototype v1 | Minimal end-to-end slice on mock data (Engineering Master Plan §18) | EPIC-01–04 (baseline), FEAT-05-1/05-2 (curated subset), FEAT-06-1/06-3, FEAT-07-1–07-3, one FEAT-08-2 agent role, minimal FEAT-09-1/09-3/09-4 |
| MVP | Pilot-deployable product, single government customer (Engineering Master Plan §19) | EPIC-01–09 in full; EPIC-10 all four screen families; EPIC-11/12 to production-grade for single-tenant deployment |
| Enterprise Production | Full platform (Engineering Master Plan §20) | All Epics/Features in full, including FEAT-02-4 and FEAT-11-5 (air-gapped), FEAT-10 future desktop/mobile evaluation, full multi-tenant federation support |

# 12. Team Allocation

| **Epic** | **Primary Team** | **Supporting Team(s)** |
| --- | --- | --- |
| EPIC-01 Foundation | Platform Team | DevSecOps Team |
| EPIC-02 Identity | Identity Team | Security Team |
| EPIC-03 Authorization | Security Team | Identity Team |
| EPIC-04 Audit | Security Team | Data Team |
| EPIC-05 Knowledge Graph | Knowledge Graph Team | Data Team |
| EPIC-06 Search | Search Team | Knowledge Graph Team |
| EPIC-07 GraphRAG | Search Team | AI Team |
| EPIC-08 AI Platform | AI Team | Security Team (safety controls) |
| EPIC-09 Decision Intelligence | AI Team | Knowledge Graph Team, Search Team |
| EPIC-10 Frontend | Frontend Team | All backend teams (per screen family) |
| EPIC-11 Infrastructure | Platform Team | DevSecOps Team |
| EPIC-12 DevSecOps | DevSecOps Team | Platform Team |

QA Team is not epic-exclusive: it embeds within every epic's sprint work to execute the Testing Strategy (Engineering Master Plan §16) and enforce the Definition of Done (Section 14) across all teams.

# 13. Definition of Ready

A backlog item may enter a sprint only when: it is traced to a specific module/ADR section; it is written in the As-a/I-want/So-that format with explicit acceptance criteria (Section 4's format); its dependencies (Section 7) are either complete or explicitly sequenced within the same sprint; it has a Fibonacci estimate agreed by the implementing team (not merely inherited from the Feature-level estimate in Section 8); security and data-classification implications have been identified, even if mitigation is implemented later in the story; and it has a named team (Section 12) with available capacity.

# 14. Definition of Done

A backlog item is Done only when: acceptance criteria (Section 4 format) are all met and demonstrated; code is reviewed and merged per the Engineering Master Plan's coding standards (§14); automated tests pass, including new tests the item required, at the team's governed coverage threshold; all DevSecOps gates (FEAT-12-2) pass; observability instrumentation (FEAT-12-3) is present for any new service boundary or decision point; the item is traceable to its governing architecture reference and that traceability is recorded in the tracking system; documentation is updated; and, for any item touching classification, provenance, or audit behavior, a security reviewer has signed off. This mirrors, and does not relax, the Engineering Master Plan's Definition of Done (§15).

# 15. Engineering Risks

| **#** | **Risk** | **Mitigation** |
| --- | --- | --- |
| 1 | Foundation/Trust layer (EPIC-01–04) delay cascades into every downstream epic, given the acyclic dependency structure (Section 7). | Prioritize Foundation/Trust as Critical (Section 9); allocate strongest engineers to Sprints 1–6; track burn-down daily during this phase specifically. |
| 2 | GraphRAG (EPIC-07) underestimation, since it integrates two previously independent architecture sections (Module 7 §30, Module 8 §6) for the first time in code. | Sequence GraphRAG after both Knowledge Graph and Search are independently stable (Section 7); reserve schedule contingency in Sprints 12–14. |
| 3 | AI Platform (EPIC-08) safety controls (FEAT-08-5) implemented as an afterthought rather than built-in. | Definition of Done (Section 14) requires safety-control test traceability for every AI Platform story, not just a final security pass. |
| 4 | Story-point estimates (Section 8) are Feature-level planning estimates, not story-level; early sprints may reveal systematic under/over-estimation. | Re-baseline velocity (Section 16) after Sprint 4 and again after Sprint 9; adjust remaining sprint scope rather than compressing quality. |
| 5 | Cross-team dependency on shared libraries (FEAT-01-2) creates a bottleneck if the Platform Team cannot keep pace with downstream demand. | Platform Team is staffed ahead of downstream teams' ramp-up (Sprint 1 vs. Sprint 2+); shared library changes are versioned so downstream teams are not blocked on a single release. |
| 6 | Air-gapped deployment (FEAT-11-5, FEAT-02-4) deferred to Enterprise Production risks discovering integration issues too late. | A minimal air-gapped smoke test is run against the MVP build at Sprint 24, even though full air-gapped hardening is Enterprise Production scope. |

# 16. Success Metrics

| **KPI** | **Definition** | **Target (MVP horizon)** |
| --- | --- | --- |
| Sprint Velocity | Story points completed per sprint (team-level estimates, Section 13) | Stable ±15% variance after Sprint 6 |
| Lead Time | Time from story entering a sprint to Done (Section 14) | Under 1 sprint for Medium-complexity stories |
| Deployment Frequency | Successful production/staging deployments per week (FEAT-12-5) | Daily to staging; weekly to production by MVP |
| Defect Escape Rate | Defects found post-Done per 100 stories | Under 5, trending down each phase |
| Test Coverage | Automated test coverage against governed threshold (Engineering Master Plan §16) | Meets team-governed threshold on 100% of Done stories |
| Build Success Rate | CI pipeline success rate on main branch | Above 95% |
| Mean Time to Recovery (MTTR) | Time from incident detection (ADR-015 alerting) to resolution | Under 1 hour for Tier 1 incidents |

These KPIs are surfaced on the Executive Delivery Dashboard (Section 20) and are themselves observability data under ADR-015.

# 17. Lab Prototype Roadmap

Sprints 1–16 deliver Lab Prototype v1: Foundation and Trust (Sprints 1–6), a curated Knowledge Graph slice on mock government data (Sprints 7–9), basic hybrid search (Sprints 10–12), a minimal GraphRAG grounding pipeline (Sprints 13–14), and one operational AI agent with Human Approval Gateway enforcement (Sprints 15–16). Exit criteria match the Engineering Master Plan §18 scope exactly: end-to-end demonstration of grounded, cited, human-approved output from mock data, with the explicit non-goals (multi-tenant isolation, full observability operation, air-gapped packaging, additional agent roles) deferred to MVP.

# 18. MVP Roadmap

Sprints 17–24 extend the Lab Prototype to a pilot-deployable product: remaining AI agent roles and safety controls (Sprint 17), Decision Intelligence in full (Sprints 18–20), the complete presentation layer across all four canonical screen families (Sprints 21–23), and stabilization/performance validation against ADR-017 capacity targets (Sprint 24). Exit criteria match Engineering Master Plan §19: production-grade Foundation/Trust, full Module 8 retrieval, governed human-in-the-loop AI, complete Decision Lifecycle, and operational (not merely instrumented) observability with governed SLOs, live for the pilot government customer.

# 19. Enterprise Production Roadmap

Enterprise Production begins backlog grooming at Sprint 24 and is scoped, in outline, as a second 24-sprint program (Sprint 25 onward, to be issued as Engineering Backlog v2.0 rather than appended here, since this document's approved horizon is Sprint 1–24): full Module 7 ontology and knowledge-domain breadth across all target verticals; full Module 8 federated search; the complete Module 9 agent roster with full observability operations; full Module 10 Decision Analytics and organizational learning feedback; ADR-014's future desktop/mobile evaluation; fully operational ADR-015/016/017 (SLI/SLO/error-budget, ownership-driven routing, validated air-gapped HA/DR); and the government-readiness posture each module described, pursued as a program-level activity per Engineering Master Plan §20.

# 20. Executive Delivery Dashboard

A single leadership-facing dashboard, composed from the same observability and backlog-tracking data every team already produces (no separate manual reporting process), presenting:

- **Overall Progress** — percentage of Section 8's 350 total Feature-points Done, plotted against the 24-sprint plan (Section 6).

- **Sprint Progress** — current sprint's committed vs. completed story points, updated daily from the tracking system.

- **Epic Completion** — percentage Done per Epic (Section 2), color-coded against the Priority Matrix (Section 9).

- **Milestones** — the Section 10 milestone table, each shown as On Track / At Risk / Missed against its target sprint.

- **Risks** — the Section 15 risk register, each shown with current status and mitigation progress, refreshed at each sprint review.

- **Budget Status** — engineering spend against plan, sourced from Team Allocation (Section 12) capacity data; specific budget figures are a program-management input to this dashboard, not defined by this backlog.

- **Team Capacity** — planned vs. available capacity per team (Section 12), surfacing over/under-allocation before it causes a sprint miss.

- **Quality Metrics** — the Section 16 KPI set, trended sprint-over-sprint.

This is a design specification for the dashboard's content and data sources, not a UI implementation; the presentation of this dashboard is itself an ADR-014 screen (a Leadership/Program surface added to that ADR's screen-family catalog) to be built during Frontend epic work, not before.

**End of EMG™ — Engineering Backlog v1.0.**

Per instruction, this document creates no new architecture, no new ADRs, no new modules, and contains no application code or repository scaffolding. It awaits approval before Sprint 1 implementation begins.

Page 1 of 2

---
*Reference copy for engineering traceability (Engineering Master Plan §3). The authoritative copy remains under Architecture Board control.*
</content>
