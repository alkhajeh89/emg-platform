"""Persistent GraphStore tenant enumeration tests (Task 4B)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import pytest
from emg_persistence import PersistenceError
from emg_persistence.revisions import RevisionRepository
from emg_persistence.store import PostgresNeo4jGraphStore
from emg_platform_core import TenantId
from psycopg import Connection, OperationalError


class _Transactions:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.calls = 0

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        self.calls += 1
        self._events.append("begin")
        try:
            yield cast(Connection[Any], object())
        except BaseException:
            self._events.append("rollback")
            raise
        else:
            self._events.append("commit")
        finally:
            self._events.append("close")


class _Repository:
    def __init__(
        self,
        events: list[str],
        tenants: tuple[TenantId, ...] = (),
        *,
        failure: BaseException | None = None,
    ) -> None:
        self._events = events
        self._tenants = tenants
        self._failure = failure
        self.calls = 0

    def tenants(self) -> tuple[TenantId, ...]:
        self.calls += 1
        self._events.append("tenants")
        if self._failure is not None:
            raise self._failure
        return self._tenants


def _store(
    repository: _Repository, events: list[str]
) -> tuple[PostgresNeo4jGraphStore, _Transactions]:
    transactions = _Transactions(events)

    def repository_factory(_connection: Connection[Any]) -> RevisionRepository:
        return cast(RevisionRepository, repository)

    return (
        PostgresNeo4jGraphStore(
            transactions,
            repository_factory=repository_factory,
        ),
        transactions,
    )


def test_empty_repository_returns_no_tenants() -> None:
    events: list[str] = []
    repository = _Repository(events)
    store, transactions = _store(repository, events)

    assert store.tenants() == ()
    assert repository.calls == 1
    assert transactions.calls == 1
    assert events == ["begin", "tenants", "commit", "close"]


def test_multiple_tenants_are_returned_directly_in_repository_order() -> None:
    events: list[str] = []
    expected = (TenantId.of("alpha"), TenantId.of("bravo"), TenantId.of("zulu"))
    repository = _Repository(events, expected)
    store, _ = _store(repository, events)

    assert store.tenants() == expected
    assert events == ["begin", "tenants", "commit", "close"]


def test_sorted_results_are_preserved_without_reconstruction() -> None:
    events: list[str] = []
    expected = (TenantId.of("alpha"), TenantId.of("zulu"))
    repository = _Repository(events, expected)
    store, _ = _store(repository, events)

    result = store.tenants()

    assert result == tuple(sorted(result, key=lambda tenant: tenant.value))
    assert repository.calls == 1
    assert events.count("tenants") == 1


def test_repository_driver_failure_is_translated_and_rolls_back() -> None:
    events: list[str] = []
    repository = _Repository(
        events,
        failure=OperationalError("database unavailable"),
    )
    store, _ = _store(repository, events)

    with pytest.raises(PersistenceError, match="failed to list") as caught:
        store.tenants()

    assert isinstance(caught.value.__cause__, OperationalError)
    assert events == ["begin", "tenants", "rollback", "close"]
