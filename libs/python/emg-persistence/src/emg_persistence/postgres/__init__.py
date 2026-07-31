"""PostgreSQL backend for emg-persistence (Phase 2).

Sprint 2 delivers the PostgreSQL **migration** executor + connection helper only.
The authoritative revision/head/outbox repositories and the GraphStore write path
arrive in later sprints.
"""

from __future__ import annotations

from .checkpoint_repository import PostgresProjectionCheckpointRepository
from .migration_executor import PostgresMigrationExecutor
from .mutation_repository import PostgresMutationRepository
from .outbox_repository import PostgresOutboxRepository
from .pool import ConnectionProvider, DirectConnectionProvider, connect
from .revision_repository import PostgresRevisionRepository
from .transactions import (
    ContextBoundTransactionProvider,
    PostgresTransactionProvider,
    TransactionProvider,
)

__all__ = [
    "ConnectionProvider",
    "ContextBoundTransactionProvider",
    "DirectConnectionProvider",
    "PostgresMigrationExecutor",
    "PostgresMutationRepository",
    "PostgresOutboxRepository",
    "PostgresProjectionCheckpointRepository",
    "PostgresRevisionRepository",
    "PostgresTransactionProvider",
    "TransactionProvider",
    "connect",
]
