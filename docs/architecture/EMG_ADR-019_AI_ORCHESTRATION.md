# ADR-019 — AI Orchestration Layer

**Status:** Proposed
**Date:** 2026-07-25
**Deciders:** Product / Architecture (EMG Platform)
**Supersedes:** none (additive)
**Related:** ADR-018 (Bilingual Enterprise Architecture), Module 9, AI APIs
(reference corpus §26, M07/M08), AI Agent Ecosystem (v2 reference corpus
Ch. 34), `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §4

---

## Context

`services/ai-orchestration` is scaffolded (`service.yaml`: owner "Chief AI
Officer," steward "AI Platform Team," `status: scaffolded`) with zero lines
of code (`IMPLEMENTATION_GAP_ANALYSIS.md` §3). A large reference corpus
already describes an AI vision — the v2.0 Enterprise Intelligence Platform
document's "AI Agent Ecosystem" (Ch. 34), "Enterprise Copilot" (Ch. 35), and
the API reference corpus's AI APIs (§26, M07/M08) — but that corpus is
either draft-status or vision-level, and it predates ADR-018. No document
currently makes a binding, implementation-ready decision for how AI
Orchestration is built against what actually exists in this repository today:
`emg-persistence` (Phase 2, PostgreSQL-authoritative graph store),
`emg-memory-graph`, `emg-semantic-layer`, `emg-trust-scoring`, and
`services/audit` (live).

## Problem

Three problems must be solved before `services/ai-orchestration` can be
implemented:

1. **Grounding.** An AI-generated answer must never assert a fact the
   platform cannot independently verify. Without a binding rule, an
   implementation could plausibly generate fluent, unsupported claims.
2. **Bilingual questions and answers.** ADR-018 §3 requires AI orchestration
   to accept Arabic, English, and mixed-language questions and answer in the
   user's preferred response language — but "preferred response language" is
   not the same field as UI `locale` (a user may browse in English and ask a
   question in Arabic expecting an Arabic answer), and no existing document
   distinguishes these two concepts.
3. **Auditability independent of language.** ADR-018 §3 requires citations
   and confidence indicators to be language-invariant. If citation assembly
   is implemented as a post-hoc step after answer generation, there is no
   structural guarantee the citation actually supports the specific claim in
   the specific language it was rendered in.

## Decision

`services/ai-orchestration` is built as a **stateless grounding-first
orchestrator**, not a generative-first one:

1. **Retrieval before generation.** Every question first resolves to a
   bounded set of graph facts (via `emg-memory-graph`, itself backed by
   `emg-persistence`) and their citations, before any answer text is
   produced. An answer generation step receives only already-cited facts as
   its input context; it is structurally prevented from asserting anything
   outside that set (enforced by construction, not by post-hoc fact-checking).
2. **Two distinct language fields.** The request carries `question_language`
   (detected or declared, informational) and `response_language` (explicit,
   defaults to the requester's session `locale` per
   `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §2, but independently
   overridable per request). Facts retrieved from the Knowledge Graph carry
   their own `source_language` (ADR-018 §1) untouched; the orchestrator
   selects or requests a `translations` entry matching `response_language`
   rather than translating on the fly, keeping translation an ingestion-time
   concern (ADR-020) rather than an AI-orchestration-time one.
3. **Audit emission is part of the request path, not a side effect.** Every
   answer, the facts used to produce it, and the requester's principal and
   language context are emitted to `services/audit` (Module 6, unchanged
   contract) synchronously as part of request handling — not queued for
   later, and not optional based on load.
4. **No persistent AI memory beyond session scope.** Any conversational
   context the orchestrator holds is bounded and session-scoped, mirroring
   ADR-014 §4's state-scoping principle; there is no new durable system of
   record introduced by this ADR.

## Alternatives Considered

- **Generate-then-verify** (produce an answer, then check its claims against
  the graph). Rejected: this permits a plausible-but-wrong answer to exist
  even momentarily, and verification-after-the-fact is inherently weaker than
  making unsupported claims structurally impossible to produce.
- **Single `language` field instead of `question_language` +
  `response_language`.** Rejected: collapses two independent user intents
  (what language did I ask in vs. what language do I want the answer in)
  into one, which would force every implementation to guess which one a
  single field means, exactly the kind of retrofit ADR-018 is meant to
  prevent.
- **Translate at answer time using a live translation call.** Rejected for
  this ADR's scope: makes AI Orchestration responsible for translation
  quality and consistency, duplicating what ADR-020 assigns to ingestion; a
  live-translation fallback for content with no existing `translations` entry
  is left as an explicit future extension (see Implementation Roadmap),
  not excluded, but not the default path.
- **Durable per-user AI memory store.** Rejected for this ADR: introduces a
  new system of record with its own retention/classification requirements
  before the grounding contract itself is even built; deferred to a future
  ADR if a product requirement for persistent AI memory emerges.

## Consequences

**Positive:** answers are structurally grounded rather than optionally
fact-checked; bilingual question/answer handling has one unambiguous field
pair instead of an overloaded single field; audit completeness cannot be
silently degraded under load since it is on the synchronous path.

**Negative / cost:** synchronous audit emission adds latency to every
request compared to fire-and-forget logging; retrieval-before-generation
requires the Knowledge Graph Expansion service (`services/knowledge-graph`,
`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §8) to exist and be queryable
before AI Orchestration can be meaningfully implemented — this ADR does not
remove that dependency.

## Security Implications

Retrieval must apply the requester's classification/clearance at the fact
level (same guarantee Search APIs already require, reference corpus §23) —
an answer must never surface a fact the requester could not read directly
via the Graph API. Because generation is scoped to already-retrieved,
already-authorized facts, this guarantee holds by construction rather than
requiring a separate content-filtering pass on generated text. Session-scoped
memory (Decision, point 4) must be purged on session expiry, consistent with
ADR-014 §7's offline/cache purge discipline.

## Implementation Roadmap

This ADR does not authorize implementation; it is the binding decision
future sprint(s) implement against, following the same sprint-by-sprint
review discipline used for Phase 2. Recommended sequence, consistent with
`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §10:

1. Question/response contract models (`question`, `question_language`,
   `response_language`, citation shape) — library-first, no service wiring,
   mirroring how every Module 7 feature shipped as a library before its
   service existed.
2. Retrieval-and-grounding binding against `emg-memory-graph` (read-only;
   no new persistence contract).
3. Audit-emission binding against the existing `services/audit` contract.
4. Answer formatting honoring `response_language` against existing
   `translations` entries (no live-translation fallback in this phase).
5. `services/ai-orchestration` service shell exposing the above via the
   Enterprise API Gateway (`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §6).
6. Live-translation fallback for ungrounded-language gaps — explicitly
   deferred past this roadmap, requiring its own review given translation-
   quality and classification implications.

Each numbered step is sized to be its own reviewed sprint, not a single
implementation pass.
