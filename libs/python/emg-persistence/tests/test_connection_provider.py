"""PostgreSQL connection acquisition and deterministic ownership (Task 2A)."""

from __future__ import annotations

from typing import Any, cast

import pytest
from emg_persistence import PersistenceSettings
from emg_persistence.postgres import ConnectionProvider, DirectConnectionProvider
from psycopg import Connection


class _FakeConnection:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _Factory:
    def __init__(self) -> None:
        self.settings: list[PersistenceSettings] = []
        self.connections: list[_FakeConnection] = []

    def __call__(self, settings: PersistenceSettings) -> Connection[Any]:
        connection = _FakeConnection()
        self.settings.append(settings)
        self.connections.append(connection)
        return cast(Connection[Any], connection)


def _settings() -> PersistenceSettings:
    return PersistenceSettings(postgres_dsn="postgresql://user@host/db")


def test_direct_provider_satisfies_connection_provider_protocol() -> None:
    assert isinstance(DirectConnectionProvider(_settings()), ConnectionProvider)


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
