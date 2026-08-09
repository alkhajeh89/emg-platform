"""Bounded, single-replica RC1 Audit Projector worker."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import timedelta
from threading import Event
from typing import Any, Protocol
from uuid import UUID

from emg_persistence.mutations import DispatchBacklog, DispatchWorkItem, LedgerRecord
from emg_persistence.postgres import PostgresMutationRepository, TransactionProvider

from .config import Settings, TenantCredential
from .delivery import AuditDeliveryClient
from .errors import PermanentDeliveryError, RetryableDeliveryError, ShutdownRequested
from .projection import project_audit_events
from .telemetry import ProjectorObserver, StructuredProjectorObserver


class MutationRepository(Protocol):
    def claim_dispatch(
        self,
        *,
        tenant_id: str,
        channel: str,
        worker: str,
        limit: int,
        max_attempts: int,
        lease: timedelta,
    ) -> tuple[DispatchWorkItem, ...]: ...

    def get_ledger(self, *, tenant_id: str, mutation_id: object) -> LedgerRecord | None: ...

    def complete_dispatch(
        self, *, tenant_id: str, mutation_id: object, channel: str, worker: str
    ) -> None: ...

    def reschedule_dispatch(
        self,
        *,
        tenant_id: str,
        mutation_id: object,
        channel: str,
        worker: str,
        delay: timedelta,
    ) -> None: ...

    def exhaust_dispatch(
        self,
        *,
        tenant_id: str,
        mutation_id: object,
        channel: str,
        worker: str,
        max_attempts: int,
    ) -> None: ...

    def dispatch_backlog(
        self, *, tenant_id: str, channel: str, max_attempts: int
    ) -> DispatchBacklog: ...


RepositoryFactory = Callable[[Any], MutationRepository]


def _postgres_repository(connection: Any) -> MutationRepository:
    return PostgresMutationRepository(connection)


def retry_delay(mutation_id: UUID, attempt_count: int) -> timedelta:
    """ADR-028 D-48: deterministic 0–25% jitter and a 300-second ceiling."""

    digest = hashlib.sha256(f"{mutation_id}:{attempt_count}".encode()).digest()
    jitter = int.from_bytes(digest[:2], "big") / 65535 * 0.25
    seconds = min(300.0, (2 ** max(0, attempt_count - 1)) * (1 + jitter))
    return timedelta(seconds=seconds)


class AuditProjectorWorker:
    def __init__(
        self,
        settings: Settings,
        transactions: TransactionProvider,
        delivery: AuditDeliveryClient,
        *,
        repository_factory: RepositoryFactory = _postgres_repository,
        observer: ProjectorObserver | None = None,
        stop_event: Event | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._transactions = transactions
        self._delivery = delivery
        self._repository_factory = repository_factory
        self._observer = observer or StructuredProjectorObserver()
        self._stop = stop_event or Event()
        self._monotonic = monotonic
        self._credentials = {
            credential.tenant_id: credential for credential in settings.tenant_credentials
        }
        self._last_telemetry = float("-inf")
        self._drain_deadline: float | None = None

    def stop(self) -> None:
        if not self._stop.is_set():
            self._drain_deadline = self._monotonic() + self._settings.drain_timeout_seconds
        self._stop.set()

    def _drain_deadline_reached(self) -> bool:
        deadline = self._drain_deadline
        return self._stop.is_set() and deadline is not None and self._monotonic() >= deadline

    def run(self) -> None:
        while not self._stop.is_set():
            worked = self.run_cycle()
            if not worked:
                self._stop.wait(self._settings.poll_interval_seconds)

    def run_cycle(self) -> bool:
        worked = False
        for tenant_id, credential in self._credentials.items():
            if self._stop.is_set():
                break
            for item in self._claim(tenant_id):
                worked = True
                self._process(item, credential)
                if self._stop.is_set():
                    break
            self._observe_backlog_if_due(tenant_id)
        return worked

    def _claim(self, tenant_id: str) -> tuple[DispatchWorkItem, ...]:
        with self._transactions.transaction() as connection:
            return self._repository_factory(connection).claim_dispatch(
                tenant_id=tenant_id,
                channel="audit",
                worker=self._settings.worker_id,
                limit=self._settings.batch_size,
                max_attempts=self._settings.max_attempts,
                lease=timedelta(seconds=self._settings.lease_seconds),
            )

    def _ledger(self, item: DispatchWorkItem) -> LedgerRecord:
        with self._transactions.transaction() as connection:
            ledger = self._repository_factory(connection).get_ledger(
                tenant_id=item.tenant_id,
                mutation_id=item.mutation_id,
            )
        if ledger is None:
            raise PermanentDeliveryError("claimed dispatch has no immutable ledger row")
        return ledger

    def _process(self, item: DispatchWorkItem, credential: TenantCredential) -> None:
        started = self._monotonic()
        try:
            ledger = self._ledger(item)
            events = project_audit_events(ledger)
            self._delivery.deliver(
                events,
                credential=credential,
                shutdown_requested=self._drain_deadline_reached,
            )
            if self._drain_deadline_reached():
                raise ShutdownRequested("projector drain deadline reached before acknowledgement")
            with self._transactions.transaction() as connection:
                self._repository_factory(connection).complete_dispatch(
                    tenant_id=item.tenant_id,
                    mutation_id=item.mutation_id,
                    channel="audit",
                    worker=self._settings.worker_id,
                )
            self._observe_delivery(item, started=started, outcome="success")
        except ShutdownRequested as exc:
            # D-51: termination is not a delivery failure. Leave the active
            # claim untouched so its existing lease is the sole recovery path.
            self._observe_delivery(
                item,
                started=started,
                outcome="lease_recovery",
                failure_class=type(exc).__name__,
            )
        except PermanentDeliveryError as exc:
            self._exhaust(item)
            self._observe_delivery(
                item,
                started=started,
                outcome="exhausted",
                failure_class=type(exc).__name__,
            )
        except RetryableDeliveryError as exc:
            if item.attempt_count >= self._settings.max_attempts:
                self._exhaust(item)
                outcome = "exhausted"
            else:
                self._reschedule(item)
                outcome = "retry"
            self._observe_delivery(
                item,
                started=started,
                outcome=outcome,
                failure_class=type(exc).__name__,
            )
        except Exception as exc:
            # Database/claim failures cannot be safely rewritten. The existing
            # lease preserves the row for crash-style recovery.
            self._observe_delivery(
                item,
                started=started,
                outcome="lease_recovery",
                failure_class=type(exc).__name__,
            )

    def _reschedule(self, item: DispatchWorkItem) -> None:
        with self._transactions.transaction() as connection:
            self._repository_factory(connection).reschedule_dispatch(
                tenant_id=item.tenant_id,
                mutation_id=item.mutation_id,
                channel="audit",
                worker=self._settings.worker_id,
                delay=retry_delay(item.mutation_id, item.attempt_count),
            )

    def _exhaust(self, item: DispatchWorkItem) -> None:
        with self._transactions.transaction() as connection:
            self._repository_factory(connection).exhaust_dispatch(
                tenant_id=item.tenant_id,
                mutation_id=item.mutation_id,
                channel="audit",
                worker=self._settings.worker_id,
                max_attempts=self._settings.max_attempts,
            )

    def _observe_delivery(
        self,
        item: DispatchWorkItem,
        *,
        started: float,
        outcome: str,
        failure_class: str | None = None,
    ) -> None:
        self._observer.delivery(
            tenant_id=item.tenant_id,
            mutation_id=item.mutation_id,
            attempt_count=item.attempt_count,
            outcome=outcome,
            duration_seconds=max(0.0, self._monotonic() - started),
            failure_class=failure_class,
        )

    def _observe_backlog_if_due(self, tenant_id: str) -> None:
        now = self._monotonic()
        if now - self._last_telemetry < self._settings.telemetry_interval_seconds:
            return
        with self._transactions.transaction() as connection:
            snapshot = self._repository_factory(connection).dispatch_backlog(
                tenant_id=tenant_id,
                channel="audit",
                max_attempts=self._settings.max_attempts,
            )
        self._observer.backlog(tenant_id=tenant_id, snapshot=snapshot)
        self._last_telemetry = now
