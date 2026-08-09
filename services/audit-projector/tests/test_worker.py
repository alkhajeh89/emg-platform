from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any
from uuid import UUID

from audit_projector_helpers import (
    FakeRepository,
    FakeTransactions,
    ledger,
    settings,
    work_item,
)
from emg_audit_projector.errors import PermanentDeliveryError, RetryableDeliveryError
from emg_audit_projector.worker import AuditProjectorWorker, retry_delay
from emg_persistence.mutations import DispatchBacklog


class FakeDelivery:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[tuple[object, ...], str]] = []

    def deliver(self, events: Any, *, credential: Any, shutdown_requested: Any) -> None:
        self.calls.append((tuple(events), credential.tenant_id))
        if self.error is not None:
            raise self.error


class FakeObserver:
    def __init__(self) -> None:
        self.deliveries: list[dict[str, Any]] = []
        self.backlogs: list[tuple[str, DispatchBacklog]] = []

    def delivery(self, **kwargs: Any) -> None:
        self.deliveries.append(kwargs)

    def backlog(self, *, tenant_id: str, snapshot: DispatchBacklog) -> None:
        self.backlogs.append((tenant_id, snapshot))


def _worker(
    repository: FakeRepository,
    delivery: FakeDelivery,
    *,
    configured: Any | None = None,
    observer: FakeObserver | None = None,
) -> AuditProjectorWorker:
    return AuditProjectorWorker(
        configured or settings(),
        FakeTransactions(),  # type: ignore[arg-type]
        delivery,  # type: ignore[arg-type]
        repository_factory=lambda connection: repository,
        observer=observer,
    )


def _call_names(repository: FakeRepository) -> list[str]:
    return [name for name, _ in repository.calls]


def test_claims_are_partitioned_by_tenant_and_audit_channel() -> None:
    repository = FakeRepository({})
    worker = _worker(repository, FakeDelivery(), configured=settings(tenants=("a", "b")))

    assert not worker.run_cycle()

    claims = [kwargs for name, kwargs in repository.calls if name == "claim"]
    assert [claim["tenant_id"] for claim in claims] == ["a", "b"]
    assert all(claim["channel"] == "audit" for claim in claims)
    assert all(claim["max_attempts"] == 8 for claim in claims)


def test_success_acknowledges_only_after_all_events_are_delivered() -> None:
    record = ledger(intent_count=2)
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record),)
    delivery = FakeDelivery()

    assert _worker(repository, delivery).run_cycle()

    assert len(delivery.calls[0][0]) == 2
    assert _call_names(repository).index("complete") > _call_names(repository).index("ledger")
    assert "reschedule" not in _call_names(repository)
    assert "exhaust" not in _call_names(repository)


def test_retryable_failure_is_explicitly_rescheduled() -> None:
    record = ledger()
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record, attempt_count=3),)
    observer = FakeObserver()

    _worker(
        repository,
        FakeDelivery(RetryableDeliveryError("outage")),
        observer=observer,
    ).run_cycle()

    reschedule = next(kwargs for name, kwargs in repository.calls if name == "reschedule")
    assert reschedule["delay"] == retry_delay(record.mutation_id, 3)
    assert "complete" not in _call_names(repository)
    assert observer.deliveries[0]["outcome"] == "retry"


def test_eighth_retryable_failure_becomes_visible_exhausted_work() -> None:
    record = ledger()
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record, attempt_count=8),)

    _worker(repository, FakeDelivery(RetryableDeliveryError("outage"))).run_cycle()

    assert "exhaust" in _call_names(repository)
    assert "reschedule" not in _call_names(repository)
    assert "complete" not in _call_names(repository)


def test_poison_record_is_exhausted_without_delivery_or_rewrite() -> None:
    record = ledger()
    record.audit_intents["schema_version"] = 999
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record),)
    delivery = FakeDelivery()

    _worker(repository, delivery).run_cycle()

    assert delivery.calls == []
    assert "exhaust" in _call_names(repository)
    assert "complete" not in _call_names(repository)


def test_permanent_credential_failure_is_exhausted_not_acknowledged() -> None:
    record = ledger()
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record),)

    _worker(repository, FakeDelivery(PermanentDeliveryError("mismatch"))).run_cycle()

    assert "exhaust" in _call_names(repository)
    assert "complete" not in _call_names(repository)


def test_crash_after_delivery_before_ack_relies_on_lease_recovery() -> None:
    record = ledger()
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record),)
    repository.complete_error = RuntimeError("worker crashed before acknowledgement")
    observer = FakeObserver()

    _worker(repository, FakeDelivery(), observer=observer).run_cycle()

    assert "complete" in _call_names(repository)
    assert "reschedule" not in _call_names(repository)
    assert "exhaust" not in _call_names(repository)
    assert observer.deliveries[0]["outcome"] == "lease_recovery"


def test_backlog_snapshot_is_emitted_without_affecting_work() -> None:
    repository = FakeRepository({})
    repository.backlog = DispatchBacklog(5, 1, 2, 12.5)
    observer = FakeObserver()

    _worker(repository, FakeDelivery(), observer=observer).run_cycle()

    assert observer.backlogs == [("tenant-a", repository.backlog)]


def test_retry_jitter_is_stable_bounded_and_capped() -> None:
    mutation_id = UUID("11111111-1111-1111-1111-111111111111")
    assert retry_delay(mutation_id, 3) == retry_delay(mutation_id, 3)
    assert timedelta(seconds=4) <= retry_delay(mutation_id, 3) <= timedelta(seconds=5)
    assert retry_delay(mutation_id, 99) <= timedelta(seconds=300)


def test_graceful_stop_interrupts_idle_poll_and_joins() -> None:
    repository = FakeRepository({})
    worker = _worker(
        repository,
        FakeDelivery(),
        configured=settings(poll_interval_seconds=10.0),
    )
    thread = threading.Thread(target=worker.run)
    thread.start()
    worker.stop()
    thread.join(timeout=1)
    assert not thread.is_alive()
