from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN")
_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "src/emg_persistence/migrations/postgres/V010__governed_entity_search.sql"
)


def test_exact_prefix_and_continuation_plans_are_tenant_revision_indexed():
    import psycopg
    from emg_persistence.postgres.search_repository import PostgresSearchRepository
    from emg_platform_core import TenantId
    from psycopg import sql

    schema = f"search_plan_{uuid4().hex}"
    connection = psycopg.connect(_PG_DSN)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cursor.execute(
                """CREATE TABLE graph_revisions (
                tenant_id text NOT NULL, revision_number integer NOT NULL,
                content_hash char(64) NOT NULL, node_count integer NOT NULL,
                PRIMARY KEY (tenant_id, revision_number))"""
            )
            cursor.execute(_MIGRATION.read_text(encoding="utf-8"))
            cursor.execute("INSERT INTO graph_revisions VALUES ('tenant-a',1,repeat('a',64),20000)")
            cursor.execute(
                """INSERT INTO entity_search_representations
                VALUES ('tenant-a',1,repeat('a',64),20000,1,NULL)"""
            )
            cursor.execute(
                """INSERT INTO entity_search_documents
                SELECT 'tenant-a',1,'entity-'||lpad(g::text,5,'0'),'person',
                  'Entity '||g,0.9,'INTERNAL',now(),now(),1
                FROM generate_series(1,20000) g"""
            )
            cursor.execute(
                """INSERT INTO entity_search_terms
                SELECT 'tenant-a',1,'entity-'||lpad(g::text,5,'0'),'id',
                  'entity-'||lpad(g::text,5,'0')
                FROM generate_series(1,20000) g"""
            )
            cursor.execute("ANALYZE entity_search_terms")
            exact = _plan(
                cursor,
                """SELECT node_id FROM entity_search_terms
                WHERE tenant_id='tenant-a' AND revision_number=1
                  AND normalized_term='entity-12345'""",
            )
            prefix = _plan(
                cursor,
                """SELECT node_id FROM entity_search_terms
                WHERE tenant_id='tenant-a' AND revision_number=1
                  AND normalized_term LIKE 'entity-123%'
                ORDER BY node_id LIMIT 100""",
            )
            continuation = _plan(
                cursor,
                """WITH matches AS (
                  SELECT node_id,4 AS tier FROM entity_search_terms
                  WHERE tenant_id='tenant-a' AND revision_number=1
                    AND normalized_term LIKE 'entity-123%')
                SELECT d.node_id FROM matches m
                JOIN entity_search_documents d USING(node_id)
                WHERE d.tenant_id='tenant-a' AND d.revision_number=1
                  AND (m.tier>4 OR (m.tier=4 AND d.node_id>'entity-12340'))
                ORDER BY m.tier,d.node_id LIMIT 100""",
            )
            retirement = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=1)
            cursor.execute(
                """INSERT INTO graph_revisions
                SELECT 'high-velocity',g,repeat('b',64),0
                FROM generate_series(1,21) g"""
            )
            cursor.execute(
                """INSERT INTO entity_search_representations
                SELECT 'high-velocity',g,repeat('b',64),0,1,
                  CASE WHEN g < 21 THEN %s ELSE NULL END
                FROM generate_series(1,21) g""",
                (retirement,),
            )
            cursor.execute(
                """SELECT count(*) FROM entity_search_representations
                WHERE tenant_id='high-velocity'"""
            )
            assert cursor.fetchone() == (21,)
            repository = PostgresSearchRepository(connection)
            assert repository.delete_expired(retirement - timedelta(seconds=1), limit=5) == 0
            assert repository.delete_expired(retirement, limit=5) == 5
            cursor.execute(
                """SELECT count(*) FROM entity_search_representations
                WHERE tenant_id='high-velocity'"""
            )
            assert cursor.fetchone() == (16,)
            assert [repository.delete_expired(retirement, limit=5) for _ in range(3)] == [5, 5, 5]
            cursor.execute(
                """SELECT revision_number FROM entity_search_representations
                WHERE tenant_id='high-velocity'"""
            )
            assert cursor.fetchall() == [(21,)]
            metrics = repository.representation_metrics()
            tenant_metrics = [row for row in metrics if row[0] == "tenant-a"]
            assert tenant_metrics[0][3:5] == (20_000, 20_000)
            assert tenant_metrics[0][6] > 0
            cursor.execute("INSERT INTO graph_revisions VALUES ('semantic',1,repeat('c',64),6)")
            cursor.execute(
                """INSERT INTO entity_search_representations
                VALUES ('semantic',1,repeat('c',64),6,1,NULL)"""
            )
            cursor.execute(
                """INSERT INTO entity_search_documents
                SELECT 'semantic',1,node_id,'person',label,0.9,'INTERNAL',now(),now(),1
                FROM (VALUES
                  ('north','North ID'),('a-label','North'),('b-alias','Alias'),
                  ('north-id','ID Prefix'),('c-label-prefix','Northwind'),
                  ('d-alias-prefix','Alias Prefix')) AS n(node_id,label)"""
            )
            cursor.execute(
                """INSERT INTO entity_search_terms VALUES
                ('semantic',1,'north','id','north'),
                ('semantic',1,'a-label','label','north'),
                ('semantic',1,'b-alias','alias','north'),
                ('semantic',1,'north-id','id','north-id'),
                ('semantic',1,'c-label-prefix','label','northwind'),
                ('semantic',1,'d-alias-prefix','alias','northstar')"""
            )
            rows = PostgresSearchRepository(connection).search(
                TenantId.of("semantic"),
                1,
                "north",
                after_tier=0,
                after_node_id="",
                limit=10,
            )
            assert [(row[0], row[7]) for row in rows] == [
                ("north", 1),
                ("a-label", 2),
                ("b-alias", 3),
                ("north-id", 4),
                ("c-label-prefix", 5),
                ("d-alias-prefix", 6),
            ]
            continued = PostgresSearchRepository(connection).search(
                TenantId.of("semantic"),
                1,
                "north",
                after_tier=3,
                after_node_id="b-alias",
                limit=10,
            )
            assert [(row[0], row[7]) for row in continued] == [
                ("north-id", 4),
                ("c-label-prefix", 5),
                ("d-alias-prefix", 6),
            ]
        for plan in (exact, prefix, continuation):
            assert "entity_search_terms" in plan
            assert "tenant_id" in plan and "revision_number" in plan
            assert "Seq Scan on entity_search_terms" not in plan
            assert "ix_entity_search_terms_prefix" in plan
    finally:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )
        connection.commit()
        connection.close()


def _plan(cursor, query: str) -> str:
    cursor.execute("EXPLAIN (COSTS OFF) " + query)
    return "\n".join(row[0] for row in cursor.fetchall())
