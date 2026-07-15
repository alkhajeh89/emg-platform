EMG™ — ADR-014: Enterprise Presentation Architecture

**EMG™**

**ADR-014: Enterprise Presentation Architecture**

*(Architecture Decision Record)*

Document Classification: Internal — Architecture Board Review

Document Type: Architecture Decision Record

ADR Number: ADR-014

Status: Accepted — Pending Architecture Baseline v1.0 Publication

Date: 2026-07-15

**Prepared For:**

Enterprise Architecture Board  •  CTO  •  Chief Software Architect

Chief Platform Architect  •  CIO  •  Government Technical Review Committee

# Table of Contents

Status

Context

Decision

Consequences

Compliance with Frozen Architecture

Related Modules and Documents

# Status

Accepted. This ADR closes Architecture Gap 1 identified in the EMG™ Architecture Consolidation Review (Section 12, Gap 1: "Presentation-layer architecture... mandatory before end-to-end UI implementation of any Module 7–10 capability can begin"). It is additive: it operationalizes the approved Enterprise UX Architecture & Design System against the specific surfaces Modules 7–10 assume exist, and modifies no approved document or module.

# Context

Modules 7 through 10 each defined the capability their layer exposes — Search (Module 8), the Human Decision Workspace (Module 10, Section 13), Agent interaction (Module 9, Section 5), and knowledge-authoring surfaces (Module 7, Section 8) — and each explicitly deferred the presentation layer to "a future presentation-layer module," consistent with their approved scope. The Enterprise Architecture Consolidation Review confirmed this deferral was consistent across all four modules but identified that no architecture yet exists to operationalize the approved Enterprise UX Architecture & Design System against these specific surfaces, and named this the primary blocker to full end-to-end implementation readiness.

This ADR closes that gap. It does not redesign the Enterprise UX Architecture & Design System; it extends it with the platform-specific composition, integration, security, and governance architecture needed to build the EMG™ presentation layer consistently across every backend capability defined in Modules 4–10.

# Decision

EMG™ will adopt a single, unified Enterprise Presentation Architecture governing every user-facing surface of the platform — Search, Knowledge authoring, Agent interaction, and Decision support alike — built on a Backend-for-Frontend integration pattern, a shared component-based composition model, and the same Zero Trust, classification-aware security posture already established across Modules 4–10. No screen, workspace, or client is authorized to bypass this architecture or to integrate directly against internal module APIs outside the BFF layer.

**1. Presentation Architecture Principles**

- **One design language, many surfaces.** Every EMG™ client — Search, Knowledge Authoring, Agent Interaction, Human Decision Workspace — is built from the same component and token set defined by the Enterprise UX Architecture & Design System; no surface may introduce a parallel visual or interaction language.

- **Backend parity, not backend exposure.** The presentation layer exposes what each backend module already governs (Module 5 authorization, Module 8 retrieval, Module 9 grounding, Module 10 decision lifecycle); it introduces no new business logic, authorization rule, or data transformation of consequence — those remain owned by their respective modules.

- **Explainability is a presentation obligation, not just a backend guarantee.** Every citation, confidence score, and provenance chain that Modules 7–10 guarantee is retrievable must be genuinely surfaced in the UI, not just theoretically available via API.

- **Human authority stays visible.** Every screen touching AI-assisted content (Module 9, Module 10) visually and structurally distinguishes AI-generated material from human-authored or human-approved material, consistent with Module 9 Section 12's transparency principle.

- **Progressive disclosure over data dump.** Complex context (decision briefings, evidence correlation, graph neighborhoods) is presented in layered, navigable form — summary first, detail on demand — never as an undifferentiated data export.

**2. UI Composition**

The presentation layer is composed from a shared library of governed, versioned components mapped directly to the Enterprise UX Architecture & Design System's token and component catalog. Screens are assembled by composing these components rather than by screen-specific one-off construction, so that a change to a shared component (e.g., a citation display element) propagates consistently to every surface that uses it — Search results, Decision Briefings, and Agent responses alike. Composition is layered: primitive design-system components (buttons, inputs, cards) compose into EMG™-specific patterns (a Citation Chip, an Evidence Card, a Confidence Badge), which in turn compose into full screens. No screen may introduce a bespoke pattern for a concept already defined at the EMG™-pattern layer.

**3. BFF Strategy**

Each major capability area is served by its own Backend-for-Frontend (BFF) layer — a thin, presentation-oriented aggregation and shaping layer sitting between the client and the governed backend APIs (Enterprise API Architecture; Modules 5–10) — rather than clients calling multiple backend module APIs directly. The BFF's responsibilities are strictly bounded: request aggregation, response shaping for a specific screen or surface, and session-scoped caching of already-authorized data. The BFF performs no independent authorization decision-making (it forwards the caller's identity and context to Module 5's Policy Enforcement Point exactly as any other API consumer) and holds no independent system-of-record data. This keeps the BFF replaceable and prevents it from becoming a shadow business-logic layer.

**4. Frontend Architecture**

The frontend is a component-based, composition-first architecture (Section 2) with a clear separation between presentation components, screen-level composition, and cross-cutting concerns (authentication session handling, telemetry emission per ADR-015, and error/empty-state handling per the Enterprise UX Architecture & Design System). State is scoped as narrowly as possible: transient UI state remains client-local, session-relevant state is held only as long as Module 9 Section 8's Session Memory lifecycle permits, and no durable organizational data is ever cached client-side beyond a governed, short-lived, classification-aware cache subject to the same access controls as the originating API call. No specific frontend framework, library, or rendering technology is prescribed by this ADR; the architecture is designed to be implementable on any modern component-based frontend technology consistent with the enterprise's technology standards.

**5. Screen Composition**

Four canonical screen families are defined, each composed from the shared component set (Section 2) and each mapped to its owning backend capability:

- **Search & Discovery surfaces** (Module 8) — query input, hybrid result presentation, citation-attached results, and Explainable Retrieval detail views (Module 8, Section 13).

- **Knowledge Authoring & Stewardship surfaces** (Module 7) — candidate entity/relationship review, validation workflow, and ontology governance views (Module 7, Sections 7, 9, 14).

- **Agent Interaction surfaces** (Module 9) — conversational and task-based interaction with agent roles (Module 9, Section 5), always rendering grounding context and citations alongside generated content.

- **Human Decision Workspace surfaces** (Module 10, Section 13) — Decision Briefing, Executive Summary, Evidence Visualization, Confidence Display, and Alternative Comparison views, composed exactly to the content requirements Module 10 Section 13 already specifies.

New screens within these families are composed from existing patterns wherever possible; a genuinely new screen family requires governance review (Section 8) before a new pattern is introduced.

**6. Client Security**

The presentation layer inherits, and does not weaken, the platform's Zero Trust posture: every client session is authenticated via Module 4 identity, every BFF request is authorized via Module 5's Policy Enforcement Point, and no client is issued a standing credential broader than the session it is actively serving. Classification-aware rendering is mandatory: a component displaying entity, evidence, or decision content must honor property-level redaction (Module 7, Section 21) at render time, not merely rely on the API having already filtered the payload, so that a client-side defect cannot silently over-display cached or partially-rendered content. Client-side telemetry (ADR-015) is itself classification-aware and never captures restricted content in logs, screenshots, or error reports without redaction.

**7. Offline Strategy**

Consistent with Module 9's air-gapped deployment support, EMG™ presentation clients support a defined offline/degraded-connectivity mode for field and disconnected government/defense use cases: read access to previously authorized and locally cached (classification-bounded, time-limited) content continues; write actions (Decision Approval, knowledge validation, agent-invoked actions) are queued locally and only committed once connectivity to the governed backend and its Policy Enforcement Point is restored — no consequential action is permitted to execute purely client-side while disconnected. Cached offline content is subject to the same classification and retention discipline as its online counterpart and is purged on session expiry or device de-authorization.

**8. Presentation Governance**

Ownership of the Enterprise Presentation Architecture sits jointly with the CIO function (platform-wide consistency) and the design system owner designated under the Enterprise UX Architecture & Design System, with each backend module's owning function (Section 8 of Modules 7–10, and this ADR's registry counterpart in ADR-016) accountable for the accuracy of what its screens present. Changes to shared components follow the same additive-only, ADR-based change discipline as the rest of EMG™'s frozen architecture; a breaking change to a shared component requires Enterprise Architecture Board review given its cross-surface blast radius. New screen families (Section 5) and any change to client security posture (Section 6) require Architecture Board approval before implementation.

**9. Accessibility**

Every EMG™ client conforms to the accessibility standards already established in the Enterprise UX Architecture & Design System; this ADR adds no new accessibility standard but makes conformance an explicit, non-waivable acceptance criterion for every screen family in Section 5, given the platform's government and public-sector user base. Accessibility conformance is verified as part of Presentation Governance review (Section 8), not left to individual implementation teams to self-certify.

**10. Design System Integration**

The Enterprise Presentation Architecture is, by design, a consumer of the Enterprise UX Architecture & Design System, not a parallel design authority. Every component in Section 2's composition hierarchy traces to a design-system-defined token or pattern; where a genuinely new pattern is needed for an EMG™-specific concept (e.g., a Confidence Badge, Section 2), it is proposed into the design system's own governance process rather than defined unilaterally within a single module's presentation layer, keeping the design system authoritative for visual and interaction standards platform-wide.

**11. Human-Centered Design**

Every screen family in Section 5 is designed around the accountable human decision-maker, investigator, steward, or analyst it serves, not around the AI or backend capability producing the content — directly reflecting the Enterprise AI Vision (Module 9, Section 3) that AI augments rather than replaces human judgment. This means presenting alternatives and dissenting evidence alongside recommendations (Module 10, Section 13), never defaulting to a single suggested answer; making the confidence and provenance of every claim as prominent as the claim itself; and designing approval and override actions (Module 9, Section 11; Module 10, Section 9) as clear, deliberate, unambiguous user actions rather than passive acceptances.

**12. Future Desktop/Mobile Strategy**

This ADR establishes web-based presentation as the baseline surface for EMG™. Native desktop and mobile clients are a recognized future direction, particularly for field, investigative, and disconnected-operation use cases (Section 7), but are not designed in this ADR. Any future desktop or mobile client must consume the same BFF layer (Section 3) and component/token contracts (Section 2, Section 10) rather than establishing an independent integration or design path, and must be proposed through its own ADR before implementation begins.

# Consequences

**Positive:** a single, governed presentation architecture prevents the four backend layers (Modules 7–10) from each accumulating a bespoke, inconsistent UI; the BFF pattern keeps authorization and business logic correctly owned by backend modules rather than duplicated client-side; and human-centered, explainability-first screen design directly reinforces the platform's core accountability guarantees rather than undermining them at the last mile.

**Trade-offs:** a shared component and BFF strategy requires cross-team coordination that a fully independent per-module frontend would not; teams building Module 7–10 backend capability cannot treat their presentation surface as a purely local concern and must coordinate through Presentation Governance (Section 8) for shared-component changes.

# Compliance with Frozen Architecture

This ADR modifies no approved document. It does not redesign the Enterprise UX Architecture & Design System, and it does not alter any API, authorization, audit, knowledge, retrieval, AI, or decision architecture defined in Modules 4–10; it strictly consumes those governed interfaces from the presentation layer, as each module already anticipated.

# Related Modules and Documents

Enterprise UX Architecture & Design System; Enterprise API Architecture; Module 4 (Identity); Module 5 (Authorization & Policy); Module 7, Section 8 (Knowledge Ingestion) and Section 21 (Security); Module 8, Section 13 (Explainable Retrieval); Module 9, Sections 3, 5, 8, 11, 12; Module 10, Section 13 (Human Decision Support); ADR-015 (client telemetry integration); ADR-016 (presentation ownership registry entries).

**End of ADR-014 — Enterprise Presentation Architecture.**

Page 1 of 2

---
*Reference copy for engineering traceability (Engineering Master Plan §3). The authoritative copy remains under Architecture Board control.*
