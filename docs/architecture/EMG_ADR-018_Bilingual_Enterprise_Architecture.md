# ADR-018 — Bilingual Enterprise Architecture (Arabic + English)

**Status:** Accepted
**Date:** 2026-07-24
**Deciders:** Product / Architecture (EMG Platform)
**Supersedes:** none (additive platform invariant)
**Related:** ADR-014 (Presentation), Module 7–10, Phase 2 Persistence Binding

---

## Context

EMG Platform targets government, defense, aviation, and large enterprises where
Arabic and English are both operational languages. Treating bilingual support as
a late UI concern produces incomplete knowledge graphs, broken search, and
ungrounded AI answers. Bilingual capability must be a **foundation-level**
platform requirement.

## Decision

EMG is a **bilingual enterprise intelligence platform (Arabic + English)** by
construction. Every layer that stores, retrieves, or presents institutional
memory must be designed for both languages from the start — not retrofitted.

### 1. Data & Knowledge Layer

- Ontology entities, relationships, metadata, and memory-graph nodes/edges
  **must** be able to carry Arabic and English content (labels, aliases,
  descriptions, terminology).
- The memory model **preserves**:
  - **original language** of each assertion (`source_language`);
  - **translated representation** when a translation exists
    (`translations` / language-tagged fields);
  - **multilingual relationships** (same real-world entity linked across
    language representations without collapsing provenance).
- Persistence stores UTF-8 content opaquely in authoritative snapshots
  (`graph_json`) and Neo4j `content_json` projections so Arabic/English
  payloads survive round-trips with canonical `content_hash` equality.
- Search and retrieval (Module 8+) **must** query across Arabic and English
  sources, including mixed-language corpora.

### 2. Document Intelligence

- Document ingestion **must** accept Arabic and English documents (and
  mixed-language documents).
- OCR, extraction, classification, chunking, and entity recognition pipelines
  **must** handle both languages (or explicitly fail closed with provenance when
  a language cannot be processed).
- Every extracted knowledge item retains **source language** and **provenance**
  (Module 6 / evidence refs).

### 3. AI Question Engine Readiness

- AI orchestration (Module 9+) **must** accept Arabic, English, and
  mixed-language questions.
- Users may ask in either language and receive grounded answers in their
  **preferred response language**.
- Citations, evidence references, confidence indicators, and auditability are
  **language-invariant** — they must appear regardless of question/answer
  language.

### 4. User Experience (ADR-014)

Frontend architecture **must** support:

- Arabic **RTL** interface
- English **LTR** interface
- Dynamic language switching (session/user preference)
- Enterprise terminology management (approved AR/EN term pairs)

### 5. Security note (identifiers)

Platform label/text validators continue to reject Unicode **bidirectional
control** characters used for spoofing. Legitimate Arabic and English letters,
digits, and punctuation in content fields remain permitted. Presentation-layer
directionality (RTL/LTR) is a UI concern and must not rely on embedding bidi
control marks in stored identifiers.

## Consequences

**Positive**

- Single product usable across GCC and international enterprises without a
  parallel “Arabic edition.”
- Knowledge graph and AI answers remain explainable across languages.
- Avoids costly schema/API rewrites after MVP.

**Negative / cost**

- Ontology, ingestion, search, AI, and UI epics gain explicit bilingual
  acceptance criteria.
- Test matrices grow (AR, EN, mixed).
- Terminology governance becomes a product capability.

**Phase 2 implication**

Phase 2 Persistence Binding does **not** yet introduce dedicated multilingual
columns. It **guarantees** opaque UTF-8 preservation of whatever bilingual
fields the domain model later carries inside `graph_json` / Neo4j
`content_json`, with hash-stable reconstruction. Domain-model enrichment
(source language, translation links) lands with knowledge/ingestion phases;
this ADR makes that work mandatory, not optional.

## Compliance

| Area | Evidence of compliance |
| --- | --- |
| Architecture status | Listed in `ARCHITECTURE_STATUS.md` ADR table |
| Roadmap | Executive + frontend roadmaps call out bilingual as core |
| Phase 2 | Persistence preserves Unicode content; bilingual readiness noted in Phase 2 docs |
| Future epics | EPIC-05…10 acceptance criteria must include AR/EN cases |

## References

- Product Vision — Enterprise Memory Graph
- ADR-014 — Enterprise Presentation Architecture
- `PHASE2_ARCHITECTURE.md` — authoritative `graph_json` snapshots
