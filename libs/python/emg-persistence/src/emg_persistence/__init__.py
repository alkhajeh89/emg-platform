"""emg-persistence — EMG Persistence Binding (Phase 2).

Durable ``GraphStore`` adapters behind the unchanged Phase 1 ``GraphStore`` port.
PostgreSQL is the authoritative revision log; Neo4j is a rebuildable serving
projection (never on the write path). Conforms to PHASE2_ARCHITECTURE.md
Revision 3 (ADR-1..ADR-6).

Sprint 1 exposes only the configuration model, the dependency-injection factory,
and the error hierarchy; the persistent backend is delivered in later sprints.
"""

from __future__ import annotations

from .config import PersistenceSettings
from .errors import PersistenceConflictError, PersistenceError, ProjectionLagError
from .factory import build_graph_store

__version__ = "0.1.0"

__all__ = [
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceSettings",
    "ProjectionLagError",
    "build_graph_store",
    "__version__",
]
