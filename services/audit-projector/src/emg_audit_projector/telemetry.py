"""Collector-ready structured observations, plus (RC-C) a Prometheus-format
metrics observer wiring the same signal into `/metrics` (see
`emg_audit_projector.metrics_server`). The dashboard/alert *backend* choice
itself remains unmade -- see `metrics.py`'s module docstring -- this module
only emits in a format any Prometheus-compatible scraper can consume."""

from __future__ import annotations

import json
import threading
from typing import Protocol
from uuid import UUID

from emg_persistence.mutations import DispatchBacklog
from emg_telemetry import get_logger
from emg_telemetry.metrics import MetricsRegistry, get_registry

_log = get_logger("audit-projector")


class ProjectorObserver(Protocol):
    def delivery(
        self,
        *,
        tenant_id: str,
        mutation_id: UUID,
        attempt_count: int,
        outcome: str,
        duration_seconds: float,
        failure_class: str | None = None,
    ) -> None: ...

    def backlog(self, *, tenant_id: str, snapshot: DispatchBacklog) -> None: ...


class StructuredProjectorObserver:
    @staticmethod
    def _emit(document: dict[str, object], *, action: str, outcome: str) -> None:
        try:
            _log.info(
                json.dumps(document, sort_keys=True, separators=(",", ":")),
                extra={
                    "actor": "audit-projector",
                    "module": "audit-projector",
                    "action": action,
                    "outcome": outcome,
                },
            )
        except Exception:
            return

    def delivery(
        self,
        *,
        tenant_id: str,
        mutation_id: UUID,
        attempt_count: int,
        outcome: str,
        duration_seconds: float,
        failure_class: str | None = None,
    ) -> None:
        self._emit(
            {
                "event": "audit_dispatch_delivery",
                "tenant_id": tenant_id,
                "mutation_id": str(mutation_id),
                "attempt_count": attempt_count,
                "outcome": outcome,
                "duration_seconds": max(0.0, duration_seconds),
                "failure_class": failure_class,
            },
            action="dispatch_delivery",
            outcome=outcome,
        )

    def backlog(self, *, tenant_id: str, snapshot: DispatchBacklog) -> None:
        for metric_name, value in (
            ("audit_dispatch_pending_depth", snapshot.pending_count),
            ("audit_dispatch_oldest_pending_age_seconds", snapshot.oldest_pending_age_seconds),
            ("audit_dispatch_in_flight", snapshot.in_flight_count),
            ("audit_dispatch_exhausted_count", snapshot.exhausted_count),
        ):
            self._emit(
                {
                    "event": "audit_dispatch_metric",
                    "tenant_id": tenant_id,
                    "metric_name": metric_name,
                    "metric_type": "gauge",
                    "metric_value": value,
                },
                action="dispatch_metric",
                outcome="observed",
            )


class PrometheusProjectorObserver:
    """Wires the same collector-ready signal `StructuredProjectorObserver`
    already emits (ADR-015 Section 2) into `/metrics` (RC-C). Never labels
    with `tenant_id`: this is a tenant-partitioned, config-driven worker
    (one process per deployment, tenants come from `Settings.tenant_credentials`),
    so per-tenant backlog is tracked only in this observer's own in-process
    state and exposed as untenanted aggregates (sum across tenants for
    depth/in-flight/exhausted counts, max across tenants for the oldest
    pending age and for backlog depth) -- one gauge each, regardless of how
    many tenants are configured, so tenant count can never grow metric
    cardinality."""

    def __init__(self, *, registry: MetricsRegistry | None = None) -> None:
        reg = registry or get_registry()
        self._delivery_total = reg.counter(
            "audit_dispatch_delivery_total",
            "Audit Projector dispatch delivery attempts, by outcome and failure class.",
            ("outcome", "failure_class"),
        )
        self._delivery_duration_seconds = reg.histogram(
            "audit_dispatch_delivery_duration_seconds",
            "Audit Projector dispatch delivery duration in seconds, by outcome.",
            ("outcome",),
        )
        self._pending_depth_sum = reg.gauge(
            "audit_dispatch_pending_depth_sum",
            "Sum, across all configured tenants, of pending audit dispatch entries.",
        )
        self._pending_depth_max = reg.gauge(
            "audit_dispatch_pending_depth_max",
            "Largest single tenant's pending audit dispatch depth.",
        )
        self._oldest_pending_age_max_seconds = reg.gauge(
            "audit_dispatch_oldest_pending_age_max_seconds",
            "Largest single tenant's oldest-pending-entry age in seconds.",
        )
        self._in_flight_sum = reg.gauge(
            "audit_dispatch_in_flight_sum",
            "Sum, across all configured tenants, of in-flight audit dispatch entries.",
        )
        self._exhausted_sum = reg.gauge(
            "audit_dispatch_exhausted_sum",
            "Sum, across all configured tenants, of exhausted (max-attempts-reached) "
            "audit dispatch entries awaiting operator remediation.",
        )
        self._lock = threading.Lock()
        self._backlog_by_tenant: dict[str, DispatchBacklog] = {}

    def delivery(
        self,
        *,
        tenant_id: str,
        mutation_id: UUID,
        attempt_count: int,
        outcome: str,
        duration_seconds: float,
        failure_class: str | None = None,
    ) -> None:
        del tenant_id, mutation_id, attempt_count  # never used as label values
        self._delivery_total.inc(labels=(outcome, failure_class or ""))
        self._delivery_duration_seconds.observe(max(0.0, duration_seconds), labels=(outcome,))

    def backlog(self, *, tenant_id: str, snapshot: DispatchBacklog) -> None:
        with self._lock:
            self._backlog_by_tenant[tenant_id] = snapshot
            snapshots = tuple(self._backlog_by_tenant.values())
        self._pending_depth_sum.set(float(sum(s.pending_count for s in snapshots)))
        self._pending_depth_max.set(float(max((s.pending_count for s in snapshots), default=0)))
        self._oldest_pending_age_max_seconds.set(
            float(max((s.oldest_pending_age_seconds for s in snapshots), default=0.0))
        )
        self._in_flight_sum.set(float(sum(s.in_flight_count for s in snapshots)))
        self._exhausted_sum.set(float(sum(s.exhausted_count for s in snapshots)))


class CompositeProjectorObserver:
    """Fan out to every wrapped observer; one failing observer must never
    suppress another (mirrors `StructuredProjectorObserver._emit`'s own
    "observability must never affect worker behavior" contract)."""

    def __init__(self, *observers: ProjectorObserver) -> None:
        self._observers = observers

    def delivery(
        self,
        *,
        tenant_id: str,
        mutation_id: UUID,
        attempt_count: int,
        outcome: str,
        duration_seconds: float,
        failure_class: str | None = None,
    ) -> None:
        for observer in self._observers:
            try:
                observer.delivery(
                    tenant_id=tenant_id,
                    mutation_id=mutation_id,
                    attempt_count=attempt_count,
                    outcome=outcome,
                    duration_seconds=duration_seconds,
                    failure_class=failure_class,
                )
            except Exception:
                continue

    def backlog(self, *, tenant_id: str, snapshot: DispatchBacklog) -> None:
        for observer in self._observers:
            try:
                observer.backlog(tenant_id=tenant_id, snapshot=snapshot)
            except Exception:
                continue
