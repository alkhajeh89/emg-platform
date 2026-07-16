"""emg_audit_client — the audit event contract (Module 6 — Audit, Provenance
& Digital Evidence Platform, FEAT-04-1). Added Sprint 6.

Defines the *shape* every service programs against — `AuditEvent`,
`SubmittedAuditEvent`, `AuditSink`, `AuditEventStore`, `AuditQuery` — with no
concrete implementation. The default concrete implementation (append-only
stores, hashing, sequencing, integrity verification) is the separate
`emg-audit-pipeline` package; `services/audit` is the thin live service over
it. See `docs/engineering/sprint-6-design.md`.

Reuses `emg_common_types.Classification` / `CorrelationId`; introduces no new
cross-cutting primitives. Kept distinct from `emg_telemetry` observability
logs per ADR-015 §Decision.
"""

from .event import (
    MAX_METADATA_ENTRIES,
    MAX_METADATA_VALUE_LEN,
    ActorType,
    AuditEvent,
    AuditOutcome,
    SubmittedAuditEvent,
)
from .protocols import AuditEventStore, AuditSink, IntegrityResult
from .query import AuditQuery

__version__ = "0.1.0"

__all__ = [
    "AuditEvent",
    "SubmittedAuditEvent",
    "AuditOutcome",
    "ActorType",
    "AuditQuery",
    "AuditSink",
    "AuditEventStore",
    "IntegrityResult",
    "MAX_METADATA_ENTRIES",
    "MAX_METADATA_VALUE_LEN",
    "__version__",
]
