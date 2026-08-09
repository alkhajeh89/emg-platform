"""Lifecycle composition for the dedicated headless projector workload."""

from __future__ import annotations

from pathlib import Path
from threading import Thread

from emg_persistence import PersistenceSettings
from emg_persistence.postgres import (
    PooledConnectionProvider,
    PostgresTransactionProvider,
)

from .config import Settings, validate_runtime_configuration
from .delivery import AuditDeliveryClient
from .worker import AuditProjectorWorker


class ProjectorRuntime:
    def __init__(self, settings: Settings) -> None:
        validate_runtime_configuration(settings)
        persistence = PersistenceSettings(
            postgres_dsn=settings.postgres_dsn,
            connect_timeout_seconds=settings.postgres_connect_timeout_seconds,
            postgres_pool_min_size=settings.postgres_pool_min_size,
            postgres_pool_max_size=settings.postgres_pool_max_size,
        )
        self._connections = PooledConnectionProvider(persistence)
        self._transactions = PostgresTransactionProvider(self._connections)
        self._delivery = AuditDeliveryClient(settings)
        self.worker = AuditProjectorWorker(settings, self._transactions, self._delivery)
        self._thread: Thread | None = None
        self._drain_timeout = settings.drain_timeout_seconds
        self._ready_path = Path("/tmp/emg-audit-projector-ready")

    def start(self) -> None:
        # Fail startup before claiming if PostgreSQL is unreachable.
        with self._transactions.transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("Audit Projector PostgreSQL startup probe failed")
        thread = Thread(target=self.worker.run, name="audit-projector", daemon=True)
        thread.start()
        self._thread = thread
        self._ready_path.touch(mode=0o600, exist_ok=True)

    def wait(self) -> None:
        thread = self._thread
        if thread is None:
            raise RuntimeError("Audit Projector runtime has not started")
        while thread.is_alive():
            thread.join(timeout=0.5)

    def stop(self) -> bool:
        self.worker.stop()
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=self._drain_timeout)
        return not thread.is_alive()

    def close(self) -> None:
        self._ready_path.unlink(missing_ok=True)
        self._delivery.close()
        self._connections.close()
