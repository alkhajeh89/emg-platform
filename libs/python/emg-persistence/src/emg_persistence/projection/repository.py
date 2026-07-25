"""Projection repository contract for Sprint 6."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import ProjectionCheckpoint


@runtime_checkable
class ProjectionCheckpointRepository(Protocol):
    """Tracks processed outbox events for idempotent projection."""

    def exists(
        self,
        tenant_id: str,
        revision_number: int,
    ) -> bool: ...

    def record(
        self,
        checkpoint: ProjectionCheckpoint,
    ) -> None: ...

    def latest(self, tenant_id: str) -> ProjectionCheckpoint | None: ...
