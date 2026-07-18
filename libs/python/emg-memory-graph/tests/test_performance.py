"""Performance / scale characteristics (deterministic, enterprise-scale friendly).

These are not micro-benchmarks; they assert that the documented complexity holds
in practice (linear-ish construction, O(1) lookups, BFS path over a long chain)
and complete well within a generous time budget on ordinary CI hardware.
"""

from __future__ import annotations

import time

from _mg_helpers import ASOF, edge_input, node_input
from emg_memory_graph import MemoryGraphBuilder, MemoryQueryEngine


def _chain(n: int) -> tuple:
    nodes = tuple(node_input(f"n{i}", "step", f"S{i}") for i in range(n))
    edges = tuple(edge_input("precedes", f"n{i}", f"n{i + 1}") for i in range(n - 1))
    return nodes, edges


def test_build_large_chain_is_fast() -> None:
    n = 2000
    nodes, edges = _chain(n)
    start = time.perf_counter()
    res = MemoryGraphBuilder().build(nodes=nodes, edges=edges, as_of=ASOF)
    elapsed = time.perf_counter() - start
    assert res.graph.node_count == n
    assert res.graph.edge_count == n - 1
    assert elapsed < 10.0  # generous ceiling; construction is O(N+E) + scoring


def test_lookups_constant_time() -> None:
    n = 5000
    nodes, edges = _chain(n)
    g = MemoryGraphBuilder().build(nodes=nodes, edges=edges, as_of=ASOF).graph
    start = time.perf_counter()
    for i in range(0, n, 50):
        assert g.node(f"n{i}") is not None
        assert g.has_edge(g.edges[0].edge_id)
    assert time.perf_counter() - start < 1.0


def test_shortest_path_over_long_chain() -> None:
    n = 1000
    nodes, edges = _chain(n)
    g = MemoryGraphBuilder().build(nodes=nodes, edges=edges, as_of=ASOF).graph
    q = MemoryQueryEngine(g)
    path = q.shortest_path("n0", f"n{n - 1}")
    assert path is not None
    assert path.length == n - 1


def test_incremental_build_scales() -> None:
    b = MemoryGraphBuilder()
    nodes, edges = _chain(500)
    g = b.build(nodes=nodes, edges=edges, as_of=ASOF).graph
    # extend with another disjoint chunk; should merge without rework blowups
    more = tuple(node_input(f"m{i}", "step", f"M{i}") for i in range(500))
    start = time.perf_counter()
    g2 = b.extend(g, nodes=more, as_of=ASOF).graph
    assert time.perf_counter() - start < 10.0
    assert g2.node_count == 1000


def test_content_hash_stable_across_builds() -> None:
    nodes, edges = _chain(300)
    a = MemoryGraphBuilder().build(nodes=nodes, edges=edges, as_of=ASOF).graph
    b = MemoryGraphBuilder().build(nodes=nodes, edges=edges, as_of=ASOF).graph
    assert a.content_hash() == b.content_hash()
