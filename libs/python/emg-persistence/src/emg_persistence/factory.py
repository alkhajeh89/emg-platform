"""Dependency-injection factory for the ``GraphStore`` (Phase 2, Sprint 1).

``build_graph_store`` is the single seam through which services obtain a
``GraphStore`` (the unchanged Phase 1 port). Selection is driven by
configuration, so callers depend on the *interface* and never construct a
concrete store directly.

Sprint 1 wires only the in-memory backend:

* **No persistence configured** (no ``postgres_dsn``) → the deterministic
  Phase 1 ``InMemoryGraphStore`` (dev/tests).
* **Persistence configured** → the persistent ``PostgresNeo4jGraphStore`` is not
  part of this build (it is delivered in later Phase 2 sprints), so a
  ``PersistenceError`` is raised rather than silently returning an in-memory
  store when durability was requested — a silent fallback would be an unsafe
  data-loss footgun.
"""

from __future__ import annotations

from emg_platform_core import GraphStore, InMemoryGraphStore

from .config import PersistenceSettings
from .errors import PersistenceError


def build_graph_store(settings: PersistenceSettings | None = None) -> GraphStore:
    """Return a ``GraphStore`` selected from ``settings``.

    Args:
        settings: persistence configuration. If ``None``, a default
            ``PersistenceSettings()`` is used (in-memory mode unless the
            environment configures a datastore).

    Returns:
        A ``GraphStore``: the in-memory adapter when persistence is not
        configured.

    Raises:
        PersistenceError: when a persistent datastore is configured but the
            persistent backend is not available in this build (delivered in a
            later Phase 2 sprint).
    """
    settings = settings if settings is not None else PersistenceSettings()
    if settings.is_persistence_configured:
        raise PersistenceError(
            "A persistent datastore is configured (postgres_dsn is set), but the "
            "persistent GraphStore backend is not available in this build; it is "
            "delivered in a later Phase 2 sprint. Unset the datastore DSN to use "
            "the in-memory store, or install a build that includes the persistent "
            "backend."
        )
    return InMemoryGraphStore()
