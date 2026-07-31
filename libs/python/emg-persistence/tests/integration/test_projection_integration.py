"""Live Neo4j + PostgreSQL projection integration coverage (Outbox Event
Persistence, Phase 2).

Require live datastores and are **skipped** unless the corresponding env
vars are set; they run in the CI ``persistence`` job (PostgreSQL 16 + Neo4j 5
Community), not in the no-DB ``quality`` job — same gating convention as
``test_migration_integration.py`` / ``test_revision_integration.py`` /
``test_outbox_integration.py``.

These are the real-database counterpart to the fake-driver unit tests in
``tests/test_neo4j_projection.py``: same scenarios, a genuine Neo4j and
PostgreSQL underneath, so a real driver/Cypher/version incompatibility (which
no fake can catch) surfaces here. The PostgreSQL-fallback test in particular
exercises the ``store.py`` fix that restored ADR-5's read-availability
guarantee when Neo4j is unreachable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from _persistence_integration_helpers import truncate_persistence_tables
from emg_memory_graph import (
    EMPTY_GRAPH,
    EdgeDirection,
    EvidenceRef,
    EvidenceSource,
    MemoryEdge,
    MemoryGraph,
    MemoryNode,
    TemporalValidity,
)
from emg_persistence import PersistenceSettings
from emg_persistence.migrate import run_migrations
from emg_persistence.neo4j.projection import Neo4jGraphProjection
from emg_persistence.postgres import (
    DirectConnectionProvider,
    PostgresMigrationExecutor,
    PostgresRevisionRepository,
    PostgresTransactionProvider,
    connect,
)
from emg_persistence.revisions import Revision
from emg_persistence.store import PostgresNeo4jGraphStore
from emg_platform_core import GraphStore, PrincipalRef, TenantId

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
_NEO4J_URI = os.environ.get("EMG_PERSISTENCE_TEST_NEO4J_URI")
_NEO4J_USER = os.environ.get("EMG_PERSISTENCE_TEST_NEO4J_USER")
_NEO4J_PASSWORD = os.environ.get("EMG_PERSISTENCE_TEST_NEO4J_PASSWORD")

requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)
requires_both = pytest.mark.skipif(
    not (_PG_DSN and _NEO4J_URI),
    reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN and EMG_PERSISTENCE_TEST_NEO4J_URI",
)

TENANT = TenantId.of("acme")
PRINCIPAL = PrincipalRef.service("ingest")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

_CLEAR_TENANT_CYPHER = (
    "MATCH (n:MemoryNode {tenant_id: $tenant_id}) DETACH DELETE n",
    "MATCH ()-[e:MEMORY_EDGE {tenant_id: $tenant_id}]->() DELETE e",
    "MATCH (h:GraphHead {tenant_id: $tenant_id}) DELETE h",
)


def _node(
    node_id: str, *, label: str | None = None
) -> MemoryNode:  # pragma: no cover - live DB only
    evidence = EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator=f"doc-{node_id}",
        source_principal="svc-ingest",
        captured_at=NOW,
    )
    return MemoryNode(
        node_id=node_id,
        node_type="person",
        label=label if label is not None else f"Node {node_id}",
        created_at=NOW,
        updated_at=NOW,
        source="svc-ingest",
        confidence=0.9,
        evidence=(evidence,),
    )


def _edge(edge_id: str, source_id: str, target_id: str) -> MemoryEdge:  # pragma: no cover
    evidence = EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator=f"doc-{edge_id}",
        source_principal="svc-ingest",
        captured_at=NOW,
    )
    return MemoryEdge(
        edge_id=edge_id,
        edge_type="knows",
        source_id=source_id,
        target_id=target_id,
        direction=EdgeDirection.DIRECTED,
        evidence=(evidence,),
        confidence=0.8,
        validity=TemporalValidity(valid_from=NOW, valid_until=None),
        created_at=NOW,
        updated_at=NOW,
    )


def _graph(
    *nodes: MemoryNode, edges: tuple[MemoryEdge, ...] = ()
) -> MemoryGraph:  # pragma: no cover
    return MemoryGraph(nodes=tuple(nodes), edges=edges)


def _revision(  # pragma: no cover - live DB only
    graph: MemoryGraph, *, number: int, parent_hash: str | None = None
) -> Revision:
    return Revision(
        tenant=TENANT,
        revision_number=number,
        content_hash=graph.content_hash(),
        parent_hash=parent_hash,
        principal=PRINCIPAL,
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        graph_json=graph.model_dump(mode="json"),
        created_at=NOW,
    )


@pytest.fixture
def pg_settings() -> PersistenceSettings:  # pragma: no cover - live DB only
    return PersistenceSettings(postgres_dsn=_PG_DSN)


@pytest.fixture
def neo4j_settings() -> PersistenceSettings:  # pragma: no cover - live DB only
    return PersistenceSettings(
        neo4j_uri=_NEO4J_URI, neo4j_user=_NEO4J_USER, neo4j_password=_NEO4J_PASSWORD
    )


@pytest.fixture
def revision_repository(pg_settings: PersistenceSettings) -> Iterator[PostgresRevisionRepository]:
    # pragma: no cover - live DB only
    connection = connect(pg_settings)
    run_migrations(PostgresMigrationExecutor(connection))
    truncate_persistence_tables(connection)
    connection.commit()
    try:
        yield PostgresRevisionRepository(connection)
    finally:
        truncate_persistence_tables(connection)
        connection.commit()
        connection.close()


def _clear_neo4j_tenant(driver: object) -> None:  # pragma: no cover - live DB only
    with driver.session() as session:  # type: ignore[attr-defined]
        for statement in _CLEAR_TENANT_CYPHER:
            session.run(statement, {"tenant_id": TENANT.value})


@pytest.fixture
def neo4j_driver(neo4j_settings: PersistenceSettings) -> Iterator[object]:
    # pragma: no cover - live DB only
    from emg_persistence.neo4j import Neo4jMigrationExecutor, create_driver

    driver = create_driver(neo4j_settings)
    run_migrations(Neo4jMigrationExecutor(driver))
    _clear_neo4j_tenant(driver)
    try:
        yield driver
    finally:
        _clear_neo4j_tenant(driver)
        driver.close()


@pytest.fixture
def projection(neo4j_driver: object) -> Neo4jGraphProjection:  # pragma: no cover - live DB only
    return Neo4jGraphProjection(neo4j_driver)


# --------------------------------------------------------------------------
# 1. Real Neo4j apply flow (diff-based, idempotent MERGE/DELETE)
# --------------------------------------------------------------------------


@requires_both
def test_apply_persists_and_diffs_against_real_neo4j(
    projection: Neo4jGraphProjection,
) -> None:  # pragma: no cover - live DB only
    node_a, node_b = _node("a"), _node("b")
    edge = _edge("e1", "a", "b")

    g1 = _graph(node_a, node_b, edges=(edge,))
    rev1 = _revision(g1, number=1)
    assert projection.apply(
        TENANT, expected_revision=0, revision=rev1, before=EMPTY_GRAPH, after=g1
    )

    # Revision 2 removes node b (and, transitively, edge e1) -- a real diff
    # applied against the live database, not a fake.
    g2 = _graph(node_a)
    rev2 = _revision(g2, number=2, parent_hash=g1.content_hash())
    assert projection.apply(TENANT, expected_revision=1, revision=rev2, before=g1, after=g2)

    reconstructed = projection.reconstruct(TENANT)
    assert reconstructed.content_hash() == g2.content_hash()
    head = projection.get_projection_head(TENANT)
    assert head is not None
    assert head.revision_number == 2


# --------------------------------------------------------------------------
# 2. Compare-and-set with two real, concurrent driver sessions
# --------------------------------------------------------------------------


@requires_both
def test_apply_cas_with_two_concurrent_real_sessions(
    neo4j_settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB only
    from emg_persistence.neo4j import create_driver

    driver_a = create_driver(neo4j_settings)
    driver_b = create_driver(neo4j_settings)
    projection_a = Neo4jGraphProjection(driver_a)
    projection_b = Neo4jGraphProjection(driver_b)
    try:
        graph_a = _graph(_node("a"))
        graph_b = _graph(_node("b"))
        rev_a = _revision(graph_a, number=1)
        rev_b = _revision(graph_b, number=1)

        first = projection_a.apply(
            TENANT, expected_revision=0, revision=rev_a, before=EMPTY_GRAPH, after=graph_a
        )
        second = projection_b.apply(
            TENANT, expected_revision=0, revision=rev_b, before=EMPTY_GRAPH, after=graph_b
        )

        # Real Cypher-level compare-and-set (PHASE2_ARCHITECTURE.md Sec8): exactly
        # one of two racing sessions may win, regardless of which connection.
        assert {first, second} == {True, False}
        winner = projection_a if first else projection_b
        expected_graph = graph_a if first else graph_b
        head = winner.get_projection_head(TENANT)
        assert head is not None
        assert head.content_hash == expected_graph.content_hash()
    finally:
        _clear_neo4j_tenant(driver_a)
        driver_a.close()
        driver_b.close()


# --------------------------------------------------------------------------
# 3. Reconstruction with real data, including bilingual (Arabic+English)
#    content -- ADR-7 / ADR-018 UTF-8 preservation, canonical hash equality.
# --------------------------------------------------------------------------


@requires_both
def test_reconstruct_preserves_bilingual_content_and_canonical_hash(
    projection: Neo4jGraphProjection,
) -> None:  # pragma: no cover - live DB only
    arabic_node = _node("n1", label="عقدة الاختبار")
    english_node = _node("n2", label="Test Node")
    graph = _graph(arabic_node, english_node)
    revision = _revision(graph, number=1)

    projection.apply(
        TENANT, expected_revision=0, revision=revision, before=EMPTY_GRAPH, after=graph
    )
    reconstructed = projection.reconstruct(TENANT)

    assert reconstructed.content_hash() == graph.content_hash()
    labels = {node.node_id: node.label for node in reconstructed.nodes}
    assert labels["n1"] == "عقدة الاختبار"
    assert labels["n2"] == "Test Node"


# --------------------------------------------------------------------------
# 4. Catch-up projection against a real multi-revision PostgreSQL chain
# --------------------------------------------------------------------------


@requires_both
def test_catch_up_projection_replays_a_real_revision_chain(
    projection: Neo4jGraphProjection,
    revision_repository: PostgresRevisionRepository,
) -> None:  # pragma: no cover - live DB only
    nodes: list[MemoryNode] = []
    parent_hash: str | None = None
    revisions: dict[int, Revision] = {}
    for i in range(1, 4):
        nodes.append(_node(f"n{i}"))
        graph = _graph(*nodes)
        revision = _revision(graph, number=i, parent_hash=parent_hash)
        revisions[i] = revision
        if i == 1:
            revision_repository.create_first_revision(revision)
        else:
            revision_repository.append_revision(revision)
        parent_hash = graph.content_hash()

    head = revision_repository.get_head(TENANT)
    assert head is not None

    applied = projection.catch_up_projection(
        TENANT,
        load_head=lambda _t: (head.revision_number, head.content_hash),
        load_revision=lambda _t, n: revision_repository.get_revision(_t, n),
    )

    assert applied == 3
    assert projection.reconstruct(TENANT).content_hash() == head.content_hash


# --------------------------------------------------------------------------
# 5. Read-repair: projection lags a freshly-committed PostgreSQL revision
# --------------------------------------------------------------------------


@requires_both
def test_read_repair_advances_a_lagging_real_projection(
    projection: Neo4jGraphProjection,
    revision_repository: PostgresRevisionRepository,
) -> None:  # pragma: no cover - live DB only
    g1 = _graph(_node("n1"))
    rev1 = _revision(g1, number=1)
    revision_repository.create_first_revision(rev1)

    load_head = lambda _t: (  # noqa: E731
        revision_repository.get_head(_t).revision_number,
        revision_repository.get_head(_t).content_hash,
    )
    load_revision = lambda _t, n: revision_repository.get_revision(_t, n)  # noqa: E731

    # Projection catches up to revision 1 first...
    projection.catch_up_projection(TENANT, load_head=load_head, load_revision=load_revision)

    # ...then PostgreSQL advances to revision 2 while the projection lags.
    g2 = _graph(_node("n1"), _node("n2"))
    rev2 = _revision(g2, number=2, parent_hash=g1.content_hash())
    revision_repository.append_revision(rev2)

    repaired = projection.read_repair(TENANT, load_head=load_head, load_revision=load_revision)

    assert repaired.content_hash() == g2.content_hash()


# --------------------------------------------------------------------------
# 6. Rebuild projection: wipe a stale/corrupt real projection, replay clean
# --------------------------------------------------------------------------


@requires_both
def test_rebuild_projection_clears_stale_state_and_replays(
    projection: Neo4jGraphProjection,
    revision_repository: PostgresRevisionRepository,
    neo4j_driver: object,
) -> None:  # pragma: no cover - live DB only
    g1 = _graph(_node("n1"))
    rev1 = _revision(g1, number=1)
    revision_repository.create_first_revision(rev1)
    load_head = lambda _t: (rev1.revision_number, rev1.content_hash)  # noqa: E731
    load_revision = lambda _t, n: revision_repository.get_revision(_t, n)  # noqa: E731
    projection.catch_up_projection(TENANT, load_head=load_head, load_revision=load_revision)

    # Simulate real corruption: an extra node with no authoritative revision.
    with neo4j_driver.session() as session:  # type: ignore[attr-defined]
        session.run(
            "MERGE (n:MemoryNode {tenant_id: $tenant_id, node_id: 'stale'}) "
            "SET n.content_json = '{}'",
            {"tenant_id": TENANT.value},
        )

    applied = projection.rebuild_projection(
        TENANT, load_head=load_head, load_revision=load_revision
    )

    assert applied == 1
    reconstructed = projection.reconstruct(TENANT)
    assert reconstructed.content_hash() == g1.content_hash()
    assert "stale" not in {n.node_id for n in reconstructed.nodes}


# --------------------------------------------------------------------------
# 7. PostgreSQL fallback when Neo4j is genuinely unreachable (ADR-5 / Sec5.1,
#    the behavior restored by the store.py fix in this same phase).
#    Deliberately gated on Postgres only -- the whole point is Neo4j being
#    unavailable, so no live Neo4j is required to prove this.
# --------------------------------------------------------------------------


@requires_postgres
def test_store_read_falls_back_to_postgresql_when_neo4j_is_unreachable(
    pg_settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB only
    from emg_persistence.neo4j import create_driver

    connection = connect(pg_settings)
    run_migrations(PostgresMigrationExecutor(connection))
    truncate_persistence_tables(connection)
    connection.commit()
    connection.close()

    transactions = PostgresTransactionProvider(DirectConnectionProvider(pg_settings))
    # A real neo4j driver aimed at a port nothing listens on -- genuinely
    # unreachable, not a fake/mock, proving the fix against real driver
    # exception types (e.g. neo4j.exceptions.ServiceUnavailable).
    unreachable_settings = PersistenceSettings(neo4j_uri="neo4j://127.0.0.1:1")
    unreachable_projection = Neo4jGraphProjection(create_driver(unreachable_settings))
    store: GraphStore = PostgresNeo4jGraphStore(
        transactions, projection=unreachable_projection, clock=lambda: NOW
    )

    graph = _graph(_node("n1"))
    store.write(TENANT, graph, principal=PRINCIPAL)
    result = store.read(TENANT)

    assert result.content_hash() == graph.content_hash()

    connection = connect(pg_settings)
    truncate_persistence_tables(connection)
    connection.commit()
    connection.close()
