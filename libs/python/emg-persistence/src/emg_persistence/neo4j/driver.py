"""Neo4j driver helper (Phase 2, Sprint 2).

A thin factory that opens a Neo4j driver from ``PersistenceSettings``. Driver
creation/connection requires a live Neo4j, so it is integration-tested (CI
``persistence`` job) and marked ``# pragma: no cover`` here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import PersistenceSettings

if TYPE_CHECKING:
    from neo4j import Driver


def create_driver(settings: PersistenceSettings) -> Driver:  # pragma: no cover - requires a live DB
    """Create a Neo4j driver from the configured URI/credentials.

    Raises:
        ValueError: if ``settings.neo4j_uri`` is not configured.
    """
    if settings.neo4j_uri is None:
        raise ValueError("neo4j_uri is not configured")
    import neo4j

    auth = None
    if settings.neo4j_user is not None and settings.neo4j_password is not None:
        auth = (settings.neo4j_user, settings.neo4j_password.get_secret_value())
    return neo4j.GraphDatabase.driver(
        settings.neo4j_uri,
        auth=auth,
        max_connection_pool_size=settings.neo4j_max_pool_size,
    )
