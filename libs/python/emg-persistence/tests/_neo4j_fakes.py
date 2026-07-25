"""In-memory fake Neo4j driver for unit-testing ``Neo4jGraphProjection``.

Mirrors the ``_outbox_helpers.py`` / ``_rev_helpers.py`` convention: reusable
test doubles placed on ``sys.path`` via ``conftest.py`` rather than imported
as a package (pytest's ``--import-mode=importlib`` setup, see conftest.py).

``_FakeNeo4jStore`` recognizes the small, fixed set of parameterized Cypher
statements ``Neo4jGraphProjection`` issues (see
``emg_persistence.neo4j.projection``) and maintains real in-memory node/edge/
head state, so tests exercise the projection's actual control flow (diff
application, compare-and-set semantics, reconstruction) rather than a
stubbed-out shell. It is deliberately scoped to only what that one module
emits; it is not a general Cypher interpreter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def __iter__(self) -> Any:
        return iter(self._records)

    def single(self) -> dict[str, Any] | None:
        return self._records[0] if self._records else None


class _FakeTransaction:
    def __init__(self, store: _FakeNeo4jStore) -> None:
        self._store = store
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def run(self, cypher: str, params: Mapping[str, Any] | None = None) -> _FakeResult:
        return self._store.dispatch(cypher, params or {})

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    def __init__(self, store: _FakeNeo4jStore) -> None:
        self._store = store

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def run(self, cypher: str, params: Mapping[str, Any] | None = None) -> _FakeResult:
        return self._store.dispatch(cypher, params or {})

    def begin_transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self._store)


class FakeNeo4jDriver:
    """Driver double: ``Neo4jGraphProjection(driver)`` only ever calls ``.session()``."""

    def __init__(self, store: _FakeNeo4jStore | None = None) -> None:
        self.store = store if store is not None else _FakeNeo4jStore()

    def session(self) -> _FakeSession:
        return _FakeSession(self.store)


class ExplodingDriver:
    """Driver double whose ``.session()`` always raises — proves validation
    happens before any driver interaction, and proves driver errors are
    wrapped into ``PersistenceError`` rather than leaking."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self._exc = exc if exc is not None else RuntimeError("simulated driver failure")
        self.touched = False

    def session(self) -> Any:
        self.touched = True
        raise self._exc


class _FakeNeo4jStore:
    """Minimal in-memory simulation of the Cypher statements
    ``Neo4jGraphProjection`` issues — real node/edge/head state, real CAS
    semantics, real idempotent MERGE/DELETE behavior."""

    def __init__(self) -> None:
        self.nodes: dict[tuple[str, str], dict[str, Any]] = {}
        self.edges: dict[tuple[str, str], dict[str, Any]] = {}
        self.heads: dict[str, dict[str, Any]] = {}
        self.run_log: list[str] = []
        self.explode: BaseException | None = None

    def dispatch(self, cypher: str, params: Mapping[str, Any]) -> _FakeResult:
        if self.explode is not None:
            raise self.explode
        self.run_log.append(cypher)
        tenant_id = params.get("tenant_id")

        if "RETURN h.revision_number" in cypher:
            head = self.heads.get(tenant_id)
            return _FakeResult([dict(head)] if head is not None else [])

        if "UNWIND $ids AS edge_id" in cypher and "DELETE e" in cypher:
            for edge_id in params["ids"]:
                self.edges.pop((tenant_id, edge_id), None)
            return _FakeResult([])

        if "UNWIND $ids AS node_id" in cypher and "DETACH DELETE n" in cypher:
            for node_id in params["ids"]:
                self.nodes.pop((tenant_id, node_id), None)
            return _FakeResult([])

        if "UNWIND $nodes AS row" in cypher and "MERGE (n:MemoryNode" in cypher:
            for row in params["nodes"]:
                self.nodes[(row["tenant_id"], row["node_id"])] = row
            return _FakeResult([])

        if "UNWIND $edges AS row" in cypher and "MERGE (a)-[e:MEMORY_EDGE" in cypher:
            for row in params["edges"]:
                if (row["tenant_id"], row["source_id"]) not in self.nodes:
                    continue
                if (row["tenant_id"], row["target_id"]) not in self.nodes:
                    continue
                self.edges[(row["tenant_id"], row["edge_id"])] = row
            return _FakeResult([])

        if "OPTIONAL MATCH (h:GraphHead" in cypher and "FOREACH" in cypher:
            current = self.heads.get(tenant_id)
            current_rev = current["revision_number"] if current is not None else 0
            if current_rev != params["expected"]:
                return _FakeResult([])  # CAS miss
            self.heads[tenant_id] = {
                "revision_number": params["next_revision"],
                "content_hash": params["next_hash"],
            }
            return _FakeResult([{"ok": 1}])

        if "RETURN n.content_json" in cypher:
            rows = sorted(
                (v for (t, _nid), v in self.nodes.items() if t == tenant_id),
                key=lambda r: r["node_id"],
            )
            return _FakeResult([{"content_json": r["content_json"]} for r in rows])

        if "RETURN e.content_json" in cypher:
            rows = sorted(
                (v for (t, _eid), v in self.edges.items() if t == tenant_id),
                key=lambda r: r["edge_id"],
            )
            return _FakeResult([{"content_json": r["content_json"]} for r in rows])

        if cypher.strip().startswith("MATCH (h:GraphHead") and "DELETE h" in cypher:
            self.heads.pop(tenant_id, None)
            return _FakeResult([])

        if "MEMORY_EDGE {tenant_id: $tenant_id}" in cypher and "DELETE e" in cypher:
            for key in [k for k in self.edges if k[0] == tenant_id]:
                del self.edges[key]
            return _FakeResult([])

        if "RETURN count(n) AS removed" in cypher:
            keys = [k for k in self.nodes if k[0] == tenant_id]
            for key in keys:
                del self.nodes[key]
            return _FakeResult([{"removed": len(keys)}])

        raise AssertionError(f"unrecognized cypher in fake Neo4j store: {cypher[:80]!r}")
