EMG™ — ADR-016: Enterprise Ownership Registry

**EMG™**

**ADR-016: Enterprise Ownership Registry**

*(Architecture Decision Record)*

Document Classification: Internal — Architecture Board Review

Document Type: Architecture Decision Record

ADR Number: ADR-016

Status: Accepted — Pending Architecture Baseline v1.0 Publication

Date: 2026-07-15

**Prepared For:**

Enterprise Architecture Board  •  CTO  •  CIO

Chief Data Officer  •  Chief AI Officer  •  Chief Information Security Officer

Government Technical Review Committee

# Table of Contents

Status

Context

Decision

Consequences

Compliance with Frozen Architecture

Related Modules and Documents

# Status

Accepted. This ADR closes Architecture Gap 3 identified in the EMG™ Architecture Consolidation Review (Section 8 and Section 12, Gap 3: ownership was "stated independently per module," with "no single consolidated ownership register" giving the Board one view across Modules 7–10). It is additive: it consolidates ownership assignments already stated across Modules 1–10 into a single authoritative registry and extends coverage to categories no module previously assigned ownership for.

# Context

Modules 7 through 10 each correctly named an accountable owner for their own layer — Module 7 to the Chief Data Officer, Module 8 jointly to the CDO and Chief AI Officer, Module 9 to the Chief AI Officer with the CISO for safety/security, and Module 10 jointly to the Chief AI Officer and Executive Decision Board — and the Consolidation Review confirmed none of these assignments conflict. But no document assembled them into one place, and several ownership categories the platform actually requires — individual APIs, individual AI agent roles, individual data domains, individual security controls — were never assigned an owner at all, only their parent module was. This ADR corrects both problems: it consolidates existing assignments and closes the coverage gap.

# Decision

EMG™ will maintain a single Enterprise Ownership Registry assigning an accountable owner and an operational steward to every module, API, AI agent, knowledge domain, data domain, policy, service, infrastructure component, documentation set, and security control in the platform. The registry, not any individual module document, is the authoritative source for "who owns this" going forward; module documents retain their existing ownership statements as consistent, non-contradictory summaries, but this registry is what ADR-015's alert routing (Section 10) and every future change-governance process consult.

**Ownership Model**

Two roles are assigned per registry entry, kept distinct so accountability and day-to-day operation are never conflated:

- **Accountable Owner** — the executive function ultimately accountable for the item's correctness, quality, and governance approval, consistent with each module's existing Governance section (e.g., Module 7 Section 24, Module 9 Section 15, Module 10 Section 14).

- **Operational Steward** — the role or team responsible for day-to-day quality, change proposals, and operational health, reporting into the Accountable Owner.

Every registry entry also names its **Governing Architecture** — the module, ADR, or baseline document whose rules that item must comply with — so ownership is never assigned in a way that contradicts the architecture the item is subject to.

**1. Modules**

| **#** | **Item** | **Accountable Owner** | **Operational Steward** | **Governing Architecture** |
| --- | --- | --- | --- | --- |
| 1 | Module 4 — Identity & Authentication | CISO | Identity Platform Team | Module 4, ADR-013 |
| 2 | Module 5 — Authorization & Policy | CISO | Policy Platform Team | Module 5 |
| 3 | Module 6 — Audit, Provenance & Digital Evidence | CISO / Chief Data Officer (joint) | Audit Platform Team | Module 6 |
| 4 | Module 7 — Knowledge Graph Platform | Chief Data Officer | Ontology Steward (Module 7, Section 14) | Module 7 |
| 5 | Module 8 — Search, GraphRAG & Retrieval | Chief Data Officer / Chief AI Officer (joint) | Retrieval Platform Team | Module 8 |
| 6 | Module 9 — AI Orchestration & Agents | Chief AI Officer | AI Platform Team; CISO for safety controls | Module 9 |
| 7 | Module 10 — Decision Intelligence | Chief AI Officer / Executive Decision Board (joint) | Decision Intelligence Team | Module 10 |
| 8 | Presentation Layer (ADR-014) | CIO | Design System Owner; per-surface teams | ADR-014 |
| 9 | Observability Platform (ADR-015) | CTO | Platform SRE Team | ADR-015 |

**2. APIs**

Every API surface exposed through the Enterprise API Architecture's gateway is owned by the Accountable Owner of the module that implements it (Section 1); no API is permitted to exist without a named entry in this registry. BFF-layer APIs (ADR-014, Section 3) are owned by the CIO function, consistent with their presentation-aggregation role, and hold no independent business-logic ownership. New APIs are registered at design time, before implementation, as part of the Enterprise API Architecture's existing governance process.

**3. AI Agents**

Every agent role defined in Module 9 Section 5 is individually registered, not owned only at the "Module 9" level, because agent roles carry distinct behavioral boundaries requiring distinct accountability:

| **#** | **Agent Role** | **Accountable Owner** | **Operational Steward** |
| --- | --- | --- | --- |
| 1 | Executive Advisor Agent | Chief AI Officer | AI Platform Team |
| 2 | Investigation Agent | Chief AI Officer | AI Platform Team; Investigations domain steward |
| 3 | Risk Intelligence Agent | Chief AI Officer | AI Platform Team; Risk domain steward |
| 4 | Compliance Agent | Chief AI Officer | AI Platform Team; CISO (policy conformance) |
| 5 | Knowledge Analyst Agent | Chief Data Officer | Ontology Steward (Module 7, Section 14) |
| 6 | Decision Support Agent | Chief AI Officer / Executive Decision Board | Decision Intelligence Team |
| 7 | Search Assistant Agent | Chief Data Officer / Chief AI Officer | Retrieval Platform Team |
| 8 | Document Intelligence Agent | Chief Data Officer | Ontology Steward (Module 7, Section 14) |

New agent roles are registered, and their authorization scope reviewed, before deployment, consistent with Module 9 Section 15's approval process.

**4. Knowledge Domains**

Knowledge domains (the domain groupings within Module 7's ontology, Section 4 — Organizational, Asset & Operational, Governance, Risk & Safety, Decision, Knowledge & AI, Process) are each assigned a domain steward under Module 7 Section 24's existing stewardship model; this registry consolidates those assignments in one place rather than requiring a reader to derive them from ontology documentation. The Ontology Steward (Module 7, Section 14) remains the cross-domain accountable authority for consistency across all knowledge domains.

**5. Data Domains**

Distinct from knowledge domains (which are graph-native), data domains covering source-system and operational data feeding Module 7's ingestion pipeline (Module 7, Section 8) are owned by the Chief Data Officer function, with per-source-system stewardship assigned to whichever business function owns that source system operationally. This closes a coverage gap: no prior module named an owner for source data quality upstream of ingestion.

**6. Policies**

Policy and Regulation entities (Module 7, Section 5) are owned by the Chief Information Security Officer for platform-internal policy (authorization rules, Module 5) and by the relevant government/regulatory affairs function for external Regulation entities represented in the graph; the Compliance Agent (Section 3) operates under, and does not alter, this ownership.

**7. Services**

Backend services implementing each module's architecture (Modules 4–10) are owned by the same Accountable Owner named in Section 1 for the module they implement; this registry does not introduce a separate service-level ownership tier beneath the module level, to avoid the fragmentation the Consolidation Review flagged as a governance risk.

**8. Infrastructure**

Underlying infrastructure (compute, storage, network, and deployment environments, including air-gapped/on-premises environments per Module 9 Section 7) is owned by the CTO function, with capacity and scaling decisions governed jointly with the Accountable Owner of each module per ADR-017's capacity model.

**9. Documentation**

Architecture documentation (Product Vision through this ADR) is owned by the Enterprise Architecture Board as a body, with the Chief Enterprise Architect role accountable for document integrity and version control (Section: Version History in the forthcoming Architecture Baseline v1.0). Module-specific documentation sections remain attributed to that module's Accountable Owner (Section 1) for content accuracy.

**10. Security Controls**

Security controls spanning identity, authorization, audit, and AI/agentic-specific safeguards (Modules 4–6; Module 9, Sections 13, 16–17) are owned by the CISO function platform-wide; layer-specific security extensions (Module 7 Section 21, Module 8 Section 10, Module 10 Section 15) remain owned by their module's Accountable Owner (Section 1) but are subject to CISO review for consistency, consistent with the Security Consistency Review finding in the Architecture Consolidation Review.

# Consequences

**Positive:** every category the Consolidation Review flagged as ambiguously or only implicitly owned now has a named Accountable Owner and Operational Steward; ADR-015's alert routing and future change-governance processes have a single authoritative source to consult rather than needing to infer ownership from module text.

**Trade-offs:** several items (agent roles, data domains, individual security controls) now carry more granular ownership than before, which requires the named functions to actively maintain their registry entries as the platform evolves rather than relying on module-level ownership statements alone.

# Compliance with Frozen Architecture

This ADR modifies no approved module and does not reassign any ownership already stated in Modules 7–10; every module-level assignment in Section 1 matches the owning module's own Governance section exactly. This ADR only adds registry structure and closes previously unassigned categories.

# Related Modules and Documents

Module 5 (Authorization & Policy); Module 6 (Audit, Provenance & Digital Evidence); Module 7, Sections 14, 24; Module 8, Section 14; Module 9, Sections 5, 15; Module 10, Section 14; ADR-014 (presentation ownership); ADR-015 (ownership-driven alerting); ADR-017 (infrastructure capacity ownership).

**End of ADR-016 — Enterprise Ownership Registry.**

Page 1 of 2

---
*Reference copy for engineering traceability (Engineering Master Plan §3). The authoritative copy remains under Architecture Board control.*
</content>
