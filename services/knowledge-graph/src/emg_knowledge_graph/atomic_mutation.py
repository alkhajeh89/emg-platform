"""Application-owned atomic mutation and replay boundary (ADR-030)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Condition
from time import monotonic
from typing import Protocol
from uuid import UUID, uuid4

from emg_platform_core import PrincipalRef, TenantId, WriteReceipt

from .commands import MutationCommand
from .errors import (
    IdempotencyContentionError,
    IdempotencyMismatchError,
    UnsupportedFingerprintVersionError,
)
from .fingerprint import (
    COMMAND_SCHEMA_VERSION,
    FINGERPRINT_VERSION,
    command_fingerprint,
    command_operation,
)
from .results import MutationResult

DEFAULT_REPLAY_RETENTION = timedelta(hours=24)
DEFAULT_CLAIM_WAIT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class MutationExecutionRequest:
    """Stable identity and fingerprint for one mutation attempt."""

    tenant: TenantId
    principal: PrincipalRef
    idempotency_key: str
    operation: str
    command_fingerprint: str
    fingerprint_version: int
    command_schema_version: int

    @classmethod
    def from_command(
        cls,
        command: MutationCommand,
        *,
        fingerprint_version: int = FINGERPRINT_VERSION,
        command_schema_version: int = COMMAND_SCHEMA_VERSION,
    ) -> MutationExecutionRequest:
        if (
            fingerprint_version != FINGERPRINT_VERSION
            or command_schema_version != COMMAND_SCHEMA_VERSION
        ):
            raise UnsupportedFingerprintVersionError(
                "active idempotency record requires an unsupported fingerprint reader"
            )
        return cls(
            tenant=command.tenant,
            principal=command.principal,
            idempotency_key=command.idempotency_key,
            operation=command_operation(command),
            command_fingerprint=command_fingerprint(command),
            fingerprint_version=fingerprint_version,
            command_schema_version=command_schema_version,
        )


@dataclass(frozen=True, slots=True)
class CommittedMutation:
    """The internal result plus the exact GraphStore commit receipt."""

    result: MutationResult
    receipt: WriteReceipt


@dataclass(frozen=True, slots=True)
class AtomicMutationOutcome:
    """Result of first execution or deterministic replay."""

    result: MutationResult
    mutation_id: UUID
    ledger_completed_at: datetime
    replayed: bool


MutationOperation = Callable[[], CommittedMutation]


class AtomicMutationExecutionPort(Protocol):
    """Application-owned port implemented by atomic persistence adapters."""

    def lookup(self, command: MutationCommand) -> AtomicMutationOutcome | None:
        """Return a completed replay before authorization, or no prior result."""
        ...

    def execute(
        self,
        request: MutationExecutionRequest,
        operation: MutationOperation,
    ) -> AtomicMutationOutcome:
        """Claim, execute, persist, and commit one mutation atomically."""
        ...


@dataclass(slots=True)
class _MemoryEntry:
    fingerprint: str
    fingerprint_version: int
    command_schema_version: int
    pending: bool
    result: MutationResult | None = None
    mutation_id: UUID | None = None
    ledger_completed_at: datetime | None = None
    expires_at: datetime | None = None


class InMemoryAtomicMutationExecution:
    """Thread-safe reference adapter used when durable persistence is absent."""

    def __init__(
        self,
        *,
        replay_retention: timedelta = DEFAULT_REPLAY_RETENTION,
        claim_wait_seconds: float = DEFAULT_CLAIM_WAIT_SECONDS,
        clock: Callable[[], datetime] | None = None,
        mutation_id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._replay_retention = replay_retention
        self._claim_wait_seconds = claim_wait_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._mutation_id_factory = mutation_id_factory or uuid4
        self._condition = Condition()
        self._entries: dict[tuple[str, str, str, str], _MemoryEntry] = {}

    @staticmethod
    def _key(request: MutationExecutionRequest) -> tuple[str, str, str, str]:
        return (
            request.tenant.value,
            request.principal.kind.value,
            str(request.principal.principal_id),
            request.idempotency_key,
        )

    @staticmethod
    def _check_fingerprint(entry: _MemoryEntry, request: MutationExecutionRequest) -> None:
        if (
            entry.fingerprint_version != request.fingerprint_version
            or entry.command_schema_version != request.command_schema_version
            or entry.fingerprint != request.command_fingerprint
        ):
            raise IdempotencyMismatchError(
                "idempotency key is already associated with a different command fingerprint"
            )

    def _completed_outcome(
        self, key: tuple[str, str, str, str], request: MutationExecutionRequest
    ) -> AtomicMutationOutcome | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        now = self._clock()
        if not entry.pending and entry.expires_at is not None and entry.expires_at <= now:
            del self._entries[key]
            return None
        self._check_fingerprint(entry, request)
        if entry.pending:
            return None
        assert entry.result is not None
        assert entry.mutation_id is not None
        assert entry.ledger_completed_at is not None
        return AtomicMutationOutcome(
            result=entry.result,
            mutation_id=entry.mutation_id,
            ledger_completed_at=entry.ledger_completed_at,
            replayed=True,
        )

    def lookup(self, command: MutationCommand) -> AtomicMutationOutcome | None:
        key = (
            command.tenant.value,
            command.principal.kind.value,
            str(command.principal.principal_id),
            command.idempotency_key,
        )
        deadline = monotonic() + self._claim_wait_seconds
        request: MutationExecutionRequest | None = None
        with self._condition:
            while True:
                entry = self._entries.get(key)
                if entry is not None and request is None:
                    if (
                        not entry.pending
                        and entry.expires_at is not None
                        and entry.expires_at <= self._clock()
                    ):
                        del self._entries[key]
                        return None
                    request = MutationExecutionRequest.from_command(
                        command,
                        fingerprint_version=entry.fingerprint_version,
                        command_schema_version=entry.command_schema_version,
                    )
                if request is None:
                    return None
                outcome = self._completed_outcome(key, request)
                if outcome is not None or key not in self._entries:
                    return outcome
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise IdempotencyContentionError(
                        "timed out waiting for the active idempotency claim"
                    )
                self._condition.wait(remaining)

    def execute(
        self,
        request: MutationExecutionRequest,
        operation: MutationOperation,
    ) -> AtomicMutationOutcome:
        key = self._key(request)
        deadline = monotonic() + self._claim_wait_seconds
        with self._condition:
            while True:
                outcome = self._completed_outcome(key, request)
                if outcome is not None:
                    return outcome
                if key not in self._entries:
                    self._entries[key] = _MemoryEntry(
                        fingerprint=request.command_fingerprint,
                        fingerprint_version=request.fingerprint_version,
                        command_schema_version=request.command_schema_version,
                        pending=True,
                    )
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise IdempotencyContentionError("timed out acquiring the idempotency claim")
                self._condition.wait(remaining)

        try:
            committed = operation()
        except BaseException:
            with self._condition:
                if self._entries.get(key) is not None:
                    del self._entries[key]
                self._condition.notify_all()
            raise

        with self._condition:
            mutation_id = self._mutation_id_factory()
            ledger_completed_at = self._clock()
            self._entries[key] = _MemoryEntry(
                fingerprint=request.command_fingerprint,
                fingerprint_version=request.fingerprint_version,
                command_schema_version=request.command_schema_version,
                pending=False,
                result=committed.result,
                mutation_id=mutation_id,
                ledger_completed_at=ledger_completed_at,
                expires_at=ledger_completed_at + self._replay_retention,
            )
            self._condition.notify_all()
        return AtomicMutationOutcome(
            result=committed.result,
            mutation_id=mutation_id,
            ledger_completed_at=ledger_completed_at,
            replayed=False,
        )
