"""PostgreSQL backend for emg-persistence (Phase 2).

Sprint 2 delivers the PostgreSQL **migration** executor + connection helper only.
The authoritative revision/head/outbox repositories and the GraphStore write path
arrive in later sprints.
"""

from __future__ import annotations

from .migration_executor import PostgresMigrationExecutor
from .pool import connect

__all__ = ["PostgresMigrationExecutor", "connect"]
