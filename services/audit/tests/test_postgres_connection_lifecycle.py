"""RC-1C Phase A coverage for the Audit Service PostgreSQL lifecycle."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest
from emg_audit_client import AuditEventStore, AuditQuery
from emg_audit_pipeline import InMemoryAuditEventStore
from emg_audit_service import main as main_module
from emg_audit_service.authn import ServicePrincipal, require_service_principal
from emg_audit_service.config import Settings
from emg_audit_service.main import create_app
from emg_audit_service.store import (
    AuditStoreRuntime,
    _PooledOperations,
    close_store_runtime,
    store_dependency,
)
from fastapi.testclient import TestClient
from psycopg import Connection, OperationalError
from psycopg.pq import TransactionStatus


class _FakeConnection:
    def __init__(self, status: TransactionStatus = TransactionStatus.IDLE) -> None:
        self.closed = False
        self.info = SimpleNamespace(transaction_status=status)
        self.rollback_count = 0
        self.close_count = 0

    def rollback(self) -> None:
        self.rollback_count += 1
        self.info.transaction_status = TransactionStatus.IDLE

    def close(self) -> None:
        self.close_count += 1
        self.closed = True


class _FakePool:
    def __init__(self, connections: list[_FakeConnection] | None = None) -> None:
        self.connections = connections or [_FakeConnection()]
        self.get_timeouts: list[float | None] = []
        self.returned: list[_FakeConnection] = []
        self.open_calls: list[tuple[bool, float]] = []
        self.close_timeouts: list[float] = []
        self._index = 0

    def open(self, *, wait: bool = False, timeout: float = 30.0) -> None:
        self.open_calls.append((wait, timeout))

    def getconn(self, timeout: float | None = None) -> Connection[Any]:
        self.get_timeouts.append(timeout)
        index = min(self._index, len(self.connections) - 1)
        self._index += 1
        return cast(Connection[Any], self.connections[index])

    def putconn(self, connection: Connection[Any]) -> None:
        self.returned.append(cast(_FakeConnection, connection))

    def close(self, timeout: float = 5.0) -> None:
        self.close_timeouts.append(timeout)


class _TimeoutPool(_FakePool):
    def getconn(self, timeout: float | None = None) -> Connection[Any]:
        self.get_timeouts.append(timeout)
        raise TimeoutError("pool acquisition timed out")


def _settings(**overrides: object) -> Settings:
    return Settings(
        store_backend="postgres",
        postgres_dsn="postgresql://audit:test@postgres/audit",
        postgres_connect_timeout_seconds=3.0,
        postgres_pool_acquisition_timeout_seconds=1.5,
        postgres_statement_timeout_seconds=7.0,
        postgres_lock_timeout_seconds=2.0,
        postgres_pool_min_size=1,
        postgres_pool_max_size=4,
        postgres_reconnect_attempts=2,
        postgres_shutdown_timeout_seconds=4.0,
        **overrides,
    )


def _operations(pool: _FakePool, **overrides: object) -> _PooledOperations:
    return _PooledOperations(cast(Any, pool), _settings(**overrides))


def test_runtime_builds_closed_pool_with_bounded_connection_options() -> None:
    pool = _FakePool()
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> _FakePool:
        captured.update(kwargs)
        return pool

    AuditStoreRuntime(_settings(), pool_factory=cast(Any, factory))

    assert captured == {
        "conninfo": "postgresql://audit:test@postgres/audit",
        "kwargs": {
            "connect_timeout": 3,
            "options": "-c statement_timeout=7000 -c lock_timeout=2000",
        },
        "min_size": 1,
        "max_size": 4,
        "timeout": 1.5,
        "open": False,
    }


def test_runtime_startup_opens_pool_once_and_waits_for_connection() -> None:
    pool = _FakePool()
    runtime = AuditStoreRuntime(_settings(), pool_factory=cast(Any, lambda **_: pool))

    runtime.open()
    runtime.open()

    assert pool.open_calls == [(True, 3.0)]


def test_runtime_shutdown_closes_pool_once_with_deadline() -> None:
    pool = _FakePool()
    runtime = AuditStoreRuntime(_settings(), pool_factory=cast(Any, lambda **_: pool))

    runtime.open()
    runtime.close()
    runtime.close()

    assert pool.close_timeouts == [4.0]
    with pytest.raises(RuntimeError, match="pool is closed"):
        runtime.open()


def test_pool_acquisition_timeout_is_bounded_and_propagated() -> None:
    pool = _TimeoutPool()

    with pytest.raises(TimeoutError, match="acquisition timed out"):
        _operations(pool).run(lambda connection: connection)

    assert pool.get_timeouts == [1.5]


def test_operational_error_closes_connection_and_retries_with_replacement() -> None:
    failed = _FakeConnection()
    replacement = _FakeConnection()
    pool = _FakePool([failed, replacement])
    attempts = 0

    def operation(connection: Connection[Any]) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OperationalError("connection lost")
        assert connection is cast(Any, replacement)
        return "reconnected"

    assert _operations(pool).run(operation) == "reconnected"
    assert failed.closed
    assert failed.close_count == 1
    assert pool.returned == [failed, replacement]
    assert pool.get_timeouts == [1.5, 1.5]


def test_operational_retry_is_bounded() -> None:
    first = _FakeConnection()
    second = _FakeConnection()
    pool = _FakePool([first, second])

    with pytest.raises(OperationalError, match="still unavailable"):
        _operations(pool).run(
            lambda connection: (_ for _ in ()).throw(OperationalError("still unavailable"))
        )

    assert first.closed and second.closed
    assert len(pool.get_timeouts) == 2


def test_non_idle_connection_is_rolled_back_before_pool_return() -> None:
    connection = _FakeConnection(TransactionStatus.INTRANS)
    pool = _FakePool([connection])

    assert _operations(pool).run(lambda _: "done") == "done"

    assert connection.rollback_count == 1
    assert pool.returned == [connection]


def test_idle_connection_is_reused_across_operations() -> None:
    connection = _FakeConnection()
    pool = _FakePool([connection])
    operations = _operations(pool)

    assert operations.run(lambda current: current) is cast(Any, connection)
    assert operations.run(lambda current: current) is cast(Any, connection)

    assert pool.returned == [connection, connection]
    assert connection.rollback_count == 0


def test_fastapi_startup_and_shutdown_own_store_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Settings | None]] = []
    settings = Settings(store_backend="memory")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        main_module,
        "open_store_runtime",
        lambda current: calls.append(("open", current)),
    )
    monkeypatch.setattr(
        main_module,
        "close_store_runtime",
        lambda: calls.append(("close", None)),
    )

    with TestClient(create_app()):
        assert calls == [("open", settings)]

    assert calls == [("open", settings), ("close", None)]


def test_blocking_store_operation_runs_in_starlette_worker_thread() -> None:
    request_thread = threading.get_ident()
    operation_threads: list[int] = []
    store = InMemoryAuditEventStore()

    class RecordingStore:
        def append(self, *args: object, **kwargs: object) -> object:
            operation_threads.append(threading.get_ident())
            return store.append(*args, **kwargs)  # type: ignore[arg-type]

        def query(self, query: AuditQuery) -> list[object]:
            return cast(list[object], store.query(query))

        def verify_integrity(self) -> object:
            return store.verify_integrity()

    app = create_app()
    app.dependency_overrides[require_service_principal] = lambda: ServicePrincipal(
        client_id="emg-svc-audit",
        service_name="audit",
        roles=("service-account", "svc-audit"),
        tenant_id="tenant-a",
    )
    app.dependency_overrides[store_dependency] = lambda: cast(AuditEventStore, RecordingStore())
    payload = {
        "event_id": "threadpool-event",
        "actor": "svc",
        "actor_type": "service",
        "module": "test",
        "action": "verify",
        "outcome": "success",
        "source_system": "test",
    }

    with TestClient(app) as client:
        response = client.post("/audit/events", json=payload)

    assert response.status_code == 200
    assert len(operation_threads) == 1
    assert operation_threads[0] != request_thread


@pytest.fixture(autouse=True)
def _clear_runtime_registry() -> None:
    close_store_runtime()
    yield
    close_store_runtime()
