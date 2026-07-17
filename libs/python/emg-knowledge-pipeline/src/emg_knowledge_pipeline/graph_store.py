"""Storage-independent graph persistence + transaction abstraction (FEAT-05-2).

The pipeline's business logic depends ONLY on the `GraphStore` and
`GraphTransaction` Protocols, never on a concrete engine — so a Neo4j adapter
can be added later (FEAT-05-4, the Semantic Layer) without touching ingestion
logic, and **no other database is introduced**. Sprint 10 ships one concrete
adapter, `InMemoryGraphStore`, which is enough to validate ingestion from a
source type end-to-end.

Guarantees:
- **Append-only.** There is no update or delete method on either Protocol; the
  knowledge graph is corrected by superseding (a new version), never by mutating
  a stored record — consistent with Module 6's append-only posture.
- **Transactional / no partial graph.** A `GraphTransaction` stages entities and
  relationships and applies them **atomically** on `commit()`. If anything
  fails, `rollback()` (or a raised exception) leaves the store exactly as it was
  — no partial nodes, no partial relationships.
- **Idempotent commit.** Staging an id that already exists with byte-identical
  content is a no-op (idempotent re-ingestion); an id that exists with different
  content is a conflict (rejected) — supersession/versioning is explicit, never
  a silent overwrite.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from emg_ontology import Entity, Relationship

from .errors import GraphPersistenceError, IngestionConflictError


@runtime_checkable
class GraphTransaction(Protocol):
    """A unit of work over the graph. Stages writes, then commits or rolls back
    atomically. Usable as a context manager (rolls back on an exception; a
    successful path must call `commit()` explicitly)."""

    def add_entity(self, entity: Entity) -> None: ...

    def add_relationship(self, relationship: Relationship) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> GraphTransaction: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


@runtime_checkable
class GraphStore(Protocol):
    """The append-only graph system-of-record contract."""

    def has_entity(self, entity_id: str) -> bool: ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def has_relationship(self, relationship_id: str) -> bool: ...

    def get_relationship(self, relationship_id: str) -> Relationship | None: ...

    def begin(self) -> GraphTransaction: ...


class InMemoryGraphTransaction:
    """In-memory transaction: buffers staged writes, applies them atomically on
    commit under the store lock. Usable as a context manager (rolls back on an
    exception; requires an explicit `commit()` on success)."""

    def __init__(self, store: InMemoryGraphStore) -> None:
        self._store = store
        self._staged_entities: list[Entity] = []
        self._staged_relationships: list[Relationship] = []
        self._closed = False

    def add_entity(self, entity: Entity) -> None:
        self._staged_entities.append(entity)

    def add_relationship(self, relationship: Relationship) -> None:
        self._staged_relationships.append(relationship)

    def commit(self) -> None:
        if self._closed:
            raise GraphPersistenceError("transaction already closed")
        # Apply atomically: the store validates the whole staged set against
        # current state first, then inserts — so a conflict leaves nothing
        # partially written.
        self._store._apply(self._staged_entities, self._staged_relationships)
        self._closed = True

    def rollback(self) -> None:
        self._staged_entities.clear()
        self._staged_relationships.clear()
        self._closed = True

    def __enter__(self) -> InMemoryGraphTransaction:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if not self._closed:
            self.rollback()


class InMemoryGraphStore:
    """Append-only in-memory graph adapter (tests / local dev / the Sprint 10
    end-to-end path). Thread-safe: `_apply` serializes on a lock, so concurrent
    commits cannot fork the graph, and concurrent identical ingestions collapse
    to a single node (idempotent)."""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[str, Relationship] = {}
        self._lock = threading.Lock()

    # --- read side (contract) ---
    def has_entity(self, entity_id: str) -> bool:
        with self._lock:
            return entity_id in self._entities

    def get_entity(self, entity_id: str) -> Entity | None:
        with self._lock:
            return self._entities.get(entity_id)

    def has_relationship(self, relationship_id: str) -> bool:
        with self._lock:
            return relationship_id in self._relationships

    def get_relationship(self, relationship_id: str) -> Relationship | None:
        with self._lock:
            return self._relationships.get(relationship_id)

    def begin(self) -> InMemoryGraphTransaction:
        return InMemoryGraphTransaction(self)

    # --- atomic apply (used by the transaction) ---
    def _apply(self, entities: list[Entity], relationships: list[Relationship]) -> None:
        with self._lock:
            # Phase 1: validate the whole set against current state. A conflict
            # here raises before ANY write, so the store is never left partial.
            planned_entities: dict[str, Entity] = {}
            for entity in entities:
                existing = self._entities.get(entity.entity_id)
                if existing is not None:
                    if existing.model_dump() != entity.model_dump():
                        raise IngestionConflictError(
                            f"entity {entity.entity_id!r} already exists with different content",
                            error_code="GRAPH_ENTITY_CONFLICT",
                        )
                    continue  # idempotent no-op
                planned_entities[entity.entity_id] = entity

            planned_relationships: dict[str, Relationship] = {}
            for rel in relationships:
                existing_rel = self._relationships.get(rel.relationship_id)
                if existing_rel is not None:
                    if existing_rel.model_dump() != rel.model_dump():
                        raise IngestionConflictError(
                            f"relationship {rel.relationship_id!r} already exists with "
                            "different content",
                            error_code="GRAPH_RELATIONSHIP_CONFLICT",
                        )
                    continue
                planned_relationships[rel.relationship_id] = rel

            # Phase 2: commit all (no failure possible past this point).
            self._entities.update(planned_entities)
            self._relationships.update(planned_relationships)

    # --- introspection helpers (read-only; not mutation) ---
    def entity_count(self) -> int:
        with self._lock:
            return len(self._entities)

    def relationship_count(self) -> int:
        with self._lock:
            return len(self._relationships)
