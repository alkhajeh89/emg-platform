"""DB-backed RevisionRepository integration tests (Sprint 3).

Require a live PostgreSQL; **skipped** unless ``EMG_PERSISTENCE_TEST_POSTGRES_DSN``
is set. Run in the CI ``persistence`` job. They exercise the real transactional
compare-and-set behavior against ``graph_revisions`` + ``graph_head`` (schema
created via the packaged baseline migration).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from emg_persistence import PersistenceConflictError, PersistenceSettings
from emg_persistence.revisions import Revision, RevisionHead
from emg_platform_core import PrincipalRef, TenantId

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)

_TENANT = TenantId.of("acme")
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _hash(seed: str) -> str:  # pragma: no cover - only used by DB-gated tests
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _rev(  # pragma: no cover - only used by DB-gated tests
    number: int, *, seed: str, parent_hash: str | None = None
) -> Revision:
    return Revision(
        tenant=_TENANT,
        revision_number=number,
        content_hash=_hash(seed),
        parent_hash=parent_hash,
        principal=PrincipalRef.service("ingest"),
        node_count=1,
        edge_count=0,
        graph_json={"nodes": [], "edges": []},
        created_at=_T0,
    )


@pytest.fixture
def repo():  # type: ignore[no-untyped-def]  # pragma: no cover - runs only with a live DB
    from emg_persistence.migrate import run_migrations
    from emg_persistence.postgres import (
        PostgresMigrationExecutor,
        PostgresRevisionRepository,
        connect,
    )

    settings = PersistenceSettings(postgres_dsn=_PG_DSN)
    conn = connect(settings)
    run_migrations(PostgresMigrationExecutor(conn))  # ensure baseline schema
    with conn.cursor() as cur:
        cur.execute("TRUNCATE graph_revisions, graph_head")
    conn.commit()
    try:
        yield PostgresRevisionRepository(conn)
    finally:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE graph_revisions, graph_head")
        conn.commit()
        conn.close()


@requires_postgres
def test_first_and_append(repo) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    r1 = _rev(1, seed="r1")
    assert repo.create_first_revision(r1) == r1.head()
    assert repo.get_head(_TENANT) == r1.head()
    r2 = _rev(2, seed="r2", parent_hash=r1.content_hash)
    assert repo.append_revision(r2) == r2.head()
    assert repo.revision_count(_TENANT) == 2
    assert repo.get_revision(_TENANT, 1) == r1


@requires_postgres
def test_first_revision_conflict(repo) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    repo.create_first_revision(_rev(1, seed="a"))
    with pytest.raises(PersistenceConflictError):
        repo.create_first_revision(_rev(1, seed="b"))
    assert repo.revision_count(_TENANT) == 1  # second did not insert a row


@requires_postgres
def test_append_optimistic_failure_rolls_back(repo) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    r1 = _rev(1, seed="r1")
    repo.create_first_revision(r1)
    repo.append_revision(_rev(2, seed="r2", parent_hash=r1.content_hash))
    # stale parent (points at r1 while head is r2) -> conflict, revision not inserted
    with pytest.raises(PersistenceConflictError):
        repo.append_revision(_rev(3, seed="stale", parent_hash=r1.content_hash))
    assert repo.revision_count(_TENANT) == 2
    assert repo.revision_exists(_TENANT, 3) is False


@requires_postgres
def test_compare_and_set_head(repo) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    h1 = RevisionHead(tenant=_TENANT, revision_number=1, content_hash=_hash("h1"))
    assert repo.compare_and_set_head(_TENANT, None, h1) is True
    assert repo.compare_and_set_head(_TENANT, None, h1) is False
    h2 = RevisionHead(tenant=_TENANT, revision_number=2, content_hash=_hash("h2"))
    assert repo.compare_and_set_head(_TENANT, h1, h2) is True
    assert repo.compare_and_set_head(_TENANT, h1, h2) is False
