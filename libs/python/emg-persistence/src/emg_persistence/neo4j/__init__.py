"""Neo4j backend for emg-persistence (Phase 2).

Sprint 2 delivers the Neo4j **migration** executor only (schema constraints via
idempotent Cypher). Neo4j is a serving projection (ADR-1) and is never on the
write path; the projection logic itself arrives in a later sprint.
"""

from __future__ import annotations

from .driver import create_driver
from .migration_executor import Neo4jMigrationExecutor, split_cypher_statements

__all__ = ["Neo4jMigrationExecutor", "create_driver", "split_cypher_statements"]
