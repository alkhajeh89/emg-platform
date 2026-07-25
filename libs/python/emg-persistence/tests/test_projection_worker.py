"""Unit tests for ``ProjectionWorker`` (outbox + checkpoint driven catch-up),
using fake repositories/transactions instead of real PostgreSQL — closes the
coverage gap identified during the Outbox Event Persistence inspection
(38% coverage, effectively untested prior to this file).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from _outbox_helpers import make_outbox_event
from emg_persistence.errors import PersistenceError
from emg_persistence.outbox import OutboxEvent
from emg_persistence.projection.model import ProjectionCheckpoint
from emg_persistence.projection.worker import ProjectionWorker
from emg_persistence.revisions.in_memory import InMemoryRevisionRepository
from emg_persistence.revisions.model import Revision
from emg_platform_core import PrincipalRef, TenantId

TENANT = TenantId.of("acme")
PRINCIPAL = PrincipalRef.service("ingest")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


class _FakeTransactions:
    def __init__(self) -> None:
        self.calls = 0

    @contextmanager
    def transaction(self) -> Iterator[object]:
        self.calls += 1
        yield object()


class _FakeOutboxRepository:
    def __init__(self, events: list[OutboxEvent] | None = None) -> None:
        self._events = list(events) if events else []

    def append(self, event: OutboxEvent) -> None:
        self._events.append(event)

    def list_for_tenant(
        self, tenant: TenantId, *, after_revision: int = 0, limit: int = 100
    ) -> tuple[OutboxEvent, ...]:
        matching = sorted(
            (e for e in self._events if e.tenant == tenant and e.revision_number > after_revision),
            key=lambda e: e.revision_number,
        )
        return tuple(matching[:limit])


class _FakeCheckpointRepository:
    def __init__(self) -> None:
        self.checkpoints: dict[tuple[str, int], ProjectionCheckpoint] = {}
        self.record_calls = 0

    def exists(self, tenant_id: str, revision_number: int) -> bool:
        return (tenant_id, revision_number) in self.checkpoints

    def record(self, checkpoint: ProjectionCheckpoint) -> None:
        self.record_calls += 1
        self.checkpoints[(checkpoint.tenant.value, checkpoint.revision_number)] = checkpoint

    def latest(self, tenant_id: str) -> ProjectionCheckpoint | None:
        matching = [cp for (t, _r), cp in self.checkpoints.items() if t == tenant_id]
        if not matching:
            return None
        return max(matching, key=lambda cp: cp.revision_number)


class _FakeProjection:
    """Stub satisfying only the surface ``ProjectionWorker`` actually calls."""

    def __init__(self) -> None:
        self.catch_up_calls: list[TenantId] = []

    def catch_up_projection(self, tenant: TenantId, *, load_head: Any, load_revision: Any) -> int:
        self.catch_up_calls.append(tenant)
        return 0


def _worker(
    *,
    outbox: _FakeOutboxRepository,
    checkpoints: _FakeCheckpointRepository,
    revisions: InMemoryRevisionRepository,
    projection: _FakeProjection,
    batch_size: int = 100,
) -> ProjectionWorker:
    return ProjectionWorker(
        _FakeTransactions(),
        projection,  # type: ignore[arg-type]
        outbox_factory=lambda _conn: outbox,
        revision_factory=lambda _conn: revisions,
        checkpoint_factory=lambda _conn: checkpoints,
        batch_size=batch_size,
    )


def _event(revision_number: int, event_id: UUID | None = None) -> OutboxEvent:
    return make_outbox_event(
        event_id=event_id if event_id is not None else uuid4(),
        tenant=TENANT,
        revision_number=revision_number,
    )


def test_process_tenant_with_empty_outbox_does_nothing() -> None:
    outbox = _FakeOutboxRepository()
    checkpoints = _FakeCheckpointRepository()
    projection = _FakeProjection()
    worker = _worker(
        outbox=outbox,
        checkpoints=checkpoints,
        revisions=InMemoryRevisionRepository(),
        projection=projection,
    )

    processed = worker.process_tenant(TENANT)

    assert processed == 0
    assert projection.catch_up_calls == []
    assert checkpoints.checkpoints == {}


def test_process_tenant_processes_a_single_batch_and_records_checkpoints() -> None:
    outbox = _FakeOutboxRepository([_event(1), _event(2), _event(3)])
    checkpoints = _FakeCheckpointRepository()
    projection = _FakeProjection()
    worker = _worker(
        outbox=outbox,
        checkpoints=checkpoints,
        revisions=InMemoryRevisionRepository(),
        projection=projection,
    )

    processed = worker.process_tenant(TENANT)

    assert processed == 3
    assert projection.catch_up_calls == [TENANT]
    assert set(checkpoints.checkpoints) == {(TENANT.value, 1), (TENANT.value, 2), (TENANT.value, 3)}


def test_process_tenant_spans_multiple_batches() -> None:
    outbox = _FakeOutboxRepository([_event(1), _event(2), _event(3)])
    checkpoints = _FakeCheckpointRepository()
    projection = _FakeProjection()
    worker = _worker(
        outbox=outbox,
        checkpoints=checkpoints,
        revisions=InMemoryRevisionRepository(),
        projection=projection,
        batch_size=2,
    )

    processed = worker.process_tenant(TENANT)

    assert processed == 3
    # Batch 1: events 1-2 (full batch, loop continues). Batch 2: event 3
    # (partial batch, loop stops). catch_up_projection runs once per batch.
    assert projection.catch_up_calls == [TENANT, TENANT]


def test_process_tenant_is_idempotent_on_already_checkpointed_events() -> None:
    outbox = _FakeOutboxRepository([_event(1), _event(2)])
    checkpoints = _FakeCheckpointRepository()
    projection = _FakeProjection()
    worker = _worker(
        outbox=outbox,
        checkpoints=checkpoints,
        revisions=InMemoryRevisionRepository(),
        projection=projection,
    )

    first = worker.process_tenant(TENANT)
    assert first == 2
    assert checkpoints.record_calls == 2

    # Re-invocation: after_revision now comes from the latest checkpoint (2),
    # so list_for_tenant returns nothing new — no redundant work.
    second = worker.process_tenant(TENANT)
    assert second == 0
    assert checkpoints.record_calls == 2  # unchanged


class _RacyCheckpointRepository(_FakeCheckpointRepository):
    """Simulates a *different* worker instance winning a concurrent race:
    the checkpoint appears to exist the first time it's checked (after our
    own batch fetch already ran with an older ``after_revision`` cutoff),
    even though this repository never recorded it itself."""

    def __init__(self) -> None:
        super().__init__()
        self._first_check_is_a_race = True

    def exists(self, tenant_id: str, revision_number: int) -> bool:
        if self._first_check_is_a_race:
            self._first_check_is_a_race = False
            return True
        return super().exists(tenant_id, revision_number)


def test_process_tenant_skips_recording_a_checkpoint_won_by_a_concurrent_worker() -> None:
    """``_record_checkpoint``'s existence check exists precisely for two
    concurrent workers processing the same tenant's batch: whichever one
    loses the race must not re-record (idempotency, PHASE2_ARCHITECTURE.md
    ADR-6 refinement)."""
    outbox = _FakeOutboxRepository([_event(1)])
    checkpoints = _RacyCheckpointRepository()
    projection = _FakeProjection()
    worker = _worker(
        outbox=outbox,
        checkpoints=checkpoints,
        revisions=InMemoryRevisionRepository(),
        projection=projection,
    )

    processed = worker.process_tenant(TENANT)

    assert processed == 1  # still counted toward this run's batch...
    assert checkpoints.record_calls == 0  # ...but never re-recorded (another worker won)


def test_process_tenant_raises_on_unsupported_event_type() -> None:
    # OutboxEvent is frozen; model_copy produces the out-of-scope event type
    # (node/edge events are Phase 4, never emitted by real code today, but
    # the worker must still reject one defensively if it ever appears).
    bad_event = _event(1).model_copy(update={"event_type": "graph.node.created"})
    outbox = _FakeOutboxRepository([bad_event])
    checkpoints = _FakeCheckpointRepository()
    projection = _FakeProjection()
    worker = _worker(
        outbox=outbox,
        checkpoints=checkpoints,
        revisions=InMemoryRevisionRepository(),
        projection=projection,
    )

    with pytest.raises(PersistenceError, match="unsupported outbox event_type"):
        worker.process_tenant(TENANT)


def test_process_once_is_an_alias_for_process_tenant() -> None:
    outbox = _FakeOutboxRepository([_event(1)])
    checkpoints = _FakeCheckpointRepository()
    projection = _FakeProjection()
    worker = _worker(
        outbox=outbox,
        checkpoints=checkpoints,
        revisions=InMemoryRevisionRepository(),
        projection=projection,
    )

    assert worker.process_once(TENANT) == 1


def test_load_pg_head_delegates_to_revision_repository() -> None:
    revisions = InMemoryRevisionRepository()
    revision = Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash="a" * 64,
        principal=PRINCIPAL,
        node_count=0,
        edge_count=0,
        graph_json={"nodes": [], "edges": []},
        created_at=NOW,
    )
    revisions.create_first_revision(revision)
    worker = _worker(
        outbox=_FakeOutboxRepository(),
        checkpoints=_FakeCheckpointRepository(),
        revisions=revisions,
        projection=_FakeProjection(),
    )

    head = worker._load_pg_head(TENANT)

    assert head == (1, "a" * 64)


def test_load_pg_head_returns_none_for_a_tenant_with_no_revisions() -> None:
    worker = _worker(
        outbox=_FakeOutboxRepository(),
        checkpoints=_FakeCheckpointRepository(),
        revisions=InMemoryRevisionRepository(),
        projection=_FakeProjection(),
    )
    assert worker._load_pg_head(TENANT) is None


def test_load_revision_delegates_to_revision_repository() -> None:
    revisions = InMemoryRevisionRepository()
    revision = Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash="a" * 64,
        principal=PRINCIPAL,
        node_count=0,
        edge_count=0,
        graph_json={"nodes": [], "edges": []},
        created_at=NOW,
    )
    revisions.create_first_revision(revision)
    worker = _worker(
        outbox=_FakeOutboxRepository(),
        checkpoints=_FakeCheckpointRepository(),
        revisions=revisions,
        projection=_FakeProjection(),
    )

    assert worker._load_revision(TENANT, 1) == revision
    assert worker._load_revision(TENANT, 2) is None
