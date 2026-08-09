"""Collector-ready structured observations; no dashboard or metrics backend."""

from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from emg_persistence.mutations import DispatchBacklog
from emg_telemetry import get_logger

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
