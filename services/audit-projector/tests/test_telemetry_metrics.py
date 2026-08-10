from __future__ import annotations

from uuid import uuid4

from emg_audit_projector.telemetry import (
    CompositeProjectorObserver,
    ProjectorObserver,
    PrometheusProjectorObserver,
)
from emg_persistence.mutations import DispatchBacklog
from emg_telemetry.metrics import MetricsRegistry


def test_delivery_never_labels_with_tenant_id_or_mutation_id():
    """Tenant/mutation safety: only outcome and failure_class may appear as
    label values, never the raw tenant_id or mutation_id passed in."""
    registry = MetricsRegistry()
    observer = PrometheusProjectorObserver(registry=registry)

    observer.delivery(
        tenant_id="tenant-should-not-leak",
        mutation_id=uuid4(),
        attempt_count=1,
        outcome="success",
        duration_seconds=0.25,
    )

    text = registry.render()
    assert "tenant-should-not-leak" not in text
    assert 'audit_dispatch_delivery_total{outcome="success",failure_class=""} 1.0' in text


def test_backlog_aggregates_across_tenants_without_tenant_labels():
    """Two tenants' backlog snapshots must collapse into sum/max gauges with
    zero labels -- never one time series per tenant."""
    registry = MetricsRegistry()
    observer = PrometheusProjectorObserver(registry=registry)

    observer.backlog(
        tenant_id="tenant-a",
        snapshot=DispatchBacklog(
            pending_count=3,
            oldest_pending_age_seconds=10.0,
            in_flight_count=1,
            exhausted_count=0,
        ),
    )
    observer.backlog(
        tenant_id="tenant-b",
        snapshot=DispatchBacklog(
            pending_count=7,
            oldest_pending_age_seconds=90.0,
            in_flight_count=2,
            exhausted_count=1,
        ),
    )

    text = registry.render()
    assert "tenant-a" not in text
    assert "tenant-b" not in text
    assert "audit_dispatch_pending_depth_sum 10.0" in text
    assert "audit_dispatch_pending_depth_max 7.0" in text
    assert "audit_dispatch_oldest_pending_age_max_seconds 90.0" in text
    assert "audit_dispatch_in_flight_sum 3.0" in text
    assert "audit_dispatch_exhausted_sum 1.0" in text


def test_backlog_updates_replace_the_same_tenants_prior_snapshot():
    """A tenant's second backlog observation must replace, not add to, its
    first -- otherwise the sum would double-count a shrinking backlog."""
    registry = MetricsRegistry()
    observer = PrometheusProjectorObserver(registry=registry)

    snapshot = DispatchBacklog(
        pending_count=5, oldest_pending_age_seconds=1.0, in_flight_count=0, exhausted_count=0
    )
    observer.backlog(tenant_id="tenant-a", snapshot=snapshot)
    observer.backlog(
        tenant_id="tenant-a",
        snapshot=DispatchBacklog(
            pending_count=1, oldest_pending_age_seconds=1.0, in_flight_count=0, exhausted_count=0
        ),
    )

    text = registry.render()
    assert "audit_dispatch_pending_depth_sum 1.0" in text


class _RecordingObserver:
    def __init__(self) -> None:
        self.delivery_calls: list[str] = []
        self.backlog_calls: list[str] = []

    def delivery(self, **kwargs: object) -> None:
        self.delivery_calls.append("called")

    def backlog(self, **kwargs: object) -> None:
        self.backlog_calls.append("called")


class _BrokenObserver:
    def delivery(self, **kwargs: object) -> None:
        raise RuntimeError("boom")

    def backlog(self, **kwargs: object) -> None:
        raise RuntimeError("boom")


def test_composite_observer_fans_out_to_every_wrapped_observer():
    first: ProjectorObserver = _RecordingObserver()  # type: ignore[assignment]
    second: ProjectorObserver = _RecordingObserver()  # type: ignore[assignment]
    composite = CompositeProjectorObserver(first, second)

    composite.delivery(
        tenant_id="t",
        mutation_id=uuid4(),
        attempt_count=1,
        outcome="success",
        duration_seconds=0.1,
    )
    composite.backlog(
        tenant_id="t",
        snapshot=DispatchBacklog(
            pending_count=0, oldest_pending_age_seconds=0.0, in_flight_count=0, exhausted_count=0
        ),
    )

    assert first.delivery_calls == ["called"]  # type: ignore[attr-defined]
    assert second.delivery_calls == ["called"]  # type: ignore[attr-defined]
    assert first.backlog_calls == ["called"]  # type: ignore[attr-defined]
    assert second.backlog_calls == ["called"]  # type: ignore[attr-defined]


def test_composite_observer_one_broken_observer_does_not_suppress_another():
    broken: ProjectorObserver = _BrokenObserver()  # type: ignore[assignment]
    recording: ProjectorObserver = _RecordingObserver()  # type: ignore[assignment]
    composite = CompositeProjectorObserver(broken, recording)

    # Must not raise.
    composite.delivery(
        tenant_id="t",
        mutation_id=uuid4(),
        attempt_count=1,
        outcome="success",
        duration_seconds=0.1,
    )

    assert recording.delivery_calls == ["called"]  # type: ignore[attr-defined]
