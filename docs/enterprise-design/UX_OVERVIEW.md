# EMG Enterprise UX Architecture

> **Status — 2026-08-03.** Narrative context. The canonical design-system
> authority is `EMG_DESIGN_SYSTEM_BASELINE.md`; product scope is governed by
> `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md`. Where this document and
> either authority differ, that authority prevails.

## Vision

Create a high-trust enterprise interface where institutional memory, decisions, evidence and temporal truth are first-class UI objects.

## Design Principles

Evidence first, human authority over AI, provenance visibility, temporal accuracy, zero-trust security, enterprise information density.

## Personas

Personas are **frozen at Product Architecture Freeze §4** and are restated here
without alteration: Executive / Decision-maker, Knowledge Steward,
Analyst / Investigator, Contributor, Auditor / Regulator (external),
Platform Admin, Developer / Integrator, and AI Agent (non-human).

*Corrected 2026-08-03: this list previously named a "Security Administrator" and
omitted Contributor and Developer / Integrator, diverging from the frozen set.*

## Core Experiences

Knowledge Graph Explorer, Decision Timeline, Evidence & Source Viewer, and
Keyword Search with grounded "why" — the four surfaces frozen as MVP at Freeze
§24.

**Executive Dashboard** and **Grounded AI Copilot** are described here as future
experiences only. Both are **outside MVP** per PD-001, which additionally
prohibits placeholder executive metrics.

## Security UX

ABAC-aware rendering, tenant isolation, classification banners, emergency investigation mode.
