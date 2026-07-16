"""Store provider and store-health reporting for the audit service (Sprint 6).

The service owns exactly one append-only store, selected by configuration:

- `memory` — `InMemoryAuditEventStore` (tests / local without a database).
- `postgres` — `PostgresAuditEventStore` over the append-only `audit_events`
  table (INSERT/SELECT-only application role).

`store_health()` backs the readiness endpoint: a `postgres` store that cannot
reach the database reports `available=False`, so the audit degradation is
visible through health/readiness (Sprint 6 Decision C, service side). The
service never fabricates an audit record it did not durably persist.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from emg_audit_client import AuditEventStore, AuditQuery, CustodyEventStore
from emg_audit_pipeline import (
    InMemoryAuditEventStore,
    InMemoryCustodyEventStore,
    PostgresAuditEventStore,
    PostgresCustodyEventStore,
)
from fastapi import Depends

from .authn import SettingsDep
from .config import Settings


@dataclass(frozen=True)
class StoreHealth:
    backend: str
    available: bool
    detail: str


@lru_cache
def _memory_store_singleton() -> InMemoryAuditEventStore:
    return InMemoryAuditEventStore()


def _build_store(settings: Settings) -> AuditEventStore:
    if settings.store_backend == "postgres":
        import psycopg

        connection = psycopg.connect(settings.postgres_dsn)
        return PostgresAuditEventStore(connection)
    return _memory_store_singleton()


@lru_cache
def _store_singleton_for(backend: str, dsn: str) -> AuditEventStore:
    # Cache keyed by the config that determines the store, so the app reuses
    # one store/connection per configuration.
    from .config import Settings as _Settings

    return _build_store(_Settings(store_backend=backend, postgres_dsn=dsn))


def store_dependency(settings: SettingsDep) -> AuditEventStore:
    return _store_singleton_for(settings.store_backend, settings.postgres_dsn)


StoreDep = Annotated[AuditEventStore, Depends(store_dependency)]


# --- Chain-of-custody store (FEAT-04-3) — a separate ledger from the audit
# store, wired identically. It reuses the same PostgreSQL connection settings
# but is its own store object over its own table.


@lru_cache
def _memory_custody_store_singleton() -> InMemoryCustodyEventStore:
    return InMemoryCustodyEventStore()


def _build_custody_store(settings: Settings) -> CustodyEventStore:
    if settings.store_backend == "postgres":
        import psycopg

        connection = psycopg.connect(settings.postgres_dsn)
        return PostgresCustodyEventStore(connection)
    return _memory_custody_store_singleton()


@lru_cache
def _custody_store_singleton_for(backend: str, dsn: str) -> CustodyEventStore:
    from .config import Settings as _Settings

    return _build_custody_store(_Settings(store_backend=backend, postgres_dsn=dsn))


def custody_store_dependency(settings: SettingsDep) -> CustodyEventStore:
    return _custody_store_singleton_for(settings.store_backend, settings.postgres_dsn)


CustodyStoreDep = Annotated[CustodyEventStore, Depends(custody_store_dependency)]


def store_health(store: AuditEventStore, settings: Settings) -> StoreHealth:
    """Probe the store for readiness reporting. For the in-memory store this is
    always available; for Postgres it runs a cheap integrity/scan probe and
    reports unavailability rather than pretending to be healthy."""
    backend = settings.store_backend
    try:
        # A cheap read proves the store is reachable without mutating it or
        # scanning the whole table.
        store.query(AuditQuery(limit=1))
        return StoreHealth(backend=backend, available=True, detail="store reachable")
    except Exception as exc:  # pragma: no cover - exercised via readiness tests with a fake
        return StoreHealth(backend=backend, available=False, detail=f"store unavailable: {exc}")
