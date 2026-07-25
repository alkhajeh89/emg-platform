"""Explicit projection worker — outbox + checkpoint driven (ADR-6 refinement).

Never started by ``GraphStore.write()``. Operators/CI call ``process_once`` /
``process_tenant`` to advance Neo4j via the same catch-up path as read-repair.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from emg_platform_core import TenantId

from ..errors import PersistenceError
from ..neo4j.projection import Neo4jGraphProjection
from ..outbox import OutboxRepository
from ..postgres.transactions import TransactionProvider
from ..revisions import RevisionRepository
from .model import ProjectionCheckpoint
from .repository import ProjectionCheckpointRepository

if TYPE_CHECKING:
    from psycopg import Connection

Clock = Callable[[], datetime]
OutboxFactory = Callable[["Connection[Any]"], OutboxRepository]
RevisionFactory = Callable[["Connection[Any]"], RevisionRepository]
CheckpointFactory = Callable[["Connection[Any]"], ProjectionCheckpointRepository]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectionWorker:
    """Process ``graph.revision.committed`` outbox events into Neo4j projection."""

    def __init__(
        self,
        transactions: TransactionProvider,
        projection: Neo4jGraphProjection,
        *,
        outbox_factory: OutboxFactory,
        revision_factory: RevisionFactory,
        checkpoint_factory: CheckpointFactory,
        clock: Clock = _utcnow,
        batch_size: int = 100,
    ) -> None:
        self._transactions = transactions
        self._projection = projection
        self._outbox_factory = outbox_factory
        self._revision_factory = revision_factory
        self._checkpoint_factory = checkpoint_factory
        self._clock = clock
        self._batch_size = batch_size

    def process_tenant(self, tenant: TenantId) -> int:
        """Catch up projection for ``tenant`` and record checkpoints. Returns events processed."""
        processed = 0
        while True:
            batch = self._load_batch(tenant)
            if not batch:
                break
            # Apply via shared catch-up (idempotent + monotonic CAS).
            self._projection.catch_up_projection(
                tenant,
                load_head=self._load_pg_head,
                load_revision=self._load_revision,
            )
            for event in batch:
                if event.event_type != "graph.revision.committed":
                    raise PersistenceError(f"unsupported outbox event_type {event.event_type!r}")
                self._record_checkpoint(event)
                processed += 1
            if len(batch) < self._batch_size:
                break
        return processed

    def process_once(self, tenant: TenantId) -> int:
        """Alias for ``process_tenant`` — one explicit invocation, no background loop."""
        return self.process_tenant(tenant)

    def _load_batch(self, tenant: TenantId) -> tuple[Any, ...]:
        with self._transactions.transaction() as connection:
            checkpoints = self._checkpoint_factory(connection)
            outbox = self._outbox_factory(connection)
            latest = checkpoints.latest(tenant.value)
            after = 0 if latest is None else latest.revision_number
            return outbox.list_for_tenant(tenant, after_revision=after, limit=self._batch_size)

    def _record_checkpoint(self, event: Any) -> None:
        with self._transactions.transaction() as connection:
            checkpoints = self._checkpoint_factory(connection)
            if checkpoints.exists(event.tenant.value, event.revision_number):
                return
            checkpoints.record(
                ProjectionCheckpoint(
                    tenant=event.tenant,
                    revision_number=event.revision_number,
                    event_id=event.event_id,
                    processed_at=self._clock(),
                )
            )

    def _load_pg_head(self, tenant: TenantId) -> tuple[int, str] | None:
        with self._transactions.transaction() as connection:
            head = self._revision_factory(connection).get_head(tenant)
            if head is None:
                return None
            return head.revision_number, head.content_hash

    def _load_revision(self, tenant: TenantId, revision_number: int) -> Any:
        with self._transactions.transaction() as connection:
            return self._revision_factory(connection).get_revision(tenant, revision_number)
