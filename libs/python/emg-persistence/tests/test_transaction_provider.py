"""Explicit PostgreSQL transaction ownership and cleanup (Task 2B)."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Any, cast

import pytest
from emg_persistence.postgres import (
    ContextBoundTransactionProvider,
    PostgresTransactionProvider,
    TransactionProvider,
)
from psycopg import Connection


class _FakeTransaction:
    def __init__(self, events: list[str], *, fail_commit: bool = False) -> None:
        self._events = events
        self._fail_commit = fail_commit

    def __enter__(self) -> None:
        self._events.append("begin")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if exc_type is not None:
            self._events.append("rollback")
            return False
        self._events.append("commit")
        if self._fail_commit:
            raise RuntimeError("commit failed")
        return False


class _FakeConnection:
    def __init__(self, events: list[str], *, fail_commit: bool = False) -> None:
        self._events = events
        self._fail_commit = fail_commit
        self.transaction_calls = 0

    def transaction(self) -> _FakeTransaction:
        self.transaction_calls += 1
        return _FakeTransaction(self._events, fail_commit=self._fail_commit)


class _FakeConnectionProvider:
    def __init__(self, events: list[str], *, fail_commit: bool = False) -> None:
        self._events = events
        self._fail_commit = fail_commit
        self.acquire_calls = 0
        self.connections: list[_FakeConnection] = []

    @contextmanager
    def acquire(self) -> Any:
        self.acquire_calls += 1
        connection = _FakeConnection(self._events, fail_commit=self._fail_commit)
        self.connections.append(connection)
        self._events.append("acquire")
        try:
            yield cast(Connection[Any], connection)
        finally:
            self._events.append("close")


def _provider(
    events: list[str], *, fail_commit: bool = False
) -> tuple[PostgresTransactionProvider, _FakeConnectionProvider]:
    connections = _FakeConnectionProvider(events, fail_commit=fail_commit)
    provider = PostgresTransactionProvider(connections)
    return provider, connections


def test_satisfies_transaction_provider_protocol() -> None:
    provider, _ = _provider([])
    assert isinstance(provider, TransactionProvider)


def test_success_commits_before_connection_cleanup() -> None:
    events: list[str] = []
    provider, connections = _provider(events)

    with provider.transaction() as connection:
        events.append("body")
        assert connection is connections.connections[0]

    assert events == ["acquire", "begin", "body", "commit", "close"]
    assert connections.acquire_calls == 1
    assert connections.connections[0].transaction_calls == 1


def test_exception_rolls_back_before_connection_cleanup() -> None:
    events: list[str] = []
    provider, connections = _provider(events)

    with pytest.raises(ValueError, match="write failed"), provider.transaction():
        events.append("body")
        raise ValueError("write failed")

    assert events == ["acquire", "begin", "body", "rollback", "close"]
    assert connections.acquire_calls == 1


def test_commit_failure_propagates_and_connection_is_cleaned_up() -> None:
    events: list[str] = []
    provider, connections = _provider(events, fail_commit=True)

    with pytest.raises(RuntimeError, match="commit failed"), provider.transaction():
        events.append("body")

    assert events == ["acquire", "begin", "body", "commit", "close"]
    assert connections.acquire_calls == 1


def test_each_transaction_acquires_exactly_one_fresh_connection() -> None:
    events: list[str] = []
    provider, connections = _provider(events)

    with provider.transaction() as first:
        pass
    with provider.transaction() as second:
        pass

    assert first is not second
    assert connections.acquire_calls == 2
    assert len(connections.connections) == 2
    assert all(connection.transaction_calls == 1 for connection in connections.connections)


def test_transaction_is_an_abstract_context_manager() -> None:
    provider, _ = _provider([])
    assert isinstance(provider.transaction(), AbstractContextManager)


def test_context_bound_provider_reuses_outer_connection_with_savepoint() -> None:
    events: list[str] = []
    connections = _FakeConnectionProvider(events)
    provider = ContextBoundTransactionProvider(connections)

    with provider.outer_transaction() as outer:
        events.append("outer-body")
        with provider.transaction() as joined:
            events.append("joined-body")
            assert joined is outer

    assert events == [
        "acquire",
        "begin",
        "outer-body",
        "begin",
        "joined-body",
        "commit",
        "commit",
        "close",
    ]
    assert connections.acquire_calls == 1


def test_context_bound_provider_rolls_back_outer_after_nested_failure() -> None:
    events: list[str] = []
    connections = _FakeConnectionProvider(events)
    provider = ContextBoundTransactionProvider(connections)

    with pytest.raises(RuntimeError, match="injected"), provider.outer_transaction():
        with provider.transaction():
            events.append("graph-write")
        events.append("ledger-write")
        raise RuntimeError("injected")

    assert events == [
        "acquire",
        "begin",
        "begin",
        "graph-write",
        "commit",
        "ledger-write",
        "rollback",
        "close",
    ]
    assert connections.acquire_calls == 1
