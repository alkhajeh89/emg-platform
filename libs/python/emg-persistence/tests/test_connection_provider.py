"""PostgreSQL connection acquisition and deterministic ownership (Task 2A)."""

from __future__ import annotations

from typing import Any, cast

import pytest
from emg_persistence import PersistenceSettings
from emg_persistence.postgres import (
    ConnectionProvider,
    DirectConnectionProvider,
    PooledConnectionProvider,
)
from psycopg import Connection
from psycopg.pq import TransactionStatus


class _FakeConnection:
    def __init__(self, status: TransactionStatus = TransactionStatus.IDLE) -> None:
        self.close_calls = 0
        self.rollback_calls = 0
        self.events: list[str] = []
        self.info = _FakeConnectionInfo(status)

    def close(self) -> None:
        self.close_calls += 1
        self.events.append("close")

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.events.append("rollback")
        self.info.transaction_status = TransactionStatus.IDLE


class _FakeConnectionInfo:
    def __init__(self, status: TransactionStatus) -> None:
        self.transaction_status = status


class _Factory:
    def __init__(self) -> None:
        self.settings: list[PersistenceSettings] = []
        self.connections: list[_FakeConnection] = []

    def __call__(self, settings: PersistenceSettings) -> Connection[Any]:
        connection = _FakeConnection()
        self.settings.append(settings)
        self.connections.append(connection)
        return cast(Connection[Any], connection)


class _FakePool:
    def __init__(self, connection: _FakeConnection | None = None) -> None:
        self.connection = connection or _FakeConnection()
        self.open_calls: list[tuple[bool, float]] = []
        self.getconn_calls: list[float | None] = []
        self.putconn_calls: list[_FakeConnection] = []
        self.close_calls = 0

    def open(self, *, wait: bool = False, timeout: float = 30.0) -> None:
        self.open_calls.append((wait, timeout))

    def getconn(self, timeout: float | None = None) -> Connection[Any]:
        self.getconn_calls.append(timeout)
        return cast(Connection[Any], self.connection)

    def putconn(self, connection: Connection[Any]) -> None:
        returned = cast(_FakeConnection, connection)
        returned.events.append("putconn")
        self.putconn_calls.append(returned)

    def close(self, timeout: float = 5.0) -> None:
        self.close_calls += 1


class _PoolFactory:
    def __init__(self, pool: _FakePool | None = None) -> None:
        self.pool = pool or _FakePool()
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> _FakePool:
        self.calls.append(kwargs)
        return self.pool


def _settings() -> PersistenceSettings:
    return PersistenceSettings(postgres_dsn="postgresql://user@host/db")


def test_direct_provider_satisfies_connection_provider_protocol() -> None:
    assert isinstance(DirectConnectionProvider(_settings()), ConnectionProvider)


def test_pooled_provider_satisfies_connection_provider_protocol() -> None:
    assert isinstance(PooledConnectionProvider(_settings()), ConnectionProvider)


def test_acquire_passes_settings_and_closes_on_success() -> None:
    settings = _settings()
    factory = _Factory()
    provider = DirectConnectionProvider(settings, connection_factory=factory)

    with provider.acquire() as acquired:
        assert acquired is factory.connections[0]
        assert factory.settings == [settings]
        assert factory.connections[0].close_calls == 0

    assert factory.connections[0].close_calls == 1


def test_acquire_closes_when_caller_raises() -> None:
    factory = _Factory()
    provider = DirectConnectionProvider(_settings(), connection_factory=factory)

    with pytest.raises(RuntimeError, match="caller failed"), provider.acquire():
        raise RuntimeError("caller failed")

    assert factory.connections[0].close_calls == 1


def test_each_acquisition_has_independent_ownership() -> None:
    factory = _Factory()
    provider = DirectConnectionProvider(_settings(), connection_factory=factory)

    with provider.acquire() as first:
        assert factory.connections[0].close_calls == 0
    with provider.acquire() as second:
        assert factory.connections[1].close_calls == 0

    assert first is not second
    assert [connection.close_calls for connection in factory.connections] == [1, 1]


def test_connection_failure_is_propagated_without_cleanup_attempt() -> None:
    settings = _settings()

    def fail(_settings: PersistenceSettings) -> Connection[Any]:
        raise OSError("cannot connect")

    provider = DirectConnectionProvider(settings, connection_factory=fail)
    with pytest.raises(OSError, match="cannot connect"), provider.acquire():
        pytest.fail("acquisition unexpectedly succeeded")


@pytest.mark.parametrize(
    ("connect_timeout_seconds", "expected_libpq_timeout"),
    [(3.5, 4), (0.1, 1)],
)
def test_pooled_provider_is_lazy_and_passes_bounded_settings_on_first_acquire(
    connect_timeout_seconds: float,
    expected_libpq_timeout: int,
) -> None:
    settings = PersistenceSettings(
        postgres_dsn="postgresql://user@host/db",
        postgres_pool_min_size=2,
        postgres_pool_max_size=7,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    factory = _PoolFactory()
    provider = PooledConnectionProvider(settings, pool_factory=factory)

    assert factory.calls == []

    with provider.acquire() as acquired:
        assert acquired is factory.pool.connection

    assert factory.calls == [
        {
            "conninfo": settings.postgres_dsn,
            "kwargs": {"connect_timeout": expected_libpq_timeout},
            "min_size": 2,
            "max_size": 7,
            "timeout": connect_timeout_seconds,
            "open": False,
        }
    ]
    assert factory.pool.open_calls == [(False, 30.0)]
    assert factory.pool.getconn_calls == [connect_timeout_seconds]
    assert factory.pool.putconn_calls == [factory.pool.connection]


def test_pooled_provider_returns_connection_when_caller_raises() -> None:
    factory = _PoolFactory()
    provider = PooledConnectionProvider(_settings(), pool_factory=factory)

    with pytest.raises(RuntimeError, match="caller failed"), provider.acquire():
        raise RuntimeError("caller failed")

    assert factory.pool.putconn_calls == [factory.pool.connection]


@pytest.mark.parametrize("status", [TransactionStatus.INTRANS, TransactionStatus.INERROR])
def test_pooled_provider_rolls_back_open_or_failed_transaction_before_return(
    status: TransactionStatus,
) -> None:
    connection = _FakeConnection(status)
    factory = _PoolFactory(_FakePool(connection))
    provider = PooledConnectionProvider(_settings(), pool_factory=factory)

    with provider.acquire():
        pass

    assert connection.rollback_calls == 1
    assert connection.events == ["rollback", "putconn"]


def test_pooled_provider_does_not_rollback_idle_connection() -> None:
    connection = _FakeConnection()
    factory = _PoolFactory(_FakePool(connection))
    provider = PooledConnectionProvider(_settings(), pool_factory=factory)

    with provider.acquire():
        pass

    assert connection.rollback_calls == 0
    assert connection.events == ["putconn"]


def test_pooled_provider_closes_connection_when_reset_fails() -> None:
    connection = _FakeConnection(TransactionStatus.INERROR)

    def fail_rollback() -> None:
        connection.events.append("rollback")
        raise RuntimeError("reset failed")

    connection.rollback = fail_rollback  # type: ignore[method-assign]
    factory = _PoolFactory(_FakePool(connection))
    provider = PooledConnectionProvider(_settings(), pool_factory=factory)

    with provider.acquire():
        pass

    assert connection.events == ["rollback", "close", "putconn"]
    assert connection.close_calls == 1


def test_pooled_provider_close_is_lazy_and_idempotent() -> None:
    unopened_factory = _PoolFactory()
    unopened = PooledConnectionProvider(_settings(), pool_factory=unopened_factory)

    unopened.close()
    unopened.close()

    assert unopened_factory.calls == []
    with pytest.raises(RuntimeError, match="pool is closed"), unopened.acquire():
        pytest.fail("closed pool unexpectedly acquired a connection")

    opened_factory = _PoolFactory()
    opened = PooledConnectionProvider(_settings(), pool_factory=opened_factory)
    with opened.acquire():
        pass

    opened.close()
    opened.close()

    assert opened_factory.pool.close_calls == 1
