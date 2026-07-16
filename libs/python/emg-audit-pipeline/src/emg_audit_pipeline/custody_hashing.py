"""Canonical hashing for the digital-evidence custody chain (FEAT-04-3).

Mirrors `emg_audit_pipeline.hashing` for the custody ledger: a deterministic
canonical serialization of each custody event's immutable fields plus the
previous event's hash, so any alteration or reordering breaks the chain from
that point forward. Uses the same SHA-256 hash-chain approach as FEAT-04-1 —
no PKI / asymmetric signatures (FEAT-04-3, no new ADR).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from emg_audit_client import CustodyEvent, SubmittedCustodyEvent

from .hashing import GENESIS_PREV_HASH, _isoformat_utc

__all__ = [
    "GENESIS_PREV_HASH",
    "canonical_custody_payload",
    "compute_custody_hash",
    "recompute_custody_event_hash",
]


def canonical_custody_payload(
    *,
    custody_event_id: str,
    source_principal: str,
    chain_sequence: int,
    custody_sequence: int,
    transfer_timestamp: datetime,
    ingest_time: datetime,
    submitted: SubmittedCustodyEvent,
    prev_hash: str,
) -> str:
    """Return the deterministic canonical string a custody `event_hash` is
    computed over: every immutable field plus `prev_hash`. Server-assigned
    ordering/identity fields (`source_principal`, `chain_sequence`,
    `custody_sequence`) are included so tampering with them is detected."""
    payload = {
        "custody_event_id": custody_event_id,
        "source_principal": source_principal,
        "chain_sequence": chain_sequence,
        "custody_sequence": custody_sequence,
        "transfer_timestamp": _isoformat_utc(transfer_timestamp),
        "ingest_time": _isoformat_utc(ingest_time),
        "evidence_id": submitted.evidence_id,
        "custody_action": submitted.custody_action,
        "custodian": submitted.custodian,
        "prior_custodian": submitted.prior_custodian,
        "transfer_reason": submitted.transfer_reason,
        "classification": submitted.classification.value,
        "correlation_id": submitted.correlation_id,
        "metadata": {key: submitted.metadata[key] for key in sorted(submitted.metadata)},
        "prev_hash": prev_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_custody_hash(
    *,
    custody_event_id: str,
    source_principal: str,
    chain_sequence: int,
    custody_sequence: int,
    transfer_timestamp: datetime,
    ingest_time: datetime,
    submitted: SubmittedCustodyEvent,
    prev_hash: str,
) -> str:
    """Compute the SHA-256 `event_hash` for one custody event."""
    payload = canonical_custody_payload(
        custody_event_id=custody_event_id,
        source_principal=source_principal,
        chain_sequence=chain_sequence,
        custody_sequence=custody_sequence,
        transfer_timestamp=transfer_timestamp,
        ingest_time=ingest_time,
        submitted=submitted,
        prev_hash=prev_hash,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def recompute_custody_event_hash(event: CustodyEvent) -> str:
    """Recompute a persisted custody event's hash from its stored fields, for
    integrity verification. Any altered field yields a different hash than the
    stored `event_hash`."""
    submitted = SubmittedCustodyEvent(
        custody_event_id=event.custody_event_id,
        evidence_id=event.evidence_id,
        custody_action=event.custody_action,
        custodian=event.custodian,
        prior_custodian=event.prior_custodian,
        transfer_reason=event.transfer_reason,
        classification=event.classification,
        correlation_id=event.correlation_id,
        metadata=event.metadata,
    )
    return compute_custody_hash(
        custody_event_id=event.custody_event_id,
        source_principal=event.source_principal,
        chain_sequence=event.chain_sequence,
        custody_sequence=event.custody_sequence,
        transfer_timestamp=event.transfer_timestamp,
        ingest_time=event.ingest_time,
        submitted=submitted,
        prev_hash=event.prev_hash,
    )
