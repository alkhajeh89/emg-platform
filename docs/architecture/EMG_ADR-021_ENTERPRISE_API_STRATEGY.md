# ADR-021 — Enterprise API Strategy

**Status:** Proposed
**Date:** 2026-07-25
**Deciders:** Product / Architecture (EMG Platform)
**Supersedes:** none (additive — extends, does not replace, the existing API
Architecture reference)
**Related:** ADR-018 (Bilingual Enterprise Architecture), ADR-014 (Enterprise
Presentation Architecture, BFF pattern), `docs/architecture/reference/api/EMG-Enterprise-API-Architecture.md`
(§16 API Gateway Design, §17 Versioning, §18–22 Request/Response/Error/
Pagination/Filtering standards), `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §6

---

## Context

A 638-line "Official API Contract · Version 1.0" already exists
(`docs/architecture/reference/api/EMG-Enterprise-API-Architecture.md`),
specifying REST standards, GraphQL, event-driven APIs, WebSockets, the API
Gateway design, versioning, request/response/error standards, pagination,
filtering, and per-module API groups tagged with an `(M##)` identifier
scheme that does not match `ARCHITECTURE_STATUS.md`'s Module 1–10 scheme
(`IMPLEMENTATION_GAP_ANALYSIS.md` Gap 4a). That document is thorough and is
treated here as authoritative for everything it already decides — REST/
GraphQL/error/pagination standards are **not** revisited by this ADR. It
predates ADR-018 and contains no locale/language-negotiation concept at all.
This ADR makes the one binding decision the existing reference does not yet
make.

## Problem

1. **No locale negotiation mechanism exists** anywhere in the existing API
   contract. Every API group it defines (Search, Graph, Decision, AI,
   Administration, Audit) would otherwise each need to invent one
   independently, which is exactly the retrofit pattern ADR-018 exists to
   prevent.
2. **Response-language is not the same concept as UI locale**, but the
   existing contract has no field for either. Left undecided, an
   implementation could plausibly conflate a UI-rendering concern (RTL/LTR,
   date/number formatting) with a content concern (what language the actual
   payload text is in), producing inconsistent behavior across API groups.
3. **Existing error/response envelope has no classification hook for
   language.** The existing Response Standards (§19) already mandate a
   `classification` field on every representation; no equivalent exists for
   language, so a client cannot currently tell what language a response
   payload is in without out-of-band knowledge.
4. **Numbering ambiguity.** The existing contract's `(M##)` tags and
   `ARCHITECTURE_STATUS.md`'s Module 1–10 do not agree (Gap 4a) — this ADR
   must not add a third, incompatible scheme on top.

## Decision

1. **A single, gateway-resolved `locale` and `response_language` pair is
   added to the existing request/response envelope**, additive to the
   existing Response Standards (§19) `classification` field pattern:
   - Request: an `Accept-Language`-style header (or explicit
     `X-Response-Language` override), resolved once at the Enterprise API
     Gateway (`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §6), never
     re-resolved independently by each downstream API group.
   - Response: every representation gains a `content_language` field
     alongside the existing `classification` field in the response `meta`
     (§19), stating what language the actual payload content is in — which
     may differ from the requester's UI `locale` (e.g., a UI in English
     displaying an untranslated Arabic-original entity).
2. **This is additive to the existing contract, not a version bump.** Per
   the existing Versioning Strategy (§17), "minor/additive changes do not
   bump the major version" — adding `content_language`/`locale` fields to
   the existing envelope is exactly this kind of additive change and does
   not require a new API major version.
3. **This ADR does not introduce a fourth numbering scheme.** Where this
   document or `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` needs to refer
   to an existing API group, it cites the existing reference document's own
   section number and `(M##)` tag verbatim (e.g., "Graph APIs, reference
   corpus §24, M04") rather than inventing a new label. Resolving which
   numbering scheme is platform-authoritative (Gap 4a) remains an open
   decision for whoever owns `ARCHITECTURE_STATUS.md` and the reference
   corpus — this ADR does not decide it, only avoids making it worse.
4. **Error responses (§20) gain no new field** — the existing RFC 7807
   `application/problem+json` shape already forbids leaking internal detail;
   a translated error message is a future, separately-designed capability
   (see Implementation Roadmap), not decided here.

## Alternatives Considered

- **Per-API-group locale handling** (each of Search/Graph/Decision/AI/
  Administration APIs independently decides how to handle language).
  Rejected: this is precisely the retrofit ADR-018 §Consequences warns
  against ("avoids costly schema/API rewrites after MVP"); a single
  gateway-resolved mechanism is strictly cheaper to build once, correctly.
- **Overload the existing `classification` field's pattern to also carry
  language** (e.g., a combined `classification/language` compound value).
  Rejected: classification and language are orthogonal dimensions (a SECRET
  document can be in Arabic, English, or both) — conflating them into one
  field would make either dimension unfilterable independently, and would
  contradict the existing Filtering standard's (§22) requirement that
  filters be independently combinable.
- **New major API version to introduce locale support.** Rejected per
  Decision point 2's reasoning — the existing Versioning Strategy already
  classifies this as additive.
- **Full response-body translation at the gateway** (gateway translates
  payload content on the fly to match requested `response_language`).
  Rejected: the gateway's existing mandate is explicitly "no business logic
  in the gateway ... it enforces, it does not decide" (§16); on-the-fly
  translation is content transformation, not enforcement, and belongs (if
  ever built) in the AI Orchestration or Knowledge Ingestion layers
  (ADR-019, ADR-020), not the gateway.

## Consequences

**Positive:** every API group gains bilingual-aware responses through one
gateway-level change rather than N independent changes; the existing
contract's versioning and envelope standards are preserved and extended
rather than replaced, so existing API consumers (identity, audit — the two
live services) are unaffected.

**Negative / cost:** every response producer (eventually: Graph, AI,
Administration, Knowledge Ingestion APIs) must populate `content_language`
correctly once built — this is a new, explicit acceptance criterion for
every future API group's implementation, not an automatic property of the
gateway change alone.

## Security Implications

Locale/language header values must be strictly validated against BCP 47
language tags (allow-listed), consistent with the existing Request Standards
(§18) "reject unknown fields" discipline — an unvalidated locale string is a
header-injection surface. `content_language` must never be used to infer or
imply the existence of restricted content (an entity's language must not
leak through a side channel to a requester who is not authorized to see the
entity itself) — this extends the existing "unauthorized existence is not
revealed" principle (§19) to the new field.

## Implementation Roadmap

Consistent with `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §10:

1. Add `LanguageCode`/`Locale` to `emg-common-types`
   (`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §1) as the typed vehicle for
   both the request-side `locale`/`response_language` and the response-side
   `content_language`.
2. Extend `emg-api-contracts` with the additive envelope fields (Decision
   point 1) — library-first, no gateway process yet, mirroring how every
   other module shipped contracts before its live service.
3. Implement gateway-level locale resolution once the Enterprise API Gateway
   itself is built (`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §6,
   Recommended Implementation Sequence step 4) — this ADR's contract change
   can land before the gateway process exists, but takes effect only once it
   does.
4. Each API group populates `content_language` as it is implemented (Graph
   APIs alongside `services/knowledge-graph`, AI APIs alongside
   `services/ai-orchestration`, etc.) — not retrofitted onto the two
   already-live services (`identity`, `audit`) unless a genuine bilingual
   requirement emerges for them specifically.
5. Translated error messages and full response-body translation — explicitly
   deferred, flagged as future work requiring its own ADR given the content-
   transformation and classification implications noted in Alternatives
   Considered.

Each step is sized as its own reviewed sprint; this ADR authorizes no
implementation on its own.
