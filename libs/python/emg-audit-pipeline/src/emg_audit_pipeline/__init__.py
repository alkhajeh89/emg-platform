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

from .custody_hashing import (
    canonical_custody_payload,
    compute_custody_hash,
    recompute_custody_event_hash,
)
from .custody_store import (
    InMemoryCustodyEventStore,
    PostgresCustodyEventStore,
    validate_and_sanitize_custody,
    verify_custody_chain,
)
from .hashing import (
    GENESIS_PREV_HASH,
    canonical_payload,
    compute_hash,
    recompute_event_hash,
)
from .integrity import IntegrityReport, verify_chain
from .stores import InMemoryAuditEventStore, PostgresAuditEventStore
from .validation import (
    is_sensitive_key,
    redact_text,
    validate_and_sanitize,
    validate_and_sanitize_provenance,
)

__version__ = "0.2.0"

__all__ = [
    "InMemoryAuditEventStore",
    "PostgresAuditEventStore",
    "InMemoryCustodyEventStore",
    "PostgresCustodyEventStore",
    "IntegrityReport",
    "verify_chain",
    "verify_custody_chain",
    "compute_hash",
    "canonical_payload",
    "recompute_event_hash",
    "compute_custody_hash",
    "canonical_custody_payload",
    "recompute_custody_event_hash",
    "GENESIS_PREV_HASH",
    "validate_and_sanitize",
    "validate_and_sanitize_provenance",
    "validate_and_sanitize_custody",
    "is_sensitive_key",
    "redact_text",
    "__version__",
]
