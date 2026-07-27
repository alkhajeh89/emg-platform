"""Immutable persistence records for ADR-030's mutation ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import total_ordering
from uuid import UUID


class IdempotencyState(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    LEGACY_SUCCEEDED = "legacy_succeeded"


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    tenant_id: str
    principal_id: str
    idempotency_key: str
    operation: str
    state: IdempotencyState
    requested_at: datetime
    expires_at: datetime
    command_fingerprint: str | None
    fingerprint_version: int | None
    command_schema_version: int | None
    mutation_id: UUID | None
    mutation_result: dict[str, object] | None
    acquired: bool


@dataclass(frozen=True, slots=True)
class LedgerResource:
    ordinal: int
    resource_type: str
    resource_id: str
    action: str
    classification: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class LedgerAppend:
    mutation_id: UUID
    tenant_id: str
    principal_id: str
    principal_kind: str
    idempotency_key: str
    command_fingerprint: str
    fingerprint_version: int
    command_schema_version: int
    operation: str
    status: str
    graph_revision: int
    graph_content_hash: str
    graph_revision_at: datetime
    write_receipt: dict[str, object]
    mutation_result: dict[str, object]
    audit_intents: dict[str, object]
    resources: tuple[LedgerResource, ...]


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    mutation_id: UUID
    tenant_id: str
    principal_id: str
    principal_kind: str
    idempotency_key: str
    command_fingerprint: str
    fingerprint_version: int
    command_schema_version: int
    operation: str
    status: str
    graph_revision: int
    graph_content_hash: str
    write_receipt: dict[str, object]
    mutation_result: dict[str, object]
    audit_intents: dict[str, object]
    requested_at: datetime
    ledger_completed_at: datetime
    graph_revision_at: datetime
    replay_expires_at: datetime
    resource_count: int


@dataclass(frozen=True, slots=True)
class DispatchWorkItem:
    mutation_id: UUID
    tenant_id: str
    channel: str
    available_at: datetime
    attempt_count: int
    claim_owner: str
    claim_expires_at: datetime
    source_position: LsnPosition | None


def _lsn_value(value: str) -> int:
    high, separator, low = value.partition("/")
    if separator != "/" or not high or not low:
        raise ValueError(f"invalid PostgreSQL LSN: {value!r}")
    try:
        return (int(high, 16) << 32) + int(low, 16)
    except ValueError as exc:
        raise ValueError(f"invalid PostgreSQL LSN: {value!r}") from exc


@total_ordering
@dataclass(frozen=True, slots=True)
class LsnPosition:
    """CDC source position; comparable only within one system/timeline."""

    system_id: str
    timeline: int
    commit_lsn: str
    transaction_index: int

    def _order_key(self) -> tuple[int, int]:
        return _lsn_value(self.commit_lsn), self.transaction_index

    def _check_stream(self, other: LsnPosition) -> None:
        if (self.system_id, self.timeline) != (other.system_id, other.timeline):
            raise ValueError("LSN positions from different source timelines are incomparable")

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, LsnPosition):
            return NotImplemented
        self._check_stream(other)
        return self._order_key() < other._order_key()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LsnPosition):
            return False
        return (
            self.system_id,
            self.timeline,
            self._order_key(),
        ) == (
            other.system_id,
            other.timeline,
            other._order_key(),
        )
