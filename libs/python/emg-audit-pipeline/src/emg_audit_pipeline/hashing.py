"""Canonical audit-event hashing and hash-chain computation (FEAT-04-1).

The hash chain is what makes out-of-band mutation *detectable*: each event's
`event_hash` is computed over a canonical serialization of its immutable
fields together with the previous event's hash, so altering any stored field
(or reordering events) breaks the chain from that point forward.

`GENESIS_PREV_HASH` is the `prev_hash` of the very first event in a store.

Canonicalization is deterministic: a fixed field order, UTC ISO-8601
timestamps, and sorted metadata keys, JSON-serialized with sorted keys and no
insignificant whitespace. The same event always produces the same hash across
processes and store backends.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from emg_audit_client import (
    EVENT_SCHEMA_VERSION_V1,
    EVENT_SCHEMA_VERSION_V2,
    AuditEvent,
    ProvenanceRecord,
    SubmittedAuditEvent,
)

GENESIS_PREV_HASH = "0" * 64


def _isoformat_utc(value: datetime) -> str:
    """Serialize a datetime as a canonical UTC ISO-8601 string. Naive
    datetimes are treated as UTC; aware datetimes are converted to UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _isoformat_utc_opt(value: datetime | None) -> str | None:
    return None if value is None else _isoformat_utc(value)


def _canonical_provenance(provenance: ProvenanceRecord) -> dict[str, object]:
    """Deterministic, JSON-serializable representation of a ProvenanceRecord.

    Ordered lists (`transformation_history`, `parent_event_refs`) keep their
    order — the order is meaningful lineage and is part of the hash. Dict keys
    are sorted by the enclosing `json.dumps(sort_keys=True)`."""
    return {
        "schema_version": provenance.schema_version,
        "source_system": provenance.source_system,
        "source_component": provenance.source_component,
        "originating_actor": provenance.originating_actor,
        "originating_principal": provenance.originating_principal,
        "correlation_id": provenance.correlation_id,
        "event_time": _isoformat_utc(provenance.event_time),
        "ingest_time": _isoformat_utc(provenance.ingest_time),
        "classification": provenance.classification.value,
        "transformation_history": [
            {
                "step": step.step,
                "timestamp": _isoformat_utc_opt(step.timestamp),
                "actor": step.actor,
                "detail": step.detail,
            }
            for step in provenance.transformation_history
        ],
        "parent_event_refs": [
            {
                "source_principal": ref.source_principal,
                "event_id": ref.event_id,
                "event_hash": ref.event_hash,
            }
            for ref in provenance.parent_event_refs
        ],
        "evidence_origin": provenance.evidence_origin,
        "collection_method": provenance.collection_method,
    }


def canonical_payload(
    *,
    event_id: str,
    source_principal: str,
    sequence_number: int,
    timestamp: datetime,
    ingest_time: datetime,
    submitted: SubmittedAuditEvent,
    prev_hash: str,
    schema_version: int = EVENT_SCHEMA_VERSION_V1,
) -> str:
    """Return the deterministic canonical string that `event_hash` is computed
    over. Includes every immutable field plus `prev_hash` (the chain link).
    `event_hash` itself is excluded (it is the output). `source_principal` (the
    server-assigned authenticated producer identity) is included so tampering
    with it is detected by integrity verification.

    **Version-aware (FEAT-04-2).** For a schema-version-1 event the payload is
    *byte-for-byte identical* to the Sprint 6 canonicalization — the
    `schema_version` and `provenance` keys are simply absent — so every existing
    version-1 record recomputes to its stored hash unchanged. For a
    schema-version-2 event the payload additionally carries `schema_version`
    and the canonical `provenance` record, so provenance is tamper-evident."""
    payload: dict[str, object] = {
        "event_id": event_id,
        "source_principal": source_principal,
        "sequence_number": sequence_number,
        "timestamp": _isoformat_utc(timestamp),
        "ingest_time": _isoformat_utc(ingest_time),
        "actor": submitted.actor,
        "actor_type": submitted.actor_type,
        "module": submitted.module,
        "action": submitted.action,
        "outcome": submitted.outcome,
        "correlation_id": submitted.correlation_id,
        "resource_type": submitted.resource_type,
        "resource_id": submitted.resource_id,
        "classification": submitted.classification.value,
        "source_system": submitted.source_system,
        "source_component": submitted.source_component,
        "reason": submitted.reason,
        "metadata": {key: submitted.metadata[key] for key in sorted(submitted.metadata)},
        "prev_hash": prev_hash,
    }
    # Version 1 stays byte-identical to Sprint 6: no new keys added. Version 2
    # adds the discriminator and the provenance record to the hashed payload.
    if schema_version >= EVENT_SCHEMA_VERSION_V2:
        payload["schema_version"] = schema_version
        payload["provenance"] = (
            None if submitted.provenance is None else _canonical_provenance(submitted.provenance)
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(
    *,
    event_id: str,
    source_principal: str,
    sequence_number: int,
    timestamp: datetime,
    ingest_time: datetime,
    submitted: SubmittedAuditEvent,
    prev_hash: str,
    schema_version: int = EVENT_SCHEMA_VERSION_V1,
) -> str:
    """Compute the SHA-256 `event_hash` for one event."""
    payload = canonical_payload(
        event_id=event_id,
        source_principal=source_principal,
        sequence_number=sequence_number,
        timestamp=timestamp,
        ingest_time=ingest_time,
        submitted=submitted,
        prev_hash=prev_hash,
        schema_version=schema_version,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def recompute_event_hash(event: AuditEvent) -> str:
    """Recompute the hash of a *persisted* event from its stored fields, for
    integrity verification. Rebuilds the producer portion from the persisted
    record, so any altered field yields a different hash than the stored
    `event_hash`. Uses the event's *stored* `schema_version`, so version-1 and
    version-2 records both recompute against the exact payload they were hashed
    with."""
    submitted = SubmittedAuditEvent(
        event_id=event.event_id,
        actor=event.actor,
        actor_type=event.actor_type,
        module=event.module,
        action=event.action,
        outcome=event.outcome,
        correlation_id=event.correlation_id,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        classification=event.classification,
        source_system=event.source_system,
        source_component=event.source_component,
        reason=event.reason,
        metadata=event.metadata,
        provenance=event.provenance,
    )
    return compute_hash(
        event_id=event.event_id,
        source_principal=event.source_principal,
        sequence_number=event.sequence_number,
        timestamp=event.timestamp,
        ingest_time=event.ingest_time,
        submitted=submitted,
        prev_hash=event.prev_hash,
        schema_version=event.schema_version,
    )
