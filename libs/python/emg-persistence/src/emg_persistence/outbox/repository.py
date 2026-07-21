"""Outbox repository contract for Phase 2 Sprint 5."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import OutboxEvent


@runtime_checkable
class OutboxRepository(Protocol):
    """Append-only persistence contract for transactional outbox events."""

    def append(self, event: OutboxEvent) -> None:
        """Persist one outbox event atomically with the owning transaction."""
        ...
