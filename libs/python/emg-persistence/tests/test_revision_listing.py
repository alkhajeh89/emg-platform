"""RevisionRepository.list_revisions: metadata-only listing (ADR-023 §18).

Covers both implementations. The PostgreSQL implementation is exercised
against a fake cursor/connection (no live database available here) to verify
the exact query shape — omitting graph_json, DESC ordering, exclusive cursor,
bounded limit — mirroring the existing fake-connection pattern used for the
outbox repository tests.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from _rev_helpers import PRINCIPAL, TENANT, make_revision
from emg_persistence.postgres.revision_repository import PostgresRevisionRepository
from emg_persistence.revisions import InMemoryRevisionRepository, RevisionRecord
from emg_platform_core import MAX_REVISION_LIST_LIMIT, PrincipalKind, TenantId
from psycopg import Connection


def _repo() -> InMemoryRevisionRepository:
    return InMemoryRevisionRepository()


# --- InMemoryRevisionRepository -----------------------------------------


def test_list_revisions_empty_history() -> None:
    repo = _repo()
    assert repo.list_revisions(TENANT) == ()


def test_list_revisions_descending_order() -> None:
    repo = _repo()
    r1 = make_revision(1)
    repo.create_first_revision(r1)
    r2 = make_revision(2, parent_hash=r1.content_hash)
    repo.append_revision(r2)
    r3 = make_revision(3, parent_hash=r2.content_hash)
    repo.append_revision(r3)

    records = repo.list_revisions(TENANT)
    assert [r.revision_number for r in records] == [3, 2, 1]
    assert all(isinstance(r, RevisionRecord) for r in records)


def test_list_revisions_first_revision_parent_hash_is_none() -> None:
    repo = _repo()
    repo.create_first_revision(make_revision(1))
    records = repo.list_revisions(TENANT)
    assert records[0].revision_number == 1
    assert records[0].parent_hash is None


def test_list_revisions_metadata_omits_graph_json() -> None:
    repo = _repo()
    repo.create_first_revision(make_revision(1))
    record = repo.list_revisions(TENANT)[0]
    # RevisionRecord structurally has no graph_json field at all.
    assert not hasattr(record, "graph_json")
    assert set(type(record).model_fields) == {
        "tenant",
        "revision_number",
        "content_hash",
        "parent_hash",
        "principal",
        "node_count",
        "edge_count",
        "created_at",
    }


def test_list_revisions_exclusive_cursor() -> None:
    repo = _repo()
    r1 = make_revision(1)
    repo.create_first_revision(r1)
    r2 = make_revision(2, parent_hash=r1.content_hash)
    repo.append_revision(r2)
    r3 = make_revision(3, parent_hash=r2.content_hash)
    repo.append_revision(r3)

    records = repo.list_revisions(TENANT, before_revision_number=3)
    assert [r.revision_number for r in records] == [2, 1]

    records_none_before_1 = repo.list_revisions(TENANT, before_revision_number=1)
    assert records_none_before_1 == ()


def test_list_revisions_limit_enforcement() -> None:
    repo = _repo()
    r1 = make_revision(1)
    repo.create_first_revision(r1)
    r2 = make_revision(2, parent_hash=r1.content_hash)
    repo.append_revision(r2)

    assert [r.revision_number for r in repo.list_revisions(TENANT, limit=1)] == [2]
    with pytest.raises(ValueError):
        repo.list_revisions(TENANT, limit=0)
    with pytest.raises(ValueError):
        repo.list_revisions(TENANT, limit=MAX_REVISION_LIST_LIMIT + 1)


def test_list_revisions_tenant_filtering() -> None:
    repo = _repo()
    other = TenantId.of("other-tenant")
    repo.create_first_revision(make_revision(1))
    repo.create_first_revision(make_revision(1, tenant=other, content_seed="o1"))

    assert len(repo.list_revisions(TENANT)) == 1
    assert len(repo.list_revisions(other)) == 1
    assert repo.list_revisions(TENANT)[0].tenant == TENANT
    assert repo.list_revisions(other)[0].tenant == other


def test_full_revision_read_remains_unchanged() -> None:
    repo = _repo()
    r1 = make_revision(1)
    repo.create_first_revision(r1)
    fetched = repo.get_revision(TENANT, 1)
    assert fetched == r1
    assert fetched.graph_json == {"nodes": [], "edges": []}  # type: ignore[union-attr]


# --- PostgresRevisionRepository (fake cursor/connection) ----------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.executed: tuple[str, dict[str, Any]] | None = None
        self._rows = rows

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self.executed = (query, params)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.cursor_instance = _FakeCursor(rows)

    def cursor(self) -> AbstractContextManager[_FakeCursor]:
        return self.cursor_instance


_ROW_CREATED_AT = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _row(revision_number: int, parent_hash: str | None) -> tuple[object, ...]:
    return (
        revision_number,
        "a" * 64,
        parent_hash,
        PRINCIPAL.principal_id,
        PRINCIPAL.kind.value,
        1,
        0,
        _ROW_CREATED_AT,
    )


def test_postgres_list_revisions_query_omits_graph_json_and_orders_desc() -> None:
    connection = _FakeConnection([_row(2, "b" * 64), _row(1, None)])
    repo = PostgresRevisionRepository(cast(Connection[Any], connection))

    records = repo.list_revisions(TENANT)

    assert connection.cursor_instance.executed is not None
    query, params = connection.cursor_instance.executed
    assert "graph_json" not in query
    assert "ORDER BY revision_number DESC" in query
    assert params["t"] == TENANT.value
    assert [r.revision_number for r in records] == [2, 1]
    assert records[1].parent_hash is None
    assert records[0].principal.kind is PrincipalKind(PRINCIPAL.kind.value)


def test_postgres_list_revisions_without_cursor_omits_before_filter() -> None:
    connection = _FakeConnection([_row(1, None)])
    repo = PostgresRevisionRepository(cast(Connection[Any], connection))

    repo.list_revisions(TENANT, limit=10)

    query, params = connection.cursor_instance.executed  # type: ignore[misc]
    assert "revision_number <" not in query
    assert params["limit"] == 10


def test_postgres_list_revisions_with_cursor_uses_exclusive_before_filter() -> None:
    connection = _FakeConnection([_row(1, None)])
    repo = PostgresRevisionRepository(cast(Connection[Any], connection))

    repo.list_revisions(TENANT, before_revision_number=2)

    query, params = connection.cursor_instance.executed  # type: ignore[misc]
    assert "revision_number < %(before)s" in query
    assert params["before"] == 2


def test_postgres_list_revisions_rejects_invalid_limit() -> None:
    connection = _FakeConnection([])
    repo = PostgresRevisionRepository(cast(Connection[Any], connection))

    with pytest.raises(ValueError):
        repo.list_revisions(TENANT, limit=0)
    with pytest.raises(ValueError):
        repo.list_revisions(TENANT, limit=MAX_REVISION_LIST_LIMIT + 1)
