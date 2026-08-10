"""ADR-042 PostgreSQL search representation and indexed candidate reader."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from emg_memory_graph import SEARCH_NORMALIZER_VERSION, MemoryGraph, normalize_search_text
from emg_platform_core import TenantId

if TYPE_CHECKING:
    from psycopg import Connection


class PostgresSearchRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    def index_revision(
        self,
        tenant: TenantId,
        revision_number: int,
        content_hash: str,
        graph: MemoryGraph,
    ) -> None:
        documents: list[dict[str, Any]] = []
        terms: list[dict[str, Any]] = []
        for node in graph.nodes:
            documents.append(
                {
                    "t": tenant.value,
                    "r": revision_number,
                    "id": node.node_id,
                    "type": node.node_type,
                    "label": node.label,
                    "confidence": node.confidence,
                    "classification": node.classification.value,
                    "created": node.created_at,
                    "updated": node.updated_at,
                    "version": SEARCH_NORMALIZER_VERSION,
                }
            )
            values = (
                ("id", node.node_id),
                ("label", node.label),
                *(("alias", a) for a in node.aliases),
            )
            for kind, value in values:
                terms.append(
                    {
                        "t": tenant.value,
                        "r": revision_number,
                        "id": node.node_id,
                        "kind": kind,
                        "term": normalize_search_text(value),
                    }
                )
        with self._connection.cursor() as cur:
            cur.execute(
                """INSERT INTO entity_search_representations
                (tenant_id, revision_number, content_hash, node_count, normalizer_version)
                VALUES (%s, %s, %s, %s, %s)""",
                (
                    tenant.value,
                    revision_number,
                    content_hash,
                    graph.node_count,
                    SEARCH_NORMALIZER_VERSION,
                ),
            )
            cur.executemany(
                """INSERT INTO entity_search_documents
              (tenant_id, revision_number, node_id, node_type, label, confidence,
               classification, created_at, updated_at, normalizer_version)
              VALUES (%(t)s, %(r)s, %(id)s, %(type)s, %(label)s, %(confidence)s,
               %(classification)s, %(created)s, %(updated)s, %(version)s)""",
                documents,
            )
            cur.executemany(
                """INSERT INTO entity_search_terms
              (tenant_id,revision_number,node_id,field_kind,normalized_term)
              VALUES (%(t)s,%(r)s,%(id)s,%(kind)s,%(term)s) ON CONFLICT DO NOTHING""",
                terms,
            )

    def expire_previous(self, tenant: TenantId, revision_number: int, expires_at: datetime) -> None:
        with self._connection.cursor() as cur:
            cur.execute(
                """UPDATE entity_search_representations SET representation_expires_at=%(e)s
              WHERE tenant_id=%(t)s AND revision_number < %(r)s
                AND representation_expires_at IS NULL""",
                {"e": expires_at, "t": tenant.value, "r": revision_number},
            )

    def expire_unscheduled_previous(self, expires_at: datetime, *, limit: int) -> int:
        """Repair post-commit scheduling gaps while preferring excess retention."""
        with self._connection.cursor() as cur:
            cur.execute(
                """WITH eligible AS (
                  SELECT s.ctid
                  FROM entity_search_representations s
                  JOIN graph_head h ON h.tenant_id=s.tenant_id
                  WHERE s.revision_number < h.head_revision_number
                    AND s.representation_expires_at IS NULL
                  ORDER BY s.tenant_id,s.revision_number
                  LIMIT %(limit)s FOR UPDATE OF s SKIP LOCKED)
                UPDATE entity_search_representations s
                SET representation_expires_at=%(expires)s
                FROM eligible e WHERE s.ctid=e.ctid""",
                {"expires": expires_at, "limit": limit},
            )
            return cur.rowcount

    def delete_expired(self, now: datetime, *, limit: int) -> int:
        with self._connection.cursor() as cur:
            cur.execute(
                """WITH eligible AS (
                  SELECT ctid FROM entity_search_representations
                  WHERE representation_expires_at <= %(now)s
                  ORDER BY representation_expires_at,tenant_id,revision_number
                  LIMIT %(limit)s FOR UPDATE SKIP LOCKED)
                DELETE FROM entity_search_representations s
                USING eligible e WHERE s.ctid=e.ctid""",
                {"now": now, "limit": limit},
            )
            return cur.rowcount

    def representation_metrics(self) -> tuple[tuple[Any, ...], ...]:
        """Low-cardinality operational cardinality/storage observations."""
        with self._connection.cursor() as cur:
            cur.execute(
                """SELECT s.tenant_id,s.revision_number,s.node_count,
                  (SELECT count(*) FROM entity_search_documents d
                    WHERE d.tenant_id=s.tenant_id
                      AND d.revision_number=s.revision_number) AS document_rows,
                  (SELECT count(*) FROM entity_search_terms t
                    WHERE t.tenant_id=s.tenant_id
                      AND t.revision_number=s.revision_number) AS term_rows,
                  s.representation_expires_at,
                  pg_total_relation_size('entity_search_documents') +
                    pg_total_relation_size('entity_search_terms') AS total_search_bytes
                FROM entity_search_representations s
                ORDER BY s.tenant_id,s.revision_number"""
            )
            return tuple(cur.fetchall())

    def representation_expiry(
        self, tenant: TenantId, revision_number: int
    ) -> datetime | None | bool:
        with self._connection.cursor() as cur:
            cur.execute(
                """SELECT s.representation_expires_at
                FROM entity_search_representations s
                JOIN graph_revisions g USING (tenant_id, revision_number)
                WHERE s.tenant_id=%s AND s.revision_number=%s
                  AND s.content_hash=g.content_hash
                  AND s.node_count=g.node_count
                  AND s.normalizer_version=%s
                LIMIT 1""",
                (tenant.value, revision_number, SEARCH_NORMALIZER_VERSION),
            )
            row = cur.fetchone()
            return False if row is None else row[0]

    def resolve_revision(
        self, tenant: TenantId, revision_number: int | None
    ) -> tuple[int, datetime, bool, datetime | None] | None:
        """Pin metadata and verify the complete representation without graph JSON I/O."""
        with self._connection.cursor() as cur:
            cur.execute(
                """SELECT g.revision_number,g.created_at,
                  (%(revision)s IS NULL) AS is_current,
                  s.representation_expires_at
                FROM graph_head h
                JOIN graph_revisions g ON g.tenant_id=h.tenant_id
                  AND g.revision_number=COALESCE(%(revision)s,h.head_revision_number)
                JOIN entity_search_representations s
                  ON s.tenant_id=g.tenant_id AND s.revision_number=g.revision_number
                WHERE h.tenant_id=%(tenant)s
                  AND s.content_hash=g.content_hash
                  AND s.node_count=g.node_count
                  AND s.normalizer_version=%(version)s
                """,
                {
                    "tenant": tenant.value,
                    "revision": revision_number,
                    "version": SEARCH_NORMALIZER_VERSION,
                },
            )
            return cur.fetchone()

    def backfill_current_heads(self) -> int:
        """Restart-safe backfill for heads that predate the search migration."""
        with self._connection.cursor() as cur:
            cur.execute(
                """SELECT g.tenant_id,g.revision_number,g.content_hash,g.graph_json
                FROM graph_head h
                JOIN graph_revisions g
                  ON g.tenant_id=h.tenant_id
                 AND g.revision_number=h.head_revision_number
                LEFT JOIN entity_search_representations s
                  ON s.tenant_id=g.tenant_id AND s.revision_number=g.revision_number
                WHERE s.tenant_id IS NULL ORDER BY g.tenant_id"""
            )
            rows = tuple(cur.fetchall())
        for tenant_value, revision_number, content_hash, graph_json in rows:
            graph = MemoryGraph.model_validate(graph_json)
            if graph.content_hash() != content_hash:
                raise ValueError("authoritative graph hash verification failed during backfill")
            self.index_revision(TenantId.of(tenant_value), revision_number, content_hash, graph)
        return len(rows)

    def search(
        self,
        tenant: TenantId,
        revision_number: int,
        query: str,
        *,
        after_tier: int,
        after_node_id: str,
        limit: int,
    ) -> tuple[tuple[Any, ...], ...]:
        prefix = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql = """WITH matches AS (
          SELECT node_id, min(CASE
            WHEN field_kind='id' AND normalized_term=%(q)s THEN 1
            WHEN field_kind='label' AND normalized_term=%(q)s THEN 2
            WHEN field_kind='alias' AND normalized_term=%(q)s THEN 3
            WHEN field_kind='id' THEN 4 WHEN field_kind='label' THEN 5 ELSE 6 END) tier
          FROM entity_search_terms WHERE tenant_id=%(t)s AND revision_number=%(r)s
            AND (normalized_term=%(q)s OR normalized_term LIKE %(p)s ESCAPE '\\')
          GROUP BY node_id)
        SELECT d.node_id,d.node_type,d.label,d.confidence,d.classification,
               d.created_at,d.updated_at,m.tier
        FROM matches m JOIN entity_search_documents d USING (node_id)
        WHERE d.tenant_id=%(t)s AND d.revision_number=%(r)s
          AND (m.tier > %(after_tier)s OR
            (m.tier = %(after_tier)s AND d.node_id > %(after_id)s))
        ORDER BY m.tier,d.node_id LIMIT %(limit)s"""
        with self._connection.cursor() as cur:
            cur.execute(
                sql,
                {
                    "t": tenant.value,
                    "r": revision_number,
                    "q": query,
                    "p": prefix,
                    "after_tier": after_tier,
                    "after_id": after_node_id,
                    "limit": limit,
                },
            )
            return tuple(cur.fetchall())
