"""Neo4j serving projection (Phase 2) — rebuildable topology, never source of truth.

Implements ``Neo4jGraphProjection`` per PHASE2_ARCHITECTURE.md §5 / §8:

* idempotent diff apply (MERGE/DELETE keyed by node/edge id)
* monotonic ``:GraphHead`` compare-and-set
* reconstruct → ``MemoryGraph`` with canonical ``content_hash`` equality
* read-repair / ``catch_up_projection`` / ``rebuild_projection``

UTF-8 bilingual payloads (ADR-018) are preserved inside ``content_json``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from emg_memory_graph import EMPTY_GRAPH, MemoryEdge, MemoryGraph, MemoryNode, diff_graphs
from emg_platform_core import TenantId
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import PersistenceError
from ..revisions import Revision

RevisionLoader = Callable[[TenantId, int], Revision | None]
HeadLoader = Callable[[TenantId], tuple[int, str] | None]


class ProjectionHead(BaseModel):
    """Immutable Neo4j ``:GraphHead`` marker for one tenant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    revision_number: int = Field(ge=0)
    content_hash: str


class Neo4jGraphProjection:
    """Queryable Neo4j topology projection derived from PostgreSQL revisions."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def get_projection_head(self, tenant: TenantId) -> ProjectionHead | None:
        """Return the projection head, or ``None`` if the tenant has never been projected."""
        records = self._run_read(
            """
            MATCH (h:GraphHead {tenant_id: $tenant_id})
            RETURN h.revision_number AS revision_number, h.content_hash AS content_hash
            """,
            {"tenant_id": tenant.value},
        )
        if not records:
            return None
        row = records[0]
        return ProjectionHead(
            tenant=tenant,
            revision_number=int(row["revision_number"]),
            content_hash=str(row["content_hash"]),
        )

    def apply(
        self,
        tenant: TenantId,
        *,
        expected_revision: int,
        revision: Revision,
        before: MemoryGraph,
        after: MemoryGraph,
    ) -> bool:
        """Apply ``before → after`` idempotently and CAS head ``expected → expected+1``.

        Returns ``True`` if this caller advanced the head, ``False`` if another
        repairer already advanced it (CAS miss — safe no-op).
        """
        if revision.tenant != tenant:
            raise PersistenceError("revision tenant does not match apply tenant")
        if revision.revision_number != expected_revision + 1:
            raise PersistenceError(
                f"revision {revision.revision_number} is not the successor of "
                f"expected projection head {expected_revision}"
            )
        if after.content_hash() != revision.content_hash:
            raise PersistenceError("after-graph content_hash does not match revision content_hash")

        graph_diff = diff_graphs(before, after)
        node_by_id = {n.node_id: n for n in after.nodes}
        edge_by_id = {e.edge_id: e for e in after.edges}

        removed_edge_ids = list(graph_diff.removed_edges) + list(graph_diff.modified_edges)
        upsert_edge_ids = list(graph_diff.added_edges) + list(graph_diff.modified_edges)
        removed_node_ids = list(graph_diff.removed_nodes)
        upsert_node_ids = list(graph_diff.added_nodes) + list(graph_diff.modified_nodes)

        nodes = [_node_row(tenant, node_by_id[nid]) for nid in upsert_node_ids]
        edges = [_edge_row(tenant, edge_by_id[eid]) for eid in upsert_edge_ids]

        try:
            with self._driver.session() as session:
                tx = session.begin_transaction()
                try:
                    if removed_edge_ids:
                        tx.run(
                            """
                            UNWIND $ids AS edge_id
                            MATCH ()-[e:MEMORY_EDGE {tenant_id: $tenant_id, edge_id: edge_id}]->()
                            DELETE e
                            """,
                            {"tenant_id": tenant.value, "ids": removed_edge_ids},
                        )
                    if removed_node_ids:
                        tx.run(
                            """
                            UNWIND $ids AS node_id
                            MATCH (n:MemoryNode {tenant_id: $tenant_id, node_id: node_id})
                            DETACH DELETE n
                            """,
                            {"tenant_id": tenant.value, "ids": removed_node_ids},
                        )
                    if nodes:
                        tx.run(
                            """
                            UNWIND $nodes AS row
                            MERGE (n:MemoryNode {tenant_id: row.tenant_id, node_id: row.node_id})
                            SET n.node_type = row.node_type,
                                n.label = row.label,
                                n.created_at = row.created_at,
                                n.updated_at = row.updated_at,
                                n.source = row.source,
                                n.confidence = row.confidence,
                                n.content_json = row.content_json
                            """,
                            {"nodes": nodes},
                        )
                    if edges:
                        tx.run(
                            """
                            UNWIND $edges AS row
                            MATCH (a:MemoryNode {tenant_id: $tenant_id, node_id: row.source_id})
                            MATCH (b:MemoryNode {tenant_id: $tenant_id, node_id: row.target_id})
                            MERGE (a)-[e:MEMORY_EDGE {
                                tenant_id: $tenant_id, edge_id: row.edge_id
                            }]->(b)
                            SET e.edge_type = row.edge_type,
                                e.direction = row.direction,
                                e.confidence = row.confidence,
                                e.valid_from = row.valid_from,
                                e.valid_until = row.valid_until,
                                e.content_json = row.content_json
                            """,
                            {"tenant_id": tenant.value, "edges": edges},
                        )
                    cas = tx.run(
                        """
                        OPTIONAL MATCH (h:GraphHead {tenant_id: $tenant_id})
                        WITH h, coalesce(h.revision_number, 0) AS current
                        WHERE current = $expected
                        FOREACH (_ IN CASE WHEN h IS NULL THEN [1] ELSE [] END |
                          CREATE (:GraphHead {
                            tenant_id: $tenant_id,
                            revision_number: $next_revision,
                            content_hash: $next_hash
                          })
                        )
                        FOREACH (_ IN CASE WHEN h IS NOT NULL THEN [1] ELSE [] END |
                          SET h.revision_number = $next_revision,
                              h.content_hash = $next_hash
                        )
                        RETURN 1 AS ok
                        """,
                        {
                            "tenant_id": tenant.value,
                            "expected": expected_revision,
                            "next_revision": revision.revision_number,
                            "next_hash": revision.content_hash,
                        },
                    )
                    advanced = cas.single() is not None
                    if advanced:
                        tx.commit()
                    else:
                        tx.rollback()
                    return advanced
                except Exception:
                    tx.rollback()
                    raise
                finally:
                    tx.close()
        except PersistenceError:
            raise
        except Exception as exc:  # noqa: BLE001 — driver exceptions vary by version
            raise PersistenceError("Neo4j projection apply failed") from exc

    def reconstruct(self, tenant: TenantId) -> MemoryGraph:
        """Build a ``MemoryGraph`` from projected ``content_json`` payloads."""
        node_rows = self._run_read(
            """
            MATCH (n:MemoryNode {tenant_id: $tenant_id})
            RETURN n.content_json AS content_json
            ORDER BY n.node_id
            """,
            {"tenant_id": tenant.value},
        )
        edge_rows = self._run_read(
            """
            MATCH ()-[e:MEMORY_EDGE {tenant_id: $tenant_id}]->()
            RETURN e.content_json AS content_json
            ORDER BY e.edge_id
            """,
            {"tenant_id": tenant.value},
        )
        try:
            nodes = tuple(_deserialize_node(row["content_json"]) for row in node_rows)
            edges = tuple(_deserialize_edge(row["content_json"]) for row in edge_rows)
            if not nodes and not edges:
                return EMPTY_GRAPH
            return MemoryGraph(nodes=nodes, edges=edges)
        except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PersistenceError(
                f"failed to reconstruct projection for tenant {tenant.value!r}"
            ) from exc

    def catch_up_projection(
        self,
        tenant: TenantId,
        *,
        load_head: HeadLoader,
        load_revision: RevisionLoader,
    ) -> int:
        """Replay pending revisions until the PostgreSQL head. Returns applied-through."""
        pg_head = load_head(tenant)
        if pg_head is None:
            return 0
        pg_revision, _pg_hash = pg_head

        while True:
            current = self.get_projection_head(tenant)
            current_rev = 0 if current is None else current.revision_number
            if current_rev >= pg_revision:
                return current_rev

            next_rev = current_rev + 1
            revision = load_revision(tenant, next_rev)
            if revision is None:
                raise PersistenceError(
                    f"missing revision {next_rev} for tenant {tenant.value!r} during catch-up"
                )
            before = (
                EMPTY_GRAPH
                if current_rev == 0
                else self._graph_at_revision(tenant, current_rev, load_revision)
            )
            after = _deserialize_revision_graph(revision)
            advanced = self.apply(
                tenant,
                expected_revision=current_rev,
                revision=revision,
                before=before,
                after=after,
            )
            if not advanced:
                # Another repairer won the CAS; loop and re-read head.
                continue

    def validate_projection(
        self,
        tenant: TenantId,
        *,
        load_head: HeadLoader,
    ) -> bool:
        """Return ``True`` when the Neo4j projection matches the PostgreSQL head."""
        pg_head = load_head(tenant)
        proj_head = self.get_projection_head(tenant)
        if pg_head is None:
            return proj_head is None
        pg_revision, expected_hash = pg_head
        if proj_head is None:
            return False
        if proj_head.revision_number != pg_revision or proj_head.content_hash != expected_hash:
            return False
        try:
            return self.reconstruct(tenant).content_hash() == expected_hash
        except PersistenceError:
            return False

    def read_repair(
        self,
        tenant: TenantId,
        *,
        load_head: HeadLoader,
        load_revision: RevisionLoader,
    ) -> MemoryGraph:
        """Catch up the projection then reconstruct (canonical hash semantics)."""
        applied = self.catch_up_projection(tenant, load_head=load_head, load_revision=load_revision)
        if applied == 0:
            return EMPTY_GRAPH
        graph = self.reconstruct(tenant)
        pg_head = load_head(tenant)
        if pg_head is None:
            return EMPTY_GRAPH
        _rev, expected_hash = pg_head
        if graph.content_hash() != expected_hash:
            raise PersistenceError(
                f"projection hash mismatch for tenant {tenant.value!r}: "
                f"reconstructed {graph.content_hash()} != authoritative {expected_hash}"
            )
        return graph

    def rebuild_projection(
        self,
        tenant: TenantId,
        *,
        load_head: HeadLoader,
        load_revision: RevisionLoader,
    ) -> int:
        """Wipe the tenant projection and replay from revision 1 through PG head."""
        self._clear_tenant(tenant)
        return self.catch_up_projection(tenant, load_head=load_head, load_revision=load_revision)

    def _graph_at_revision(
        self, tenant: TenantId, revision_number: int, load_revision: RevisionLoader
    ) -> MemoryGraph:
        revision = load_revision(tenant, revision_number)
        if revision is None:
            raise PersistenceError(
                f"missing revision {revision_number} for tenant {tenant.value!r}"
            )
        return _deserialize_revision_graph(revision)

    def _clear_tenant(self, tenant: TenantId) -> None:
        self._run_write(
            """
            MATCH (h:GraphHead {tenant_id: $tenant_id})
            DELETE h
            """,
            {"tenant_id": tenant.value},
        )
        self._run_write(
            """
            MATCH ()-[e:MEMORY_EDGE {tenant_id: $tenant_id}]->()
            DELETE e
            """,
            {"tenant_id": tenant.value},
        )
        self._run_write(
            """
            MATCH (n:MemoryNode {tenant_id: $tenant_id})
            DETACH DELETE n
            RETURN count(n) AS removed
            """,
            {"tenant_id": tenant.value},
        )

    def _run_read(self, cypher: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        try:
            with self._driver.session() as session:
                result = session.run(cypher, dict(params))
                return [dict(record) for record in result]
        except PersistenceError:
            raise
        except Exception as exc:  # noqa: BLE001 — driver exceptions vary by version
            raise PersistenceError("Neo4j projection read failed") from exc

    def _run_write(self, cypher: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        try:
            with self._driver.session() as session:
                result = session.run(cypher, dict(params))
                return [dict(record) for record in result]
        except PersistenceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError("Neo4j projection write failed") from exc


def _node_row(tenant: TenantId, node: MemoryNode) -> dict[str, Any]:
    payload = node.model_dump(mode="json")
    return {
        "tenant_id": tenant.value,
        "node_id": node.node_id,
        "node_type": node.node_type,
        "label": node.label,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
        "source": node.source,
        "confidence": node.confidence,
        "content_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }


def _edge_row(tenant: TenantId, edge: MemoryEdge) -> dict[str, Any]:
    payload = edge.model_dump(mode="json")
    return {
        "tenant_id": tenant.value,
        "edge_id": edge.edge_id,
        "edge_type": edge.edge_type,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "direction": edge.direction.value,
        "confidence": edge.confidence,
        "valid_from": edge.validity.valid_from.isoformat(),
        "valid_until": (
            None if edge.validity.valid_until is None else edge.validity.valid_until.isoformat()
        ),
        "content_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    }


def _deserialize_node(raw: Any) -> MemoryNode:
    data = raw if isinstance(raw, dict) else json.loads(str(raw))
    return MemoryNode.model_validate(data)


def _deserialize_edge(raw: Any) -> MemoryEdge:
    data = raw if isinstance(raw, dict) else json.loads(str(raw))
    return MemoryEdge.model_validate(data)


def _deserialize_revision_graph(revision: Revision) -> MemoryGraph:
    try:
        graph = MemoryGraph.model_validate(revision.graph_json)
    except ValidationError as exc:
        raise PersistenceError(
            f"invalid graph snapshot at revision {revision.revision_number} "
            f"for tenant {revision.tenant.value!r}"
        ) from exc
    if graph.content_hash() != revision.content_hash:
        raise PersistenceError(
            f"graph snapshot hash mismatch at revision {revision.revision_number} "
            f"for tenant {revision.tenant.value!r}"
        )
    return graph
