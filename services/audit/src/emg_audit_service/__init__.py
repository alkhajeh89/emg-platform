"""EMG Audit Service (Module 6 — Audit, Provenance & Digital Evidence
Platform). Sprint 6, FEAT-04-1.

A deliberately thin live service over the shared audit libraries
(`emg-audit-client` contract, `emg-audit-pipeline` implementation). It owns
the single append-only store, authenticated ingestion, the minimal US-04
query surface, integrity verification, and health/readiness reporting. All
audit logic lives in the libraries; this package is a deployment shell. See
`docs/engineering/sprint-6-design.md`.
"""

__version__ = "0.1.0"
