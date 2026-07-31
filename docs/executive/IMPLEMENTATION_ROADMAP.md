# Implementation Roadmap

**Classification:** L4 delivery and planning material
**Authority boundary:** This roadmap reports evidence and planning only. It
does not define product scope, architecture, or the scope of an undefined
delivery phase.

The implementation follows a capability-based roadmap:

1. **Foundation**: Evidenced (Repository bootstrap, identity, authorization, and audit platform established).
2. **Knowledge & Trust**: Libraries implemented (Core ontology, knowledge
   ingestion, validation, and trust-scoring libraries exist; live-service and
   platform-wide adoption remain incomplete).
3. **Durable Memory Substrate (Phase 2)**: Persistence libraries and live
   PostgreSQL/Neo4j integration tests are complete; the Knowledge Graph
   service's live Neo4j serving-projection binding remains open.
4. **Retrieval & Grounding**: Planned (Search layer and GraphRAG grounding pipeline).
5. **Agent Operations**: Planned (Operational AI agent deployment with human approval enforcement).
6. **Executive Surfaces**: Planned (BFF + bilingual UI per ADR-014 / ADR-018).

## ADR-027 Stage 4 Delivery Status

| Phase | Status |
| --- | --- |
| Phase 4A | **Complete** — HTTP/API delivery conformance is present on `develop` at `0726bde` |
| Phase 4B | **Not started — scope undefined** |
| Phase 4C | **Not started — scope undefined** |
| Phase 4D | **Not started — scope undefined** |
| Phase 4E | **Not started — scope undefined** |

This roadmap does not infer or propose objectives, sequencing, prerequisites,
or acceptance criteria for Phases 4B–4E.

## Cross-cutting invariant — Bilingual (Arabic + English)

Per **ADR-018**, bilingual support is a **core platform capability**, not a post-MVP add-on:

| Capability | Requirement |
| --- | --- |
| Knowledge graph | AR + EN content, source language, translations, multilingual links |
| Document intelligence | AR + EN OCR/extraction/classification/chunking/NER with provenance |
| AI question engine | AR, EN, and mixed questions; preferred-language grounded answers with citations |
| UX | Arabic RTL, English LTR, dynamic switching, terminology management |

Every delivery phase implementing bilingual product requirements must conform
to ADR-018 and the Product Architecture Freeze.

TBD — requires executive decision on target delivery dates for remaining roadmap phases.
