# Engineering Note — FEAT-05-3 Trust Engine ↔ Knowledge Ingestion Pipeline Seam

**Status:** documentation only. No production code changes. This note records the
existing integration seam between the Sprint 11 trust-scoring engine
(`libs/python/emg-trust-scoring`, FEAT-05-3) and the Sprint 10 knowledge
ingestion pipeline (`libs/python/emg-knowledge-pipeline`, FEAT-05-2), why Sprint
11 intentionally leaves that seam **unchanged**, and exactly what future work
integration would require **if** the architecture later decides to wire them
together. It does **not** decide whether to integrate — that is a product /
architecture decision outside this sprint's approved scope.

## 1. The existing seam

The Sprint 10 pipeline already assigns a trust score at ingestion time through a
single, explicitly labelled seam:

- `emg_knowledge_pipeline/context.py`
  - `_DEFAULT_TRUST_BY_SOURCE` — an interim, conservative per-source-type default
    (`system 0.7`, `api 0.6`, `document 0.5`, `human 0.5`, `ai 0.3`), commented:
    *"FEAT-05-3 will replace this with a real composite score … documented as a
    placeholder, not a scoring engine."*
  - `IngestionContext.assigned_trust_score()` — returns an optional server-set
    `trust_score` override if present, else the source-type default. Its docstring
    reads *"interim; FEAT-05-3 supersedes."*
- `emg_knowledge_pipeline/pipeline.py:134` and `validation.py:116` — the only two
  call sites; both set `entity.trust_score = context.assigned_trust_score()`.

So the pipeline funnels **all** trust assignment through one method. That method
is the seam FEAT-05-3 was written to eventually replace.

On the trust-scoring side, the matching seam already exists and is deliberately
storage- and pipeline-independent:

- `emg_trust_scoring/from_ontology.py::signals_from_entity(entity, *, as_of,
  source_type, …observations)` derives a `TrustSignals` envelope from a
  constructed `emg-ontology` `Entity` (provenance links, ownership, identifier,
  effective window, lifecycle) plus caller-supplied observations (evidence
  counts, validation outcomes, relationship conflicts, ingestion quality,
  duplicate likelihood). It does **not** read the entity's own `trust_score`.
- `emg_trust_scoring/evaluate.py::evaluate(signals, policy)` then returns the
  quality-gate report and the computed composite score.

The two halves are designed to meet at `signals_from_entity(...) → evaluate(...)`.

## 2. Why Sprint 11 leaves the seam unchanged

1. **Scope.** FEAT-05-3's approved scope is the deterministic trust-scoring and
   advanced-validation **library**. Wiring is not in the approved fix set and
   would expand scope.
2. **Dependency direction.** Trust-scoring must not depend on the ingestion
   pipeline; the pipeline may later depend on trust-scoring, not vice versa.
   Keeping the seam un-wired preserves that clean acyclic direction and lets the
   library be reused by any future consumer (not only the pipeline).
3. **It would change merged FEAT-05-2 behaviour and tests.** Replacing
   `assigned_trust_score()` changes the value stamped onto every ingested entity.
   Existing pipeline tests pin the interim defaults directly —
   `test_ingestion.py:46` (`== 0.7`), `test_ingestion.py:66-67`
   (`system→0.7, ai→0.3, document→0.5`), and `test_security.py:60`
   (`== context.assigned_trust_score()`). Those are the placeholder tests the
   seam was written to supersede, but rewriting merged, released Sprint 10 code
   and tests is a separate, deliberate change that belongs to its own scoped unit
   of work, not a Sprint 11 side effect.
4. **Missing runtime inputs.** A faithful composite score needs the
   *observations that live outside the entity* (evidence counts, validation
   outcomes, relationship conflicts, ingestion redactions/violations, duplicate
   likelihood). The current pipeline does not yet collect these; supplying zeros
   would produce a misleadingly low score, so integration should wait until those
   inputs exist.

## 3. What integration would require (if later approved)

This is a forward-looking checklist only — none of it is implemented here.

1. **Add the dependency** `emg-knowledge-pipeline → emg-trust-scoring` (one
   direction; the reverse remains forbidden).
2. **Collect observation inputs** during ingestion: evidence expected/present/
   conflicts, validation error/warning counts, relationship total/conflicts,
   ingestion redactions/bound-violations, and a duplicate-likelihood estimate.
   These feed the `signals_from_entity(...)` keyword arguments.
3. **Replace the seam.** In `IngestionContext.assigned_trust_score()` (or at the
   two call sites), build `TrustSignals` via `signals_from_entity(entity, as_of=
   ingest_time, source_type=…, **observations)` and call `evaluate(signals,
   policy)`, then stamp `entity.trust_score = evaluation.trust.score`.
4. **Decide the policy source.** Pick and pin the `ScoringPolicy` (default or a
   governed, versioned policy), and persist `policy_version` alongside the score
   so a stored score is interpretable against the policy that produced it.
5. **Retire the interim default.** Remove `_DEFAULT_TRUST_BY_SOURCE` and the
   optional caller `trust_score` override, closing the last caller-controlled
   trust path in the running system (the library already forbids caller-set
   trust; only the pipeline still allows an override).
6. **Update the pipeline tests** that pin the interim defaults to assert against
   the computed composite (or golden-pinned expected scores).
7. **Gate enforcement (optional, policy decision).** Decide whether a failing
   `QualityGateReport` (error-severity) should block ingestion or only annotate
   the entity; today the gates are advisory.
8. **Regression.** Re-run the full suite plus the Module 6 audit-hash and
   Sprint 9 ontology-descriptor golden regressions.

## 4. Summary

The seam is present, single-point, and explicitly labelled on both sides.
Sprint 11 completes the reusable scoring/validation engine and the
`signals_from_entity` adapter, but does **not** cross the seam — that would
modify released FEAT-05-2 code and tests and needs runtime observation inputs the
pipeline does not yet collect. The checklist in §3 is the complete, bounded work
required if a future architecture decision chooses to integrate.
