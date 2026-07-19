"""Dependency-injection factory for the ``GraphStore`` (Phase 2, Sprint 1).

``build_graph_store`` is the single seam through which services obtain a
``GraphStore`` (the unchanged Phase 1 port). Selection is driven by
configuration, so callers depend on the *interface* and never construct a
concrete store directly.

Sprint 1 is a **scaffolding** sprint: it establishes *structure*, not final
runtime behavior. Accordingly:

* **No persistence configured** (no ``postgres_dsn``) → the deterministic
  Phase 1 ``InMemoryGraphStore`` (dev/tests).
* **Persistence configured** → construction is delegated to the internal
  placeholder :func:`_build_persistent_store`, which is **not implemented yet**
  and raises ``NotImplementedError``. This is a passive placeholder seam, not a
  persistence *policy*: no runtime decision is fixed here that a later sprint
  would have to undo. The persistent ``PostgresNeo4jGraphStore`` is built by
  replacing the placeholder's body in a later Phase 2 sprint (per PHASE2_PLAN.md,
  the backend lands in Sprint 4+).
"""

from __future__ import annotations

from emg_platform_core import GraphStore, InMemoryGraphStore

from .config import PersistenceSettings


def _build_persistent_store(settings: PersistenceSettings) -> GraphStore:
    """Placeholder for the persistent (PostgreSQL + Neo4j) ``GraphStore``.

    Intentionally unimplemented in Sprint 1 — a structural seam only. A later
    Phase 2 sprint replaces this body with the real ``PostgresNeo4jGraphStore``
    construction (using ``settings``); until then it raises
    ``NotImplementedError`` so the scaffold makes no premature runtime decision.

    Raises:
        NotImplementedError: always, in Sprint 1.
    """
    raise NotImplementedError(
        "The persistent GraphStore backend is not implemented yet; it is "
        "delivered in a later Phase 2 sprint. This is a Sprint 1 scaffold "
        "placeholder that will be filled in when the backend lands."
    )


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
        NotImplementedError: when persistence is configured — the persistent
            backend placeholder is not implemented in Sprint 1 (delivered in a
            later Phase 2 sprint).
    """
    settings = settings if settings is not None else PersistenceSettings()
    if settings.is_persistence_configured:
        return _build_persistent_store(settings)
    return InMemoryGraphStore()
