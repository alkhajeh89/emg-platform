EMG™ — ADR-017: Enterprise Capacity & Scalability Model

**EMG™**

**ADR-017: Enterprise Capacity & Scalability Model**

*(Architecture Decision Record)*

Document Classification: Internal — Architecture Board Review

Document Type: Architecture Decision Record

ADR Number: ADR-017

Status: Accepted — Pending Architecture Baseline v1.0 Publication

Date: 2026-07-15

**Prepared For:**

Enterprise Architecture Board  •  CTO  •  Chief Data Officer

Chief AI Officer  •  Chief Information Security Officer  •  Government Technical Review Committee

# Table of Contents

Status

Context

Decision

Consequences

Compliance with Frozen Architecture

Related Modules and Documents

# Status

Accepted. This ADR closes Architecture Gap 2 identified in the EMG™ Architecture Consolidation Review (Section 11 and Section 12, Gap 2: "no cross-layer capacity model exists showing how load compounds through the full Knowledge → Retrieval → AI → Decision pipeline," previously "only addressed per-layer"). It is additive: it unifies, without redefining, the per-layer scalability strategies already established in Modules 7–9.

# Context

Module 7 Section 22 (Scalability Strategy), Module 8's query and complexity governance, and Module 9's routing and fallback strategy (Section 7) each correctly addressed scalability within their own layer. The Consolidation Review found no model showing how load compounds across layers — a single Search request may trigger Knowledge Graph traversal (Module 7), retrieval ranking (Module 8), AI grounding and reasoning (Module 9), and, for decision-support requests, the full Decision Lifecycle (Module 10) — and no enterprise-wide capacity, high-availability, or disaster-recovery model existed to plan against.

# Decision

EMG™ will adopt a single Enterprise Capacity & Scalability Model that governs cross-layer capacity planning, horizontal and vertical scaling, high availability, and disaster recovery for the platform as a whole, treating each module's existing per-layer scalability strategy (Module 7 Section 22, Module 8, Module 9 Section 7) as a governed input rather than replacing any of them.

**1. Capacity Planning**

Capacity is planned against compounded, not isolated, load: a single logical request (e.g., a Decision Support Agent invocation) is modeled as a chain — Knowledge Graph traversal (Module 7) → Retrieval/GraphRAG (Module 8) → AI Reasoning Lifecycle (Module 9) → Decision Lifecycle (Module 10) — and capacity for each layer is planned against the peak compounded request rate flowing through that chain, not against each layer's request rate in isolation. Capacity plans are reviewed jointly by the CTO function and each layer's Accountable Owner (ADR-016) on a governed periodic cadence and ahead of any known peak-demand event (e.g., a government reporting cycle).

**2. Horizontal Scaling**

Every module's services (Modules 4–10) are designed to scale horizontally as the default scaling strategy, consistent with Module 7 Section 22's storage-independence principle and Module 8/9's stateless-request-handling design; horizontal scaling is bounded by each layer's own architectural constraints (e.g., Module 7 Section 22's query pattern separation between shallow and deep traversal, which may scale differently). No module's architecture requires a single, non-horizontally-scalable component on the critical request path.

**3. Vertical Scaling**

Vertical scaling is treated as a bounded, secondary strategy — appropriate for components with inherently stateful or traversal-depth-sensitive characteristics (e.g., deep Knowledge Graph traversal, Module 7 Section 22) where horizontal scaling alone does not proportionally reduce latency — and is never the sole scaling strategy for a component on the compounded request chain (Section 1), to avoid a single-instance bottleneck reappearing at enterprise scale.

**4. High Availability**

Every layer in the compounded request chain (Section 1) is designed for redundancy sufficient to avoid a single point of failure, consistent with Module 9 Section 7's fallback strategy (model/provider failover) extended as the platform-wide HA pattern: each module maintains redundant service instances, and cross-layer HA is validated against the full chain, not per layer in isolation — a Module 8 outage's effect on Module 10 decision availability is an explicit HA planning scenario, not an implicit assumption.

**5. Disaster Recovery**

Disaster recovery is planned around the same trust foundation every module already depends on: Module 6's audit and provenance records and Module 7's bitemporal knowledge state are the recovery baseline for the entire platform, since every other layer (Search, AI, Decision) is reconstructable from Knowledge Graph state plus reprocessing, but Module 6/7 state itself is not independently reconstructable and therefore carries the platform's most stringent recovery point and recovery time objectives. Air-gapped and on-premises deployments (Module 9, Section 7) additionally require a documented, tested disaster recovery procedure that does not assume connectivity to any external service.

**6. Performance Targets**

Performance targets are set as SLOs under ADR-015's Unified Enterprise Observability model (ADR-015, Section 12), using this ADR's capacity model as the planning basis; this ADR does not itself fix numeric targets (e.g., specific latency thresholds), since those are implementation-phase decisions dependent on selected technology and deployment scale, but establishes that every SLO must be traceable to a capacity plan produced under Section 1, not set arbitrarily.

**7. AI Capacity**

AI capacity (model routing throughput, air-gapped model capacity, human-approval-gateway throughput) is planned against the AI Reasoning Lifecycle's compounded load (Section 1), with particular attention to the Human Approval Gateway (Module 9, Section 4) as a potential bottleneck distinct from model compute capacity — human review throughput does not scale the way compute does, and capacity planning must size approval-chain staffing and routing (Module 10, Section 14) alongside infrastructure capacity, not treat AI capacity as a purely technical dimension.

**8. Knowledge Graph Scaling**

Extends Module 7 Section 22 without redefinition: concept-count scalability (ontology growth), storage-technology independence via the Semantic Layer, and the shallow/deep traversal query pattern separation remain exactly as Module 7 specified; this ADR adds that Knowledge Graph scaling must be planned against the compounded request chain (Section 1), since Search and AI-layer demand, not only direct graph queries, now drive graph load.

**9. Search Scaling**

Search and retrieval scaling follows Module 8's existing query complexity and rate governance, planned here against compounded AI-agent-driven retrieval demand (Module 9's agents issuing retrieval as part of grounding, Module 8 Section 6) in addition to direct human search demand, since agent-driven retrieval volume can substantially exceed direct human query volume at enterprise scale.

**10. Storage Growth**

Storage growth is planned across three distinct growth curves that scale differently and must be forecast separately: Knowledge Graph entity/relationship/version growth (Module 7, Section 13's versioning model, which is append-only and therefore monotonically growing), Module 6 audit/provenance/evidence growth (also append-only, with the most stringent retention and integrity requirements), and observability telemetry growth (ADR-015, typically the highest-volume but shortest-retention data class). Retention and archival policy (Module 7, Section 7's archiving lifecycle stage) is the primary lever for managing the first two; telemetry sampling and tiered retention is the primary lever for the third.

**11. Future Expansion**

This capacity model is designed to extend to future federation scenarios (Module 7, Section 35: Multi-Graph Federation, Government Knowledge Federation) without redesign: capacity planning at federation scale is modeled as multiple independently-capacity-planned instances of this same model, coordinated rather than merged, consistent with Module 7 Section 35's federation principles. Numeric capacity targets for federated scenarios are out of scope for this ADR and would be addressed by the ADR proposing federation itself, per Module 7 Section 35's own governance note.

# Consequences

**Positive:** capacity, HA, and DR planning now account for compounded cross-layer load instead of four independent, potentially inconsistent per-layer plans; Section 5's DR prioritization gives engineering a clear, architecture-grounded basis for recovery sequencing; and Section 7's explicit treatment of human-approval throughput as a capacity dimension prevents a purely infrastructure-focused capacity plan from missing a real-world bottleneck.

**Trade-offs:** cross-layer capacity planning (Section 1) requires coordination across every module's Accountable Owner (ADR-016) rather than allowing each layer to plan independently, which is a governance overhead the platform did not previously require.

# Compliance with Frozen Architecture

This ADR modifies no approved module. Module 7 Section 22, Module 8's complexity governance, and Module 9 Section 7's fallback strategy remain exactly as approved; this ADR adds the cross-layer compounded-load model and the two previously unaddressed dimensions (Disaster Recovery prioritization, Section 5; human-approval throughput as AI capacity, Section 7) around them.

# Related Modules and Documents

Module 6 (Audit, Provenance & Digital Evidence); Module 7, Sections 7, 13, 22, 35; Module 8 (query/complexity governance); Module 9, Sections 4, 7; Module 10, Section 14; ADR-015 (SLO/error-budget basis); ADR-016 (capacity planning ownership).

**End of ADR-017 — Enterprise Capacity & Scalability Model.**

Page 1 of 2

---
*Reference copy for engineering traceability (Engineering Master Plan §3). The authoritative copy remains under Architecture Board control.*
</content>
