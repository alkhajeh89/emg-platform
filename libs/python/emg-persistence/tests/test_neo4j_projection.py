"""Unit tests for ``Neo4jGraphProjection`` — apply/CAS/reconstruct/catch-up/
read-repair, plus serialization and validation branches — using the fake
in-memory Neo4j driver (``_neo4j_fakes.py``) instead of a live database.

These close the coverage gap identified during the Outbox Event Persistence
inspection: prior to this file, ``neo4j/projection.py`` had 20% coverage and
no test exercised its control flow at all (the existing integration suite
states "Neo4j is deliberately absent from the entire suite"). Real
Neo4j-backed integration tests are added separately
(``tests/integration/test_projection_integration.py``); these are pure unit
tests that need no live database.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from _neo4j_fakes import ExplodingDriver, FakeNeo4jDriver, _FakeNeo4jStore
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
from emg_persistence.errors import PersistenceError
from emg_persistence.neo4j.projection import (
    Neo4jGraphProjection,
    _deserialize_edge,
    _deserialize_node,
    _edge_row,
    _node_row,
)
from emg_persistence.revisions import Revision
from emg_platform_core import PrincipalRef, TenantId

TENANT = TenantId.of("acme")
OTHER_TENANT = TenantId.of("globex")
PRINCIPAL = PrincipalRef.service("ingest")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _node(node_id: str = "n1") -> MemoryNode:
    evidence = EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator=f"doc-{node_id}",
        source_principal="svc-ingest",
        captured_at=NOW,
    )
    return MemoryNode(
        node_id=node_id,
        node_type="person",
        label=f"Node {node_id}",
        created_at=NOW,
        updated_at=NOW,
        source="svc-ingest",
        confidence=0.9,
        evidence=(evidence,),
    )


def _edge(edge_id: str, source_id: str, target_id: str) -> MemoryEdge:
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


def _graph(*nodes: MemoryNode, edges: tuple[MemoryEdge, ...] = ()) -> MemoryGraph:
    return MemoryGraph(nodes=tuple(nodes), edges=edges)


def _revision(graph: MemoryGraph, *, number: int, parent_hash: str | None = None) -> Revision:
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


# --------------------------------------------------------------------------
# Serialization / deserialization — pure functions, no driver needed at all.
# --------------------------------------------------------------------------


def test_node_row_round_trips_through_deserialize() -> None:
    node = _node("n1")
    row = _node_row(TENANT, node)
    assert row["tenant_id"] == TENANT.value
    assert row["node_id"] == "n1"
    restored = _deserialize_node(row["content_json"])
    assert restored == node


def test_edge_row_round_trips_through_deserialize() -> None:
    node_a, node_b = _node("a"), _node("b")
    edge = _edge("e1", "a", "b")
    row = _edge_row(TENANT, edge)
    assert row["source_id"] == "a"
    assert row["target_id"] == "b"
    restored = _deserialize_edge(row["content_json"])
    assert restored == edge
    # Round-tripping through the projection preserves the graph's canonical
    # content_hash (PHASE2_ARCHITECTURE.md §6 — semantic, not byte, equality).
    original_graph = _graph(node_a, node_b, edges=(edge,))
    rebuilt_graph = MemoryGraph(nodes=(node_a, node_b), edges=(restored,))
    assert original_graph.content_hash() == rebuilt_graph.content_hash()


def test_deserialize_node_accepts_dict_or_json_string() -> None:
    node = _node("n1")
    row = _node_row(TENANT, node)
    from_string = _deserialize_node(row["content_json"])
    from_dict = _deserialize_node(node.model_dump(mode="json"))
    assert from_string == from_dict == node


# --------------------------------------------------------------------------
# get_projection_head
# --------------------------------------------------------------------------


def test_get_projection_head_returns_none_for_unprojected_tenant() -> None:
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    assert projection.get_projection_head(TENANT) is None


def test_get_projection_head_reflects_store_state() -> None:
    store = _FakeNeo4jStore()
    store.heads[TENANT.value] = {"revision_number": 3, "content_hash": "a" * 64}
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    head = projection.get_projection_head(TENANT)
    assert head is not None
    assert head.revision_number == 3
    assert head.content_hash == "a" * 64


# --------------------------------------------------------------------------
# apply — validation branches (no driver interaction on failure)
# --------------------------------------------------------------------------


def test_apply_rejects_tenant_mismatch_without_touching_driver() -> None:
    poison = ExplodingDriver()
    projection = Neo4jGraphProjection(poison)
    revision = _revision(_graph(_node()), number=1)
    with pytest.raises(PersistenceError, match="does not match apply tenant"):
        projection.apply(
            OTHER_TENANT,
            expected_revision=0,
            revision=revision,
            before=EMPTY_GRAPH,
            after=_graph(_node()),
        )
    assert poison.touched is False


def test_apply_rejects_non_successor_revision_without_touching_driver() -> None:
    poison = ExplodingDriver()
    projection = Neo4jGraphProjection(poison)
    revision = _revision(_graph(_node()), number=5)
    with pytest.raises(PersistenceError, match="not the successor"):
        projection.apply(
            TENANT,
            expected_revision=0,
            revision=revision,
            before=EMPTY_GRAPH,
            after=_graph(_node()),
        )
    assert poison.touched is False


def test_apply_rejects_hash_mismatch_without_touching_driver() -> None:
    poison = ExplodingDriver()
    projection = Neo4jGraphProjection(poison)
    graph = _graph(_node())
    revision = _revision(graph, number=1)
    with pytest.raises(PersistenceError, match="content_hash does not match"):
        projection.apply(
            TENANT,
            expected_revision=0,
            revision=revision,
            before=EMPTY_GRAPH,
            after=_graph(_node("different-node")),  # hash won't match `revision`
        )
    assert poison.touched is False


# --------------------------------------------------------------------------
# apply — happy path, CAS hit / miss, driver-exception wrapping
# --------------------------------------------------------------------------


def test_apply_first_revision_creates_head_and_nodes() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    graph = _graph(_node("n1"))
    revision = _revision(graph, number=1)

    advanced = projection.apply(
        TENANT, expected_revision=0, revision=revision, before=EMPTY_GRAPH, after=graph
    )

    assert advanced is True
    assert store.heads[TENANT.value]["revision_number"] == 1
    assert (TENANT.value, "n1") in store.nodes


def test_apply_is_idempotent_diff_based_merge_and_delete() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    node_a, node_b = _node("a"), _node("b")
    edge = _edge("e1", "a", "b")

    g0 = EMPTY_GRAPH
    g1 = _graph(node_a, node_b, edges=(edge,))
    rev1 = _revision(g1, number=1)
    assert projection.apply(TENANT, expected_revision=0, revision=rev1, before=g0, after=g1)

    # Revision 2 removes node b (and, transitively, edge e1).
    g2 = _graph(node_a)
    rev2 = _revision(g2, number=2, parent_hash=g1.content_hash())
    assert projection.apply(TENANT, expected_revision=1, revision=rev2, before=g1, after=g2)

    assert (TENANT.value, "a") in store.nodes
    assert (TENANT.value, "b") not in store.nodes
    assert (TENANT.value, "e1") not in store.edges
    assert store.heads[TENANT.value]["revision_number"] == 2


def test_apply_cas_miss_when_another_repairer_already_advanced() -> None:
    """Two racing repairers both diff against revision 0; only one may win
    the compare-and-set (PHASE2_ARCHITECTURE.md §8)."""
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    graph_a = _graph(_node("a"))
    graph_b = _graph(_node("b"))
    rev_a = _revision(graph_a, number=1)
    rev_b = _revision(graph_b, number=1)

    first = projection.apply(
        TENANT, expected_revision=0, revision=rev_a, before=EMPTY_GRAPH, after=graph_a
    )
    second = projection.apply(
        TENANT, expected_revision=0, revision=rev_b, before=EMPTY_GRAPH, after=graph_b
    )

    assert first is True
    assert second is False  # CAS miss: head already moved to revision 1
    assert store.heads[TENANT.value]["content_hash"] == graph_a.content_hash()


def test_apply_wraps_driver_exceptions_as_persistence_error() -> None:
    projection = Neo4jGraphProjection(ExplodingDriver())
    graph = _graph(_node())
    revision = _revision(graph, number=1)
    with pytest.raises(PersistenceError, match="Neo4j projection apply failed"):
        projection.apply(
            TENANT, expected_revision=0, revision=revision, before=EMPTY_GRAPH, after=graph
        )


def test_apply_does_not_double_wrap_a_persistence_error_raised_mid_transaction() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    graph = _graph(_node())
    revision = _revision(graph, number=1)
    store.explode = PersistenceError("already a persistence error")

    with pytest.raises(PersistenceError, match="already a persistence error"):
        projection.apply(
            TENANT, expected_revision=0, revision=revision, before=EMPTY_GRAPH, after=graph
        )


def test_apply_rolls_back_and_wraps_a_mid_transaction_failure() -> None:
    """A failure after the transaction has begun (e.g. mid MERGE) must roll
    back and still surface as PersistenceError, not leak the raw driver
    exception (§9 / IMPLEMENTATION_RULES.md exception-hierarchy rule)."""
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    graph = _graph(_node())
    revision = _revision(graph, number=1)
    store.explode = RuntimeError("simulated mid-transaction failure")

    with pytest.raises(PersistenceError, match="Neo4j projection apply failed"):
        projection.apply(
            TENANT, expected_revision=0, revision=revision, before=EMPTY_GRAPH, after=graph
        )


# --------------------------------------------------------------------------
# reconstruct
# --------------------------------------------------------------------------


def test_reconstruct_empty_tenant_returns_empty_graph() -> None:
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    assert projection.reconstruct(TENANT) == EMPTY_GRAPH


def test_reconstruct_matches_authoritative_content_hash() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    node_a, node_b = _node("a"), _node("b")
    edge = _edge("e1", "a", "b")
    graph = _graph(node_a, node_b, edges=(edge,))
    revision = _revision(graph, number=1)
    projection.apply(
        TENANT, expected_revision=0, revision=revision, before=EMPTY_GRAPH, after=graph
    )

    rebuilt = projection.reconstruct(TENANT)

    assert rebuilt.content_hash() == graph.content_hash()


def test_reconstruct_wraps_malformed_content_json_as_persistence_error() -> None:
    store = _FakeNeo4jStore()
    store.nodes[(TENANT.value, "broken")] = {
        "tenant_id": TENANT.value,
        "node_id": "broken",
        "content_json": "{not valid json",
    }
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    with pytest.raises(PersistenceError, match="failed to reconstruct"):
        projection.reconstruct(TENANT)


def test_reconstruct_wraps_driver_exceptions_as_persistence_error() -> None:
    projection = Neo4jGraphProjection(ExplodingDriver())
    with pytest.raises(PersistenceError, match="Neo4j projection read failed"):
        projection.reconstruct(TENANT)


# --------------------------------------------------------------------------
# catch_up_projection / read_repair / rebuild_projection / validate_projection
# --------------------------------------------------------------------------


def _revision_chain(n: int) -> dict[int, Revision]:
    """A chain of ``n`` revisions, each adding one more node than the last."""
    revisions: dict[int, Revision] = {}
    nodes: list[MemoryNode] = []
    parent_hash: str | None = None
    for i in range(1, n + 1):
        nodes.append(_node(f"n{i}"))
        graph = _graph(*nodes)
        revisions[i] = _revision(graph, number=i, parent_hash=parent_hash)
        parent_hash = graph.content_hash()
    return revisions


def test_catch_up_projection_returns_zero_when_no_authoritative_head() -> None:
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    applied = projection.catch_up_projection(
        TENANT, load_head=lambda _t: None, load_revision=lambda _t, _n: None
    )
    assert applied == 0


def test_catch_up_projection_replays_multiple_pending_revisions() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(3)
    head_revision = revisions[3]

    applied = projection.catch_up_projection(
        TENANT,
        load_head=lambda _t: (head_revision.revision_number, head_revision.content_hash),
        load_revision=lambda _t, n: revisions.get(n),
    )

    assert applied == 3
    assert store.heads[TENANT.value]["content_hash"] == head_revision.content_hash
    reconstructed = projection.reconstruct(TENANT)
    assert reconstructed.content_hash() == head_revision.content_hash


def test_catch_up_projection_is_idempotent_on_reinvocation() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(2)
    head_revision = revisions[2]
    load_head = lambda _t: (head_revision.revision_number, head_revision.content_hash)  # noqa: E731
    load_revision = lambda _t, n: revisions.get(n)  # noqa: E731

    first = projection.catch_up_projection(TENANT, load_head=load_head, load_revision=load_revision)
    second = projection.catch_up_projection(
        TENANT, load_head=load_head, load_revision=load_revision
    )

    assert first == 2
    assert second == 2  # already at head — no-op, no error


def test_catch_up_projection_raises_on_missing_revision() -> None:
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    with pytest.raises(PersistenceError, match="missing revision"):
        projection.catch_up_projection(
            TENANT, load_head=lambda _t: (1, "a" * 64), load_revision=lambda _t, _n: None
        )


def test_catch_up_projection_raises_when_an_earlier_revision_is_missing() -> None:
    """``before`` is computed from an earlier revision when the projection is
    already partway caught up (current_rev > 0) — that earlier revision must
    itself be loadable, or catch-up must fail loudly rather than guess."""
    store = _FakeNeo4jStore()
    store.heads[TENANT.value] = {"revision_number": 1, "content_hash": "a" * 64}
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(2)  # revisions[1], revisions[2] available...
    incomplete = {2: revisions[2]}  # ...but revision 1 ("before") is missing here.

    with pytest.raises(PersistenceError, match="missing revision 1"):
        projection.catch_up_projection(
            TENANT,
            load_head=lambda _t: (2, revisions[2].content_hash),
            load_revision=lambda _t, n: incomplete.get(n),
        )


def test_read_repair_returns_empty_graph_for_never_projected_tenant() -> None:
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    graph = projection.read_repair(
        TENANT, load_head=lambda _t: None, load_revision=lambda _t, _n: None
    )
    assert graph == EMPTY_GRAPH


def test_read_repair_reconstructs_at_authoritative_head() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(2)
    head_revision = revisions[2]

    graph = projection.read_repair(
        TENANT,
        load_head=lambda _t: (head_revision.revision_number, head_revision.content_hash),
        load_revision=lambda _t, n: revisions.get(n),
    )

    assert graph.content_hash() == head_revision.content_hash


def test_read_repair_raises_on_projection_hash_mismatch() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(1)
    # load_head reports a hash that will never match anything reconstructable —
    # simulates authoritative/projection divergence (corruption).
    with pytest.raises(PersistenceError, match="projection hash mismatch"):
        projection.read_repair(
            TENANT,
            load_head=lambda _t: (1, "f" * 64),
            load_revision=lambda _t, n: revisions.get(n),
        )


def test_rebuild_projection_clears_then_replays_from_scratch() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(2)
    head_revision = revisions[2]
    load_head = lambda _t: (head_revision.revision_number, head_revision.content_hash)  # noqa: E731
    load_revision = lambda _t, n: revisions.get(n)  # noqa: E731

    projection.catch_up_projection(TENANT, load_head=load_head, load_revision=load_revision)
    # Simulate a stale/corrupt projection with an extra node not in any
    # authoritative revision, then rebuild — it must not survive the rebuild.
    store.nodes[(TENANT.value, "stale")] = _node_row(TENANT, _node("stale"))

    applied = projection.rebuild_projection(
        TENANT, load_head=load_head, load_revision=load_revision
    )

    assert applied == 2
    assert (TENANT.value, "stale") not in store.nodes
    assert projection.reconstruct(TENANT).content_hash() == head_revision.content_hash


def test_validate_projection_true_when_absent_on_both_sides() -> None:
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    assert projection.validate_projection(TENANT, load_head=lambda _t: None) is True


def test_validate_projection_false_when_projection_missing_but_head_exists() -> None:
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    assert projection.validate_projection(TENANT, load_head=lambda _t: (1, "a" * 64)) is False


def test_validate_projection_true_after_successful_catch_up() -> None:
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(1)
    head_revision = revisions[1]
    load_head = lambda _t: (head_revision.revision_number, head_revision.content_hash)  # noqa: E731
    projection.catch_up_projection(
        TENANT, load_head=load_head, load_revision=lambda _t, n: revisions.get(n)
    )

    assert projection.validate_projection(TENANT, load_head=load_head) is True


def test_validate_projection_false_on_revision_number_mismatch() -> None:
    store = _FakeNeo4jStore()
    store.heads[TENANT.value] = {"revision_number": 1, "content_hash": "a" * 64}
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    assert projection.validate_projection(TENANT, load_head=lambda _t: (2, "a" * 64)) is False


def test_validate_projection_false_when_reconstruct_fails() -> None:
    store = _FakeNeo4jStore()
    store.heads[TENANT.value] = {"revision_number": 1, "content_hash": "a" * 64}
    store.nodes[(TENANT.value, "broken")] = {
        "tenant_id": TENANT.value,
        "node_id": "broken",
        "content_json": "{not valid json",
    }
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    assert projection.validate_projection(TENANT, load_head=lambda _t: (1, "a" * 64)) is False


def test_catch_up_projection_continues_after_a_lost_cas_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the internal ``apply`` call reports a CAS miss (another repairer
    won concurrently), the loop must retry rather than give up (§8)."""
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(1)
    head_revision = revisions[1]
    real_apply = projection.apply
    calls = {"n": 0}

    def flaky_apply(*args: object, **kwargs: object) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            return False  # simulate a concurrent repairer winning the CAS
        return real_apply(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr(projection, "apply", flaky_apply)

    applied = projection.catch_up_projection(
        TENANT,
        load_head=lambda _t: (head_revision.revision_number, head_revision.content_hash),
        load_revision=lambda _t, n: revisions.get(n),
    )

    assert applied == 1
    assert calls["n"] == 2


def test_catch_up_projection_raises_on_malformed_revision_graph_json() -> None:
    bad_revision = Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash="a" * 64,
        principal=PRINCIPAL,
        node_count=0,
        edge_count=0,
        graph_json={"nodes": "not-a-list", "edges": []},
        created_at=NOW,
    )
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    with pytest.raises(PersistenceError, match="invalid graph snapshot"):
        projection.catch_up_projection(
            TENANT, load_head=lambda _t: (1, "a" * 64), load_revision=lambda _t, _n: bad_revision
        )


def test_catch_up_projection_raises_on_revision_content_hash_mismatch() -> None:
    graph = _graph(_node())
    mismatched_revision = Revision(
        tenant=TENANT,
        revision_number=1,
        content_hash="f" * 64,  # does not match `graph`'s real content_hash
        principal=PRINCIPAL,
        node_count=graph.node_count,
        edge_count=graph.edge_count,
        graph_json=graph.model_dump(mode="json"),
        created_at=NOW,
    )
    projection = Neo4jGraphProjection(FakeNeo4jDriver())
    with pytest.raises(PersistenceError, match="hash mismatch"):
        projection.catch_up_projection(
            TENANT,
            load_head=lambda _t: (1, "f" * 64),
            load_revision=lambda _t, _n: mismatched_revision,
        )


def test_run_write_wraps_a_plain_driver_exception() -> None:
    store = _FakeNeo4jStore()
    revisions = _revision_chain(1)
    head_revision = revisions[1]
    load_head = lambda _t: (head_revision.revision_number, head_revision.content_hash)  # noqa: E731
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    projection.catch_up_projection(
        TENANT, load_head=load_head, load_revision=lambda _t, n: revisions.get(n)
    )

    store.explode = RuntimeError("simulated write failure")
    with pytest.raises(PersistenceError, match="Neo4j projection write failed"):
        projection.rebuild_projection(
            TENANT, load_head=load_head, load_revision=lambda _t, n: revisions.get(n)
        )


def test_read_repair_returns_empty_graph_if_head_vanishes_after_catch_up() -> None:
    """A defensive branch: if the authoritative head becomes unavailable
    between catch-up completing and the post-catch-up re-check, read_repair
    degrades to EMPTY_GRAPH rather than raising."""
    store = _FakeNeo4jStore()
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    revisions = _revision_chain(1)
    head_revision = revisions[1]
    calls = {"n": 0}

    def flaky_load_head(_tenant: TenantId) -> tuple[int, str] | None:
        calls["n"] += 1
        # First call (inside catch_up_projection) succeeds; second call
        # (read_repair's own post-catch-up re-check) reports head is gone.
        return (
            (head_revision.revision_number, head_revision.content_hash) if calls["n"] == 1 else None
        )

    graph = projection.read_repair(
        TENANT, load_head=flaky_load_head, load_revision=lambda _t, n: revisions.get(n)
    )

    assert graph == EMPTY_GRAPH


def test_run_read_does_not_double_wrap_a_persistence_error() -> None:
    store = _FakeNeo4jStore()
    store.explode = PersistenceError("already a persistence error")
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    with pytest.raises(PersistenceError, match="already a persistence error"):
        projection.reconstruct(TENANT)


def test_run_write_does_not_double_wrap_a_persistence_error() -> None:
    store = _FakeNeo4jStore()
    revisions = _revision_chain(1)
    head_revision = revisions[1]
    load_head = lambda _t: (head_revision.revision_number, head_revision.content_hash)  # noqa: E731
    projection = Neo4jGraphProjection(FakeNeo4jDriver(store))
    projection.catch_up_projection(
        TENANT, load_head=load_head, load_revision=lambda _t, n: revisions.get(n)
    )

    store.explode = PersistenceError("already a persistence error")
    with pytest.raises(PersistenceError, match="already a persistence error"):
        projection.rebuild_projection(
            TENANT, load_head=load_head, load_revision=lambda _t, n: revisions.get(n)
        )
