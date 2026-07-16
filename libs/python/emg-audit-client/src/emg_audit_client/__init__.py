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

from .custody import (
    MAX_CUSTODY_VALUE_LEN,
    CustodyAction,
    CustodyEvent,
    CustodyQuery,
    SubmittedCustodyEvent,
)
from .event import (
    EVENT_SCHEMA_VERSION_V1,
    EVENT_SCHEMA_VERSION_V2,
    MAX_METADATA_ENTRIES,
    MAX_METADATA_VALUE_LEN,
    MAX_PROVENANCE_PARENT_REFS,
    MAX_PROVENANCE_TRANSFORMATIONS,
    MAX_PROVENANCE_VALUE_LEN,
    ActorType,
    AuditEvent,
    AuditOutcome,
    SubmittedAuditEvent,
)
from .protocols import AuditEventStore, AuditSink, CustodyEventStore, IntegrityResult
from .provenance import (
    PROVENANCE_SCHEMA_VERSION,
    EventRef,
    ProvenanceRecord,
    TransformationStep,
)
from .query import AuditQuery

__version__ = "0.2.0"

__all__ = [
    "AuditEvent",
    "SubmittedAuditEvent",
    "AuditOutcome",
    "ActorType",
    "AuditQuery",
    "AuditSink",
    "AuditEventStore",
    "IntegrityResult",
    "ProvenanceRecord",
    "TransformationStep",
    "EventRef",
    "PROVENANCE_SCHEMA_VERSION",
    "CustodyEvent",
    "SubmittedCustodyEvent",
    "CustodyAction",
    "CustodyQuery",
    "CustodyEventStore",
    "MAX_CUSTODY_VALUE_LEN",
    "EVENT_SCHEMA_VERSION_V1",
    "EVENT_SCHEMA_VERSION_V2",
    "MAX_METADATA_ENTRIES",
    "MAX_METADATA_VALUE_LEN",
    "MAX_PROVENANCE_TRANSFORMATIONS",
    "MAX_PROVENANCE_PARENT_REFS",
    "MAX_PROVENANCE_VALUE_LEN",
    "__version__",
]
