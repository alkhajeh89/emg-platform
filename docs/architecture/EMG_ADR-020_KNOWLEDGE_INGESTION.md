# ADR-020 — Knowledge Ingestion Layer

**Status:** Proposed
**Date:** 2026-07-25
**Deciders:** Product / Architecture (EMG Platform)
**Supersedes:** none (additive)
**Related:** ADR-018 (Bilingual Enterprise Architecture), Module 7 (FEAT-05-2),
Knowledge APIs (reference corpus §28, M02),
`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §5

---

## Context

`emg-knowledge-pipeline` (1,407 LOC, 7 tests) already implements a complete,
storage-independent ingestion pipeline: ingestion request models, an
ingestion context, a conformance/bounds/duplicate/cycle validator,
deterministic idempotent id generation, entity/relationship resolvers, batch
dependency ordering, a `GraphStore` + transaction abstraction with an
in-memory adapter, and Module-6 audit-contract emission
(`ARCHITECTURE_STATUS.md` Sprint 10 notes). It deliberately has **no Neo4j
binding, no document intake, no OCR, and no live service** —
`services/knowledge-graph` remains scaffolded. ADR-018 §2 requires document
ingestion to accept Arabic, English, and mixed-language documents, with OCR,
extraction, classification, and chunking pipelines handling both languages or
explicitly failing closed with provenance. No existing document specifies
how that requirement is met against the pipeline that actually exists.

## Problem

1. **Where does `source_language` get assigned?** It must be assigned once,
   authoritatively, at ingestion — not re-derived downstream by AI
   Orchestration or left for the frontend to guess.
2. **What happens to a document EMG cannot process?** ADR-018 §2 requires
   "fail closed with provenance" rather than silent mis-processing, but the
   existing pipeline's validator was designed around ontology conformance,
   not language-processing failure — this is a new failure mode the existing
   validator does not model.
3. **Where do translations come from, and can they be trusted the same as
   the original?** ADR-018 §1 requires preserving both the original-language
   assertion and a translated representation "when a translation exists" —
   this is silent on whether ingestion is required to produce a translation
   proactively, or only preserve one if supplied.
4. **Server-assigned trust boundary.** The existing pipeline already treats
   `owner`, `provenance_reference`, and `trust_score` as server-assigned,
   never caller-supplied (Sprint 10 note). Language fields need the same
   trust boundary decided explicitly, or an implementation could plausibly
   trust a caller-supplied `source_language` and create a mislabeling attack
   surface.

## Decision

1. **`source_language` is server-detected, assigned once, at extraction
   time**, before the document reaches the existing ingestion validator.
   It becomes a required field on the ingestion request model the validator
   already checks — extending, not replacing, `emg-knowledge-pipeline`'s
   existing conformance checks. A caller may *declare* an expected language
   as a hint, but the server-detected value is authoritative, exactly
   mirroring how `owner`/`provenance_reference`/`trust_score` are already
   handled (Decision point 4 below).
2. **Language-processing failure is a new, explicit failure mode**, distinct
   from ontology-conformance failure. A document in a language the pipeline
   cannot process fails closed with its own typed error and a provenance
   record capturing what was attempted and why it failed — it does not
   silently proceed as if the content were absent, and it does not silently
   fall back to processing only the recognizable-language portion of a
   mixed-language document without flagging the untouched portion.
3. **Translation is opportunistic, not mandatory, at ingestion time.**
   Ingestion preserves whatever `translations` accompany a source document
   (e.g., a bilingual document already contains both versions) and MAY
   invoke a translation step to populate a `translations` entry for the
   platform's other operating language, but ingestion is not blocked or
   failed if no translation is produced — an entity with only its
   `source_language` content and no `translations` yet is a valid, complete
   ingestion outcome. This keeps ingestion's completion contract simple
   (matching the existing pipeline's "no partial graph" transactional
   guarantee) while leaving translation coverage as an improvable-over-time
   property, not a hard gate.
4. **`source_language` is server-assigned, never caller-trusted**, joining
   `owner`, `provenance_reference`, and `trust_score` in the existing
   server-assigned trust boundary (`emg-knowledge-pipeline`, Sprint 10).

## Alternatives Considered

- **Require translation at ingestion time (mandatory, blocking).** Rejected:
  makes ingestion latency and success depend on translation-service
  availability and quality, which is an operational concern unrelated to
  whether the source content itself is valid and ingestible; also
  contradicts the existing pipeline's "no partial graph" atomicity guarantee
  if translation is treated as part of the same transaction.
- **Trust caller-declared `source_language`.** Rejected: identical rationale
  to why `owner`/`provenance_reference`/`trust_score` are already
  server-assigned — a caller-supplied language label could be used to evade
  language-specific policy conditions (e.g., a future clearance rule keyed
  on `source_language`, per `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §9)
  or to mislabel content to bypass an OCR/extraction pipeline that would
  otherwise have flagged it.
- **Silently skip unprocessable-language content rather than fail closed.**
  Rejected: directly contradicts ADR-018 §2's explicit requirement; silent
  skipping produces an ingestion outcome indistinguishable from "there was
  nothing there," which defeats the provenance guarantee the rest of the
  platform depends on.
- **Treat mixed-language documents as a single dominant language.** Rejected:
  ADR-018 §1 explicitly requires the memory model to preserve "multilingual
  relationships... without collapsing provenance" — collapsing a
  mixed-language document to its majority language at ingestion is exactly
  the kind of collapsing that requirement forbids.

## Consequences

**Positive:** ingestion completion has one simple, testable contract
(valid document + assigned `source_language` + optional `translations`);
language-processing failures are visible and provenanced rather than silent;
the server-assigned trust boundary for language fields closes an otherwise
open mislabeling attack surface.

**Negative / cost:** entities may persist for some time with no
`translations` entry, meaning cross-language search/retrieval coverage is
gradual rather than complete-at-ingestion — this is an explicit, accepted
trade-off (Decision point 3), not an oversight; a future translation
backfill job is a reasonable follow-up but is not designed by this ADR.

## Security Implications

Fail-closed behavior on unprocessable-language content (Decision point 2)
prevents a document from being silently half-ingested in a way that could
misrepresent completeness to a downstream reader. Server-assigned
`source_language` (Decision point 4) closes the mislabeling surface described
above. OCR and extraction pipelines processing Arabic content introduce the
same injection-surface concerns as any text-extraction pipeline (control/bidi
character handling) already enforced platform-wide by existing identifier/
label validators (ADR-018 §5) — this ADR extends that existing discipline to
extracted document content, not just identifiers.

## Implementation Roadmap

Consistent with `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §10's
sequencing and the existing library-first pattern:

1. Extend `emg-knowledge-pipeline`'s ingestion request model with
   `source_language` (required, server-assigned) and `translations`
   (optional) fields, plus the new language-processing-failure error type —
   library-first, no service, no OCR yet (mirrors how FEAT-05-2 itself
   shipped storage-independent before any live service existed).
2. Add the `LanguageCode`/`Locale` shared type to `emg-common-types`
   (`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §1) as the typed vehicle for
   the fields in step 1, rather than using bare strings.
3. Document intake + language detection + OCR as a new capability, tested
   independently of the graph-write path (extraction correctness is
   separable from graph transaction correctness).
4. Wire intake + detection into the existing validator/transaction path
   (step 1's fields), preserving the existing "no partial graph" guarantee.
5. `services/knowledge-graph` service shell exposing ingestion via the
   Enterprise API Gateway.
6. Translation-backfill job for entities with no `translations` entry —
   explicitly deferred past this roadmap as a future, separately-reviewed
   capability.

Each step is sized as its own reviewed sprint.
