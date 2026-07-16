"""emg_audit_pipeline — the audit pipeline core (Module 6 — Audit, Provenance
& Digital Evidence Platform, FEAT-04-1). Added Sprint 6.

The concrete implementation of the `emg-audit-client` contract: canonical
event hashing, a centralized (single-writer per store) hash chain and
sequence assignment, append-only stores (`InMemoryAuditEventStore` for tests,
`PostgresAuditEventStore` for tier-1), integrity verification that detects
out-of-band mutation, event-id idempotency, and pre-persistence
metadata/secret validation.

This package holds all audit logic; `services/audit` is a thin live service
over it. See `docs/engineering/sprint-6-design.md`.
"""

from .hashing import (
    GENESIS_PREV_HASH,
    canonical_payload,
    compute_hash,
    recompute_event_hash,
)
from .integrity import IntegrityReport, verify_chain
from .stores import InMemoryAuditEventStore, PostgresAuditEventStore
from .validation import is_sensitive_key, redact_text, validate_and_sanitize

__version__ = "0.1.0"

__all__ = [
    "InMemoryAuditEventStore",
    "PostgresAuditEventStore",
    "IntegrityReport",
    "verify_chain",
    "compute_hash",
    "canonical_payload",
    "recompute_event_hash",
    "GENESIS_PREV_HASH",
    "validate_and_sanitize",
    "is_sensitive_key",
    "redact_text",
    "__version__",
]
