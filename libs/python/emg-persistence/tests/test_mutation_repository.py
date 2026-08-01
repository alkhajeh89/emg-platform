"""Focused unit coverage for ADR-030 mutation-dispatch claims."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Any, cast

import pytest
from emg_persistence.postgres import PostgresMutationRepository
from psycopg import Connection


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: tuple[str, dict[str, object]] | None = None

    def execute(self, query: str, params: dict[str, object]) -> None:
        self.executed = (query, params)

    def fetchall(self) -> list[tuple[object, ...]]:
        return []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_calls = 0
        self.cursor_instance = _FakeCursor()

    def cursor(self) -> AbstractContextManager[_FakeCursor]:
        self.cursor_calls += 1
        return self.cursor_instance


def _repository(connection: _FakeConnection) -> PostgresMutationRepository:
    return PostgresMutationRepository(cast(Connection[Any], connection))


@pytest.mark.parametrize("max_attempts", [0, -1])
def test_claim_dispatch_rejects_non_positive_max_attempts_before_database_execution(
    max_attempts: int,
) -> None:
    connection = _FakeConnection()

    with pytest.raises(ValueError, match="dispatch max_attempts must be positive"):
        _repository(connection).claim_dispatch(
            tenant_id="tenant-a",
            channel="audit",
            worker="worker-a",
            limit=1,
            max_attempts=max_attempts,
            lease=timedelta(seconds=30),
        )

    assert connection.cursor_calls == 0


def test_claim_dispatch_passes_bound_to_atomic_skip_locked_query() -> None:
    connection = _FakeConnection()

    assert (
        _repository(connection).claim_dispatch(
            tenant_id="tenant-a",
            channel="event",
            worker="worker-a",
            limit=4,
            max_attempts=7,
            lease=timedelta(seconds=30),
        )
        == ()
    )

    assert connection.cursor_instance.executed is not None
    query, params = connection.cursor_instance.executed
    assert "attempt_count < %(max_attempts)s" in query
    assert "FOR UPDATE SKIP LOCKED" in query
    assert "attempt_count = dispatch.attempt_count + 1" in query
    assert params == {
        "channel": "event",
        "tenant": "tenant-a",
        "worker": "worker-a",
        "limit": 4,
        "max_attempts": 7,
        "lease": timedelta(seconds=30),
    }
