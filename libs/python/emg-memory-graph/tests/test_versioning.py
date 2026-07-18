"""Immutable graph versioning + diff (Deliverable 9)."""

from __future__ import annotations

import pytest
from _mg_helpers import ASOF, node_input
from emg_memory_graph import (
    EMPTY_HISTORY,
    GraphHistory,
    MemoryGraphBuilder,
    RevisionError,
    diff_graphs,
)
from pydantic import ValidationError


def _graphs() -> tuple:
    b = MemoryGraphBuilder()
    g0 = b.build(nodes=(node_input("a", "person", "A"),), as_of=ASOF).graph
    g1 = b.extend(g0, nodes=(node_input("b", "person", "B"),), as_of=ASOF).graph
    return g0, g1


def test_commit_creates_revisions() -> None:
    g0, g1 = _graphs()
    h = EMPTY_HISTORY.commit(g0, at=ASOF).commit(g1, at=ASOF)
    assert len(h.revisions) == 2
    assert [r.revision_number for r in h.revisions] == [1, 2]
    assert h.revisions[1].parent_id == h.revisions[0].revision_id
    assert h.latest().revision_number == 2  # type: ignore[union-attr]


def test_commit_idempotent_on_unchanged_graph() -> None:
    g0, _ = _graphs()
    h = EMPTY_HISTORY.commit(g0, at=ASOF)
    h2 = h.commit(g0, at=ASOF)
    assert len(h2.revisions) == 1  # no empty revision


def test_reconstruct_and_get_at() -> None:
    g0, g1 = _graphs()
    h = EMPTY_HISTORY.commit(g0, at=ASOF).commit(g1, at=ASOF)
    r0 = h.revisions[0]
    assert h.reconstruct(r0.revision_id).content_hash() == g0.content_hash()
    assert h.at(2).content_hash == g1.content_hash()  # type: ignore[union-attr]
    assert h.get("nope") is None
    with pytest.raises(RevisionError):
        h.reconstruct("nope")


def test_diff_between_revisions() -> None:
    g0, g1 = _graphs()
    h = EMPTY_HISTORY.commit(g0, at=ASOF).commit(g1, at=ASOF)
    d = h.diff(h.revisions[0].revision_id, h.revisions[1].revision_id)
    assert d.added_nodes == ("b",)
    assert not d.is_empty
    with pytest.raises(RevisionError):
        h.diff("x", "y")


def test_diff_graphs_modified_and_removed() -> None:
    g0, g1 = _graphs()
    empty = diff_graphs(g0, g0)
    assert empty.is_empty
    d = diff_graphs(g1, g0)
    assert d.removed_nodes == ("b",)


def test_revision_chain_validation() -> None:
    g0, g1 = _graphs()
    h = EMPTY_HISTORY.commit(g0, at=ASOF)
    rev0 = h.revisions[0]
    bad = rev0.model_copy(update={"revision_number": 5})
    with pytest.raises(ValidationError):
        GraphHistory(revisions=(bad,))
