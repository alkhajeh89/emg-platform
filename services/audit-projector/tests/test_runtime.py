from __future__ import annotations

from contextlib import contextmanager
from threading import Event
from typing import Any

from audit_projector_helpers import settings
from emg_audit_projector import runtime


class _Cursor:
    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        assert statement == "SELECT 1"

    def fetchone(self) -> tuple[int]:
        return (1,)


class _Connection:
    def cursor(self) -> _Cursor:
        return _Cursor()


class _Transactions:
    def __init__(self, connections: object) -> None:
        del connections

    @contextmanager
    def transaction(self):
        yield _Connection()


class _Connections:
    instances: list[_Connections] = []

    def __init__(self, persistence: object) -> None:
        del persistence
        self.closed = False
        self.instances.append(self)

    def close(self) -> None:
        self.closed = True


class _Delivery:
    instances: list[_Delivery] = []

    def __init__(self, configured: object) -> None:
        del configured
        self.closed = False
        self.instances.append(self)

    def close(self) -> None:
        self.closed = True


class _Worker:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.stopped = Event()

    def run(self) -> None:
        self.stopped.wait()

    def stop(self) -> None:
        self.stopped.set()


def test_runtime_starts_probes_drains_and_closes(monkeypatch: Any) -> None:
    monkeypatch.setattr(runtime, "PooledConnectionProvider", _Connections)
    monkeypatch.setattr(runtime, "PostgresTransactionProvider", _Transactions)
    monkeypatch.setattr(runtime, "AuditDeliveryClient", _Delivery)
    monkeypatch.setattr(runtime, "AuditProjectorWorker", _Worker)
    instance = runtime.ProjectorRuntime(settings())

    instance.start()
    assert instance.stop() is True
    instance.close()

    assert _Connections.instances[-1].closed is True
    assert _Delivery.instances[-1].closed is True
