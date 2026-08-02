"""Live PostgreSQL coverage for bounded pooled connection ownership."""

from __future__ import annotations

import os

import pytest
from emg_persistence import PersistenceSettings
from emg_persistence.postgres import PooledConnectionProvider
from psycopg.errors import DivisionByZero
from psycopg.pq import TransactionStatus
from psycopg_pool import PoolTimeout

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not _PG_DSN,
    reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN",
)


def _provider(*, timeout: float = 1.0) -> PooledConnectionProvider:
    return PooledConnectionProvider(
        PersistenceSettings(
            postgres_dsn=_PG_DSN,
            postgres_pool_min_size=0,
            postgres_pool_max_size=1,
            connect_timeout_seconds=timeout,
        )
    )


def test_pool_reuses_returned_connection_and_resets_open_transaction() -> None:
    provider = _provider()
    try:
        with provider.acquire() as first:
            with first.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                first_pid = cursor.fetchone()[0]
            assert first.info.transaction_status is TransactionStatus.INTRANS

        with provider.acquire() as second:
            assert second.info.transaction_status is TransactionStatus.IDLE
            with second.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                second_pid = cursor.fetchone()[0]

        assert second_pid == first_pid
    finally:
        provider.close()


def test_pool_resets_failed_transaction_before_reuse() -> None:
    provider = _provider()
    try:
        with provider.acquire() as first:
            with first.cursor() as cursor, pytest.raises(DivisionByZero):
                cursor.execute("SELECT 1 / 0")
            first_pid = first.info.backend_pid
            assert first.info.transaction_status is TransactionStatus.INERROR

        with provider.acquire() as second:
            assert second.info.transaction_status is TransactionStatus.IDLE
            assert second.info.backend_pid == first_pid
            with second.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
    finally:
        provider.close()


def test_pool_exhaustion_uses_configured_acquisition_timeout() -> None:
    provider = _provider(timeout=0.1)
    try:
        with provider.acquire(), pytest.raises(PoolTimeout), provider.acquire():
            pytest.fail("exhausted pool unexpectedly acquired a connection")
    finally:
        provider.close()
