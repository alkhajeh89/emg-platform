"""Startup migration wiring for the Knowledge Graph service (Knowledge Graph
Integration Closure, Group B4).

Runs the existing, reusable `emg_persistence` PostgreSQL migration machinery
(`emg_persistence.migrate.run_migrations` + `PostgresMigrationExecutor`)
against this service's configured database before the ASGI app starts
serving traffic, so `V001__baseline.sql` and `V002__projection_checkpoints.sql`
are applied automatically instead of requiring an undocumented manual step.
This module introduces no new migration logic -- it only wires the service to
infrastructure that already exists and is already used elsewhere in the repo.

Scope: PostgreSQL only. The Neo4j migration (`M001__constraints.cypher`) is
explicitly out of scope here -- this service's Neo4j serving-projection
binding is deliberately left unwired (see `store.py`'s module docstring;
ADR-024 §19), and wiring it is a separate, not-yet-scheduled work item
(Knowledge Graph Integration Closure implementation specification, Groups
C-F). Applying a Neo4j migration for a projection this service does not yet
read from would be a new capability, which this sprint's requirements
forbid.

Invoked as a standalone entrypoint (`python -m emg_knowledge_graph_api.migrate`)
from the Dockerfile's `CMD`, once, before `uvicorn` starts. It is not part of
the FastAPI app object and does not run per-request or per-worker.

A no-op, by design, when `store_backend != "postgres"` (e.g. local
development or tests running against the in-memory store) -- there is
nothing to migrate in that configuration.
"""

from __future__ import annotations

import logging

from emg_persistence.config import PersistenceSettings
from emg_persistence.migrate import run_migrations
from emg_persistence.postgres.migration_executor import PostgresMigrationExecutor
from emg_persistence.postgres.pool import DirectConnectionProvider

from .config import get_settings, validate_migration_configuration

logger = logging.getLogger(__name__)


def run_startup_migrations() -> None:
    """Apply any pending PostgreSQL migrations for the configured database.

    Safe to call unconditionally at process startup: it is a no-op unless
    `store_backend == "postgres"`.
    """
    settings = get_settings()
    validate_migration_configuration(settings)
    if settings.store_backend != "postgres":
        logger.info(
            "knowledge-graph: store_backend=%r, skipping startup migrations "
            "(migration wiring is PostgreSQL-only)",
            settings.store_backend,
        )
        return

    persistence_settings = PersistenceSettings(
        postgres_dsn=settings.migration_postgres_dsn,
        connect_timeout_seconds=settings.postgres_connect_timeout_seconds,
    )
    connections = DirectConnectionProvider(persistence_settings)
    with connections.acquire() as connection:
        executor = PostgresMigrationExecutor(connection)
        applied = run_migrations(executor)

    if applied:
        logger.info(
            "knowledge-graph: applied %d migration(s): %s",
            len(applied),
            ", ".join(f"V{m.version}__{m.name}" for m in applied),
        )
    else:
        logger.info("knowledge-graph: no pending migrations; database already up to date")


if __name__ == "__main__":  # pragma: no cover - process entrypoint, exercised via Dockerfile CMD
    logging.basicConfig(level=logging.INFO)
    run_startup_migrations()
