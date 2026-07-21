"""Reusable OutboxRepository test doubles and event constructors."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from emg_persistence.outbox import OutboxEvent
from emg_platform_core import TenantId

TENANT_A = TenantId.of("tenant-a")


class RecordingOutboxRepository:
    def __init__(self, lifecycle: list[str] | None = None) -> None:
        self.events: list[OutboxEvent] = []
        self._lifecycle = lifecycle

    def append(self, event: OutboxEvent) -> None:
        if self._lifecycle is not None:
            self._lifecycle.append("outbox")
        self.events.append(event)


def make_outbox_event(
    *,
    event_id: UUID,
    tenant: TenantId = TENANT_A,
    revision_number: int = 1,
    idempotency_key: str | None = None,
) -> OutboxEvent:
    created_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    return OutboxEvent(
        event_id=event_id,
        tenant=tenant,
        revision_number=revision_number,
        content_hash="a" * 64,
        event_type="graph.revision.committed",
        schema_version=1,
        idempotency_key=(
            idempotency_key if idempotency_key is not None else f"{tenant.value}:{revision_number}"
        ),
        payload={"revision_number": revision_number},
        created_at=created_at,
    )
