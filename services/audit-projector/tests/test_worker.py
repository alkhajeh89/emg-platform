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
from emg_audit_projector.errors import (
    PermanentDeliveryError,
    RetryableDeliveryError,
    ShutdownRequested,
)
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
    monotonic: Any | None = None,
) -> AuditProjectorWorker:
    kwargs: dict[str, Any] = {}
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    return AuditProjectorWorker(
        configured or settings(),
        FakeTransactions(),  # type: ignore[arg-type]
        delivery,  # type: ignore[arg-type]
        repository_factory=lambda connection: repository,
        observer=observer,
        **kwargs,
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


def test_shutdown_before_claim_does_not_acquire_or_modify_work() -> None:
    repository = FakeRepository({})
    delivery = FakeDelivery()
    worker = _worker(repository, delivery)

    worker.stop()

    assert worker.run_cycle() is False
    assert repository.calls == []
    assert delivery.calls == []


def test_shutdown_during_active_mutation_drains_and_acknowledges_normally() -> None:
    first = ledger()
    second = ledger()
    repository = FakeRepository({first.mutation_id: first, second.mutation_id: second})
    repository.claims[first.tenant_id] = (work_item(first), work_item(second))

    class DrainingDelivery(FakeDelivery):
        worker: AuditProjectorWorker

        def deliver(self, events: Any, *, credential: Any, shutdown_requested: Any) -> None:
            super().deliver(
                events,
                credential=credential,
                shutdown_requested=shutdown_requested,
            )
            self.worker.stop()
            assert shutdown_requested() is False

    delivery = DrainingDelivery()
    worker = _worker(repository, delivery)
    delivery.worker = worker

    assert worker.run_cycle() is True

    assert len(delivery.calls) == 1
    assert _call_names(repository).count("complete") == 1
    assert _call_names(repository).count("ledger") == 1
    assert "reschedule" not in _call_names(repository)
    assert "exhaust" not in _call_names(repository)


def test_shutdown_interruption_preserves_claim_without_retry_mutation() -> None:
    record = ledger()
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record),)
    observer = FakeObserver()

    _worker(
        repository,
        FakeDelivery(ShutdownRequested("drain deadline reached")),
        observer=observer,
    ).run_cycle()

    assert "complete" not in _call_names(repository)
    assert "reschedule" not in _call_names(repository)
    assert "exhaust" not in _call_names(repository)
    assert observer.deliveries[0]["outcome"] == "lease_recovery"


def test_adversarial_shutdown_after_ledger_load_never_reschedules() -> None:
    record = ledger()
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record),)

    _worker(
        repository,
        FakeDelivery(ShutdownRequested("adversarial shutdown boundary")),
    ).run_cycle()

    assert _call_names(repository)[:2] == ["claim", "ledger"]
    assert "reschedule" not in _call_names(repository)
    assert "complete" not in _call_names(repository)
    assert "exhaust" not in _call_names(repository)


def test_partial_multi_intent_shutdown_replays_safely_after_lease_expiry() -> None:
    record = ledger(intent_count=2)
    first_repository = FakeRepository({record.mutation_id: record})
    first_repository.claims[record.tenant_id] = (work_item(record),)
    accepted: list[str] = []

    class PartialDelivery(FakeDelivery):
        def deliver(self, events: Any, *, credential: Any, shutdown_requested: Any) -> None:
            del credential, shutdown_requested
            accepted.append(events[0].event_id)
            raise ShutdownRequested("drain deadline reached between intents")

    _worker(first_repository, PartialDelivery()).run_cycle()

    assert "complete" not in _call_names(first_repository)
    assert "reschedule" not in _call_names(first_repository)
    assert "exhaust" not in _call_names(first_repository)

    recovered_repository = FakeRepository({record.mutation_id: record})
    recovered_repository.claims[record.tenant_id] = (work_item(record),)
    recovered_delivery = FakeDelivery()
    _worker(recovered_repository, recovered_delivery).run_cycle()

    replayed = [event.event_id for event in recovered_delivery.calls[0][0]]
    assert replayed == [
        f"kg-mutation:{record.mutation_id}:0",
        f"kg-mutation:{record.mutation_id}:1",
    ]
    assert accepted[0] == replayed[0]
    assert "complete" in _call_names(recovered_repository)


def test_active_delivery_observes_shutdown_only_after_drain_deadline() -> None:
    record = ledger()
    repository = FakeRepository({record.mutation_id: record})
    repository.claims[record.tenant_id] = (work_item(record),)

    class Clock:
        value = 10.0

        def __call__(self) -> float:
            return self.value

    class DeadlineDelivery(FakeDelivery):
        worker: AuditProjectorWorker

        def deliver(self, events: Any, *, credential: Any, shutdown_requested: Any) -> None:
            del events, credential
            self.worker.stop()
            assert shutdown_requested() is False
            clock.value += 20.0
            assert shutdown_requested() is True

    clock = Clock()
    delivery = DeadlineDelivery()
    worker = _worker(
        repository,
        delivery,
        configured=settings(drain_timeout_seconds=20.0, lease_seconds=30.0),
        monotonic=clock,
    )
    delivery.worker = worker

    worker.run_cycle()

    assert "complete" not in _call_names(repository)
    assert "reschedule" not in _call_names(repository)
