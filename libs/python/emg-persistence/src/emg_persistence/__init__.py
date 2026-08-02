"""emg-persistence — EMG Persistence Binding (Phase 2).

Durable ``GraphStore`` adapters behind the unchanged Phase 1 ``GraphStore`` port.
PostgreSQL is the authoritative revision log; Neo4j is a rebuildable serving
projection (never on the write path). Conforms to PHASE2_ARCHITECTURE.md
Revision 3 (ADR-1..ADR-6).

The package exports its configuration, dependency-injection factory, typed
errors, and concrete persistent GraphStore adapter.
"""

from __future__ import annotations

from .config import PersistenceSettings
from .errors import (
    EvidenceLedgerIntegrityError,
    PersistenceConflictError,
    PersistenceError,
    ProjectionLagError,
)
from .factory import build_graph_store
from .store import PostgresNeo4jGraphStore

__version__ = "0.1.0"

__all__ = [
    "EvidenceLedgerIntegrityError",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceSettings",
    "PostgresNeo4jGraphStore",
    "ProjectionLagError",
    "build_graph_store",
    "__version__",
]
