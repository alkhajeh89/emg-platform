# Sprint 11 Design — Knowledge Validation & Trust Scoring (FEAT-05-3)

Reference: Engineering Backlog v1.0 §3 (FEAT-05-3 — "Knowledge Validation &
Trust Scoring: Quality gates and composite confidence scoring"), §6 row 9, §9
(8 story points); Architecture Baseline ("grounded, cited, **explainable by
construction**"; Module 7 §26 knowledge-quality testing, §34 explainability).
Builds on FEAT-05-1 (`emg-ontology`) and re-uses its envelope; does not depend on
FEAT-05-2.

## Scope

Sprint 11 implements **FEAT-05-3 only**, delivered **library-first** as
`libs/python/emg-trust-scoring`: a **deterministic, storage-independent** engine
that (a) computes an immutable, explainable **composite confidence (trust)
score** from observable signals and (b) runs a suite of typed **quality-gate**
validation checks.

Out of scope (deferred / excluded): the **Semantic Layer** and **Neo4j**
(FEAT-05-4), **lifecycle management** (FEAT-05-5), and all retrieval, graph
querying, embeddings, AI, and UI. No persistence, no service, no storage
coupling. `services/knowledge-graph` remains scaffolded.

## Architecture

Library-first and pure. The engine depends only on `emg-common-types`,
`emg-errors`, and `emg-ontology` (for the `Entity` envelope in the optional
`signals_from_entity` adapter) — **not** on `emg-knowledge-pipeline`, so the
dependency direction stays clean (the pipeline may later depend on trust scoring,
not vice versa). Everything is a frozen pydantic model or a pure function.

**Trust is computed, never supplied.** The input `TrustSignals` model has no
trust field; a caller provides observable facts and the engine derives the
score. This is the real replacement for the FEAT-05-2 interim source-type
default. It is **not wired into the pipeline this sprint** — doing so would
change merged FEAT-05-2 behaviour and tests — so wiring (via
`signals_from_entity` + `evaluate`) is a follow-up for the future live ingestion
service.

## Trust scoring architecture

```
TrustSignals (observable, bounded, no trust field)      ScoringPolicy (weights, half-life,
   source_type, provenance_*, evidence_*, validation_*,     thresholds, precision, version)
   owner_*, effective_*, relationship_*, ingestion_*,                     │
   duplicate_likelihood, lifecycle_status, as_of                          │
        │                                                                 │
        ▼                                                                 ▼
   compute_factor_scores()  ── 8 pure factor fns, each clamped to [0,1] ──┐
   ┌─ source_confidence      (per-source-type map)                        │
   ├─ provenance_quality     (present + audit + correlation + link count) │
   ├─ evidence_completeness  (present/expected, penalized by conflicts)   │
   ├─ validation_status      (conformant - errors/warnings)               │  weighted
   ├─ ownership_confidence    (absent / present / registered)             │  average
   ├─ temporal_freshness     (0.5 ** age/half_life; 0 if expired/retired) │  (Σ weightᵢ·rawᵢ)
   ├─ relationship_consistency (1 - conflicts/total)                      │     │
   └─ ingestion_quality      (1 - redactions/violations)                  │     ▼
        │                                                                 │  round → clamp
        ▼                                                                 │     │
   run_quality_gates() ── 9 typed checks (info/warning/error) ────────────┘     ▼
        │  evidence, provenance, ownership, identifier, ontology,        TrustScoreResult
        │  relationship, duplicate, temporal, lifecycle                  (score, accepted,
        ▼                                                                 breakdown[], explanation,
   QualityGateReport (passed = no error-severity failures)               policy_version)  ── frozen
        └───────────────────────────┬───────────────────────────────────────────┘
                                    ▼
                          evaluate() -> TrustEvaluation (quality_gates + trust)   ── frozen
```

## Key decisions

- **Determinism / reproducibility.** No wall-clock (temporal decay uses
  `signals.as_of`), no randomness, no I/O. Factor scores and the composite are
  rounded to `policy.precision` (default 6) so results are byte-identical across
  runs and platforms. A **golden test** pins the composite for canonical
  high-/low-trust signals (`0.971667` / `0.216667`).
- **No single-signal domination.** Each factor is clamped to `[0, 1]` and the
  composite is a weighted average, so an inflated signal caps at its factor's
  clamp and contributes at most its weight. Signals are bounded at construction.
- **Explainability.** `TrustScoreResult.breakdown` gives every factor's raw
  score, weight, and contribution, plus a human-readable `explanation`.
- **Versioned, normalized policy.** `ScoringPolicy` validates that all eight
  factors have non-negative weights and normalizes them to sum 1; `policy_version`
  is pinned.
- **Quality gates return typed results.** Each `QualityCheck` carries a
  severity; only `error`-severity failures fail the `QualityGateReport`
  (`warning` is advisory). The report also informs the validation-status factor.
- **Immutability.** All result/report/evaluation models are frozen.
- **Input vs. output trust boundary.** Only `TrustSignals` and `ScoringPolicy`
  are caller-supplied inputs. `TrustScoreResult`, `QualityGateReport`,
  `FactorContribution`, and `TrustEvaluation` are **engine outputs** and must be
  obtained only from `evaluate_trust` / `run_quality_gates` / `evaluate`. They
  are frozen DTOs and therefore *can* be hand-constructed, but a hand-built
  result bypasses the deterministic calculation and carries no guarantee that its
  `score`/`passed`/counts were computed from signals; consumers must never accept
  a caller-constructed result as a computed trust score. Non-finite policy inputs
  (NaN/±Infinity weights or `half_life_days`) are rejected at `ScoringPolicy`
  construction (`math.isfinite`), so no constructible policy can produce a NaN
  score.

## Security

- Trust cannot be spoofed (no trust field on the input; extra fields rejected).
- Deterministic, reproducible, immutable outputs.
- Bounded signals + clamped factors resist manipulated evidence (no domination).
- The engine scores provided signals; it does not attest them — signal
  trustworthiness is the ingestion pipeline's server-side responsibility
  (FEAT-05-2). Documented in `security-limitations.md`.

## Testing

See `testing-strategy.md` (Sprint 11 section): per-factor calculations,
clamping, composite/determinism/immutability, the golden score pins, temporal
decay + expiry + lifecycle, edge/malformed/conflicting-evidence cases, duplicate
scenarios, every quality gate + report aggregation, no-caller-trust +
manipulation resistance, policy validation/normalization, and the ontology
adapter — plus the Module 6 golden audit-hash and Sprint 9 golden ontology
descriptor regressions unchanged and the full Sprint 1–10 suite.
