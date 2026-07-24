"""Outbox repository contract for Phase 2 Sprint 5."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from emg_platform_core import TenantId

from .model import OutboxEvent


@runtime_checkable
class OutboxRepository(Protocol):
    """Append-only persistence contract for transactional outbox events."""

    def append(self, event: OutboxEvent) -> None:
        """Persist one outbox event atomically with the owning transaction."""
        ...

    def list_for_tenant(
        self, tenant: TenantId, *, after_revision: int = 0, limit: int = 100
    ) -> tuple[OutboxEvent, ...]:
        """Return outbox events for ``tenant`` with ``revision_number > after_revision``.

        Ordered by ``revision_number`` ascending. Used by the explicit
        projection worker (never by ``GraphStore.write``).
        """
        ...
