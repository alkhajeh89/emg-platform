# Implementation Roadmap

The implementation follows a phased, capability-based roadmap:

1. **Foundation**: Evidenced (Repository bootstrap, identity, authorization, and audit platform established).
2. **Knowledge & Trust**: Declared (Core ontology, knowledge ingestion, validation, and trust scoring library implementation).
3. **Durable Memory Substrate (Phase 2)**: In progress — PostgreSQL-authoritative graph persistence + Neo4j serving projection.
4. **Retrieval & Grounding**: Planned (Search layer and GraphRAG grounding pipeline).
5. **Agent Operations**: Planned (Operational AI agent deployment with human approval enforcement).
6. **Executive Surfaces**: Planned (BFF + bilingual UI per ADR-014 / ADR-018).

## Cross-cutting invariant — Bilingual (Arabic + English)

Per **ADR-018**, bilingual support is a **core platform capability**, not a post-MVP add-on:

| Capability | Requirement |
| --- | --- |
| Knowledge graph | AR + EN content, source language, translations, multilingual links |
| Document intelligence | AR + EN OCR/extraction/classification/chunking/NER with provenance |
| AI question engine | AR, EN, and mixed questions; preferred-language grounded answers with citations |
| UX | Arabic RTL, English LTR, dynamic switching, terminology management |

Every phase after foundation must include bilingual acceptance criteria.

TBD — requires executive decision on target delivery dates for remaining roadmap phases.
