# emg-trust-scoring

**Knowledge Validation & Trust Scoring** for Module 7 (Enterprise Knowledge
Graph Platform) — EPIC-05, **FEAT-05-3**, added Sprint 11.

Part of the EMG™ shared-libraries workspace (Module 3, ADR-012), delivered
**library-first** and **deterministic**: it computes an immutable, explainable
composite **trust (confidence) score** from observable **signals** and runs a
suite of typed **quality-gate** validation checks. It has **no persistence, no
service, no Neo4j, no Semantic Layer, and no retrieval/search/embeddings/AI/UI**.

## What this is

- **Trust factors** (`factors.py`): the eight scoring dimensions — source
  confidence, provenance quality, evidence completeness, validation status,
  ownership confidence, temporal freshness, relationship consistency, ingestion
  quality.
- **Signals** (`signals.py`): `TrustSignals` — a frozen, bounded model of the
  observable inputs. It has **no trust field**: a caller supplies signals, the
  engine *computes* the score, so trust can never be spoofed.
- **Scoring policy** (`policy.py`): `ScoringPolicy` — per-factor weights
  (normalized to sum 1), a temporal-decay half-life, an acceptance threshold, a
  duplicate threshold, a rounding precision, and a pinned `policy_version`;
  `DEFAULT_POLICY`.
- **Scoring engine** (`engine.py`): pure, deterministic per-factor computations
  and a weighted composite, clamped to `[0, 1]` and rounded for reproducibility.
  No wall-clock (temporal decay uses an explicit `as_of`), no randomness.
- **Result** (`result.py`): `TrustScoreResult` — a frozen composite score with a
  per-factor breakdown (raw score, weight, contribution), the policy version, an
  acceptance verdict, and a human-readable explanation.
- **Quality gates** (`validation.py`): typed `QualityCheck` / `QualityGateReport`
  for evidence completeness, provenance integrity, ownership/identifier/ontology/
  relationship consistency, duplicate-confidence, temporal, and lifecycle.
- **Combined evaluation** (`evaluate.py`): `evaluate(...)` → a frozen
  `TrustEvaluation` (quality gates + trust).
- **Ontology integration** (`from_ontology.py`): `signals_from_entity(...)`
  derives envelope signals from an `emg-ontology` `Entity`; the clean point a
  future live ingestion service would use.

## Trust boundary — inputs vs. outputs

Only **`TrustSignals`** (and `ScoringPolicy`) are caller-supplied **inputs**.
Everything the engine returns — **`TrustScoreResult`**, **`QualityGateReport`**,
`FactorContribution`, and `TrustEvaluation` — is an **output produced by the
engine** (`evaluate_trust`, `run_quality_gates`, `evaluate`).

These output models are ordinary frozen data-transfer objects, so they *can* be
constructed directly in Python — but doing so **bypasses the deterministic
calculation and is not a supported path**. A hand-built `TrustScoreResult(score=
0.99, ...)` or a `QualityGateReport(passed=True, ...)` carries no guarantee that
its `score`/`passed`/counts were actually computed from signals. **Consumers must
treat these types as engine outputs only** and obtain them exclusively from the
engine functions; never accept or forward a caller-constructed result as if it
were a computed trust score. (Non-finite policy inputs — NaN/±Infinity weights or
`half_life_days` — are rejected at `ScoringPolicy` construction, so a valid policy
can never yield a NaN score.)

## What this is not

- **Not a trust value a caller can set.** Trust is always computed from signals.
- **Not persistence, a service, Neo4j, a semantic layer, retrieval, search,
  embeddings, AI, or UI.** The engine is **not** wired into the ingestion
  pipeline this sprint (that would change merged FEAT-05-2 behaviour); that is a
  follow-up for the future live ingestion service.
- **Not lifecycle management** (FEAT-05-5) — lifecycle is read as a signal only.

## Usage

```python
from datetime import datetime, timezone
from emg_trust_scoring import TrustSignals, evaluate

now = datetime(2026, 6, 1, tzinfo=timezone.utc)
signals = TrustSignals(
    as_of=now,
    source_type="system",
    provenance_present=True, provenance_has_audit_event=True,
    provenance_has_correlation=True, provenance_link_count=2,
    evidence_expected=3, evidence_present=3,
    owner_present=True, owner_registered=True,
    effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
)
result = evaluate(signals)          # deterministic, immutable
assert result.quality_gates.passed
print(result.trust.score, result.trust.accepted)
print(result.trust.explanation)     # per-factor breakdown
```
