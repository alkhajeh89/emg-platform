"""PostgreSQL connection helper (Phase 2, Sprint 2).

A thin factory that opens a psycopg connection from ``PersistenceSettings``.
Connection establishment requires a live database, so it is integration-tested
(CI ``persistence`` job) and marked ``# pragma: no cover`` here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import PersistenceSettings

if TYPE_CHECKING:
    from psycopg import Connection


def connect(settings: PersistenceSettings) -> Connection[Any]:  # pragma: no cover - live DB
    """Open a psycopg connection to the configured PostgreSQL DSN.

    Raises:
        ValueError: if ``settings.postgres_dsn`` is not configured.
    """
    if settings.postgres_dsn is None:
        raise ValueError("postgres_dsn is not configured")
    import psycopg

    return psycopg.connect(
        settings.postgres_dsn,
        connect_timeout=int(settings.connect_timeout_seconds),
    )
