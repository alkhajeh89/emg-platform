"""Internal evidence-ledger contract and deterministic integrity primitives.

The ledger is PostgreSQL-authoritative, append-only, tenant-scoped, and
independent of GraphStore and the transactional outbox.  Hash identity follows
the accepted P-02 contract addendum EL-1 through EL-4 exactly; recovery is
verification and escalation only, never mutation or repair.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Protocol, runtime_checkable

from emg_memory_graph import EvidenceRef, EvidenceSource, Metadata
from emg_platform_core import TenantId
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import EvidenceLedgerIntegrityError

GENESIS_PREV_HASH = "0" * 64
HexHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_PAYLOAD_KEYS = frozenset(
    {
        "evidence_id",
        "source",
        "locator",
        "source_principal",
        "captured_at",
        "description",
        "event_id",
        "correlation_id",
        "metadata",
    }
)
_HASHED_ENTRY_KEYS = frozenset(
    {
        "captured_at",
        "evidence_id",
        "locator",
        "payload",
        "prev_hash",
        "seq",
        "source",
        "source_principal",
        "tenant_id",
    }
)


class EvidenceIntegrityFailureKind(str, Enum):
    """Bounded reason vocabulary for explicit range-verification reports."""

    ENTRY_HASH = "entry_hash"
    PAYLOAD_MISMATCH = "payload_mismatch"
    PREV_HASH = "prev_hash"
    SEQUENCE = "sequence"


class EvidenceEntry(BaseModel):
    """One immutable stored evidence capture plus its tenant-chain identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: TenantId
    seq: int = Field(ge=1)
    prev_hash: HexHash
    entry_hash: HexHash
    evidence: EvidenceRef


class EvidenceVerificationReport(BaseModel):
    """Result of explicit inclusive-range chain verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: TenantId
    start_seq: int = Field(ge=1)
    end_seq: int = Field(ge=1)
    valid: bool
    verified_entries: int = Field(ge=0)
    first_failing_seq: int | None = Field(default=None, ge=1)
    failure_kind: EvidenceIntegrityFailureKind | None = None

    @model_validator(mode="after")
    def _validate_report(self) -> EvidenceVerificationReport:
        if self.end_seq < self.start_seq:
            raise ValueError("end_seq must be greater than or equal to start_seq")
        if self.valid != (self.first_failing_seq is None and self.failure_kind is None):
            raise ValueError("valid report state does not match failure fields")
        if (self.first_failing_seq is None) != (self.failure_kind is None):
            raise ValueError("failure sequence and kind must be set together")
        return self


@runtime_checkable
class EvidenceLedgerRepository(Protocol):
    """Internal tenant-scoped, append-only evidence-ledger capability."""

    def append(self, tenant: TenantId, evidence: EvidenceRef) -> EvidenceEntry:
        """Atomically append one capture to ``tenant``'s independent chain."""
        ...

    def get(self, tenant: TenantId, seq: int) -> EvidenceEntry | None:
        """Return one verified entry, or ``None`` when it does not exist."""
        ...

    def list_range(
        self, tenant: TenantId, *, start_seq: int, end_seq: int
    ) -> tuple[EvidenceEntry, ...]:
        """Return verified entries in the inclusive range, ordered by ``seq``."""
        ...

    def verify_range(
        self, tenant: TenantId, *, start_seq: int, end_seq: int
    ) -> EvidenceVerificationReport:
        """Explicitly verify hashes, ordering, and links in an inclusive range."""
        ...


def canonical_evidence_payload(evidence: EvidenceRef) -> dict[str, object]:
    """Return the complete EL-2 representation persisted in ``payload``."""

    payload: dict[str, object] = {
        "evidence_id": str(evidence.evidence_id),
        "source": evidence.source.value,
        "locator": str(evidence.locator),
        "source_principal": str(evidence.source_principal),
        "captured_at": canonical_datetime(evidence.captured_at),
        "description": None if evidence.description is None else str(evidence.description),
        "event_id": None if evidence.event_id is None else str(evidence.event_id),
        "correlation_id": (
            None if evidence.correlation_id is None else str(evidence.correlation_id)
        ),
        "metadata": evidence.metadata.as_dict(),
    }
    _reject_floats(payload)
    return payload


def canonical_evidence_entry(
    *, tenant: TenantId, seq: int, prev_hash: str, evidence: EvidenceRef
) -> str:
    """Return the exact EL-1 canonical string used to derive ``entry_hash``."""

    return _canonical_entry_from_values(
        tenant_id=tenant.value,
        seq=seq,
        prev_hash=prev_hash,
        evidence_id=str(evidence.evidence_id),
        source=evidence.source.value,
        locator=str(evidence.locator),
        source_principal=str(evidence.source_principal),
        captured_at=evidence.captured_at,
        payload=canonical_evidence_payload(evidence),
    )


def compute_evidence_entry_hash(
    *, tenant: TenantId, seq: int, prev_hash: str, evidence: EvidenceRef
) -> str:
    """Compute one full-width lowercase SHA-256 evidence-chain digest."""

    canonical = canonical_evidence_entry(
        tenant=tenant,
        seq=seq,
        prev_hash=prev_hash,
        evidence=evidence,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_evidence_entry(
    *, tenant: TenantId, seq: int, prev_hash: str, evidence: EvidenceRef
) -> EvidenceEntry:
    """Assign and hash chain fields for one append without performing I/O."""

    entry_hash = compute_evidence_entry_hash(
        tenant=tenant,
        seq=seq,
        prev_hash=prev_hash,
        evidence=evidence,
    )
    canonical_evidence = evidence_from_payload(canonical_evidence_payload(evidence))
    return EvidenceEntry(
        tenant_id=tenant,
        seq=seq,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        evidence=canonical_evidence,
    )


def verify_evidence_entry(entry: EvidenceEntry) -> None:
    """Fail closed when an in-memory entry does not recompute to its stored hash."""

    expected = compute_evidence_entry_hash(
        tenant=entry.tenant_id,
        seq=entry.seq,
        prev_hash=entry.prev_hash,
        evidence=entry.evidence,
    )
    if expected != entry.entry_hash:
        raise _integrity_error(entry.tenant_id, entry.seq)


def canonical_datetime(value: datetime) -> str:
    """Render aware or naive input as the accepted canonical UTC ISO-8601 string."""

    return as_utc_datetime(value).isoformat()


def as_utc_datetime(value: datetime) -> datetime:
    """Normalize an aware value to UTC and interpret a naive value as UTC."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evidence_from_payload(payload: Mapping[str, object]) -> EvidenceRef:
    """Reconstruct the unchanged ``EvidenceRef`` from its canonical payload."""

    if frozenset(payload) != _EVIDENCE_PAYLOAD_KEYS:
        raise ValueError("evidence payload keys do not match the accepted contract")
    metadata = payload["metadata"]
    if not isinstance(metadata, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in metadata.items()
    ):
        raise ValueError("evidence metadata must be a string mapping")
    return EvidenceRef.model_validate(
        {
            "evidence_id": payload["evidence_id"],
            "source": EvidenceSource(payload["source"]),
            "locator": payload["locator"],
            "source_principal": payload["source_principal"],
            "captured_at": payload["captured_at"],
            "description": payload["description"],
            "event_id": payload["event_id"],
            "correlation_id": payload["correlation_id"],
            "metadata": Metadata.from_mapping(metadata),
        }
    )


def inspect_persisted_entry(
    *,
    tenant: TenantId,
    seq: int,
    prev_hash: object,
    entry_hash: object,
    evidence_id: object,
    source: object,
    locator: object,
    source_principal: object,
    captured_at: object,
    payload: object,
) -> tuple[EvidenceEntry | None, EvidenceIntegrityFailureKind | None]:
    """Verify and materialize one raw row without exposing corrupt content."""

    if not isinstance(prev_hash, str) or _HASH_PATTERN.fullmatch(prev_hash) is None:
        return None, EvidenceIntegrityFailureKind.PREV_HASH
    if not isinstance(entry_hash, str) or _HASH_PATTERN.fullmatch(entry_hash) is None:
        return None, EvidenceIntegrityFailureKind.ENTRY_HASH
    if not isinstance(captured_at, datetime) or not isinstance(payload, Mapping):
        return None, EvidenceIntegrityFailureKind.PAYLOAD_MISMATCH
    try:
        raw_payload = dict(payload)
        _reject_floats(raw_payload)
        canonical = _canonical_entry_from_values(
            tenant_id=tenant.value,
            seq=seq,
            prev_hash=prev_hash,
            evidence_id=evidence_id,
            source=source,
            locator=locator,
            source_principal=source_principal,
            captured_at=captured_at,
            payload=raw_payload,
        )
        expected_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if expected_hash != entry_hash:
            return None, EvidenceIntegrityFailureKind.ENTRY_HASH

        evidence = evidence_from_payload(raw_payload)
        if (
            str(evidence.evidence_id) != evidence_id
            or evidence.source.value != source
            or str(evidence.locator) != locator
            or str(evidence.source_principal) != source_principal
            or canonical_datetime(evidence.captured_at) != canonical_datetime(captured_at)
            or canonical_evidence_payload(evidence) != raw_payload
        ):
            return None, EvidenceIntegrityFailureKind.PAYLOAD_MISMATCH
        return (
            EvidenceEntry(
                tenant_id=tenant,
                seq=seq,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
                evidence=evidence,
            ),
            None,
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        return None, EvidenceIntegrityFailureKind.PAYLOAD_MISMATCH


def require_persisted_entry(**values: object) -> EvidenceEntry:
    """Materialize a raw row or raise the EL-8 non-retryable integrity error."""

    tenant = values.get("tenant")
    seq = values.get("seq")
    if not isinstance(tenant, TenantId) or not isinstance(seq, int):
        raise TypeError("tenant and seq are required")
    entry, failure = inspect_persisted_entry(**values)  # type: ignore[arg-type]
    if entry is None:
        assert failure is not None
        raise _integrity_error(tenant, seq, failure)
    return entry


def _canonical_entry_from_values(
    *,
    tenant_id: object,
    seq: object,
    prev_hash: object,
    evidence_id: object,
    source: object,
    locator: object,
    source_principal: object,
    captured_at: datetime,
    payload: Mapping[str, object],
) -> str:
    hashed_payload: dict[str, object] = {
        "captured_at": canonical_datetime(captured_at),
        "evidence_id": evidence_id,
        "locator": locator,
        "payload": dict(payload),
        "prev_hash": prev_hash,
        "seq": seq,
        "source": source,
        "source_principal": source_principal,
        "tenant_id": tenant_id,
    }
    assert frozenset(hashed_payload) == _HASHED_ENTRY_KEYS
    _reject_floats(hashed_payload)
    return json.dumps(
        hashed_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _reject_floats(value: object) -> None:
    if isinstance(value, float):
        raise ValueError("floating-point values are forbidden in evidence hashes")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_floats(key)
            _reject_floats(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            _reject_floats(nested)


def _integrity_error(
    tenant: TenantId,
    seq: int,
    failure: EvidenceIntegrityFailureKind | None = None,
) -> EvidenceLedgerIntegrityError:
    suffix = "" if failure is None else f" ({failure.value})"
    return EvidenceLedgerIntegrityError(
        f"evidence ledger integrity failure for tenant {tenant.value!r} at seq {seq}{suffix}"
    )
