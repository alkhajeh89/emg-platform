"""Immutable graph versioning + snapshot comparison (FEAT-05-6, Deliverable 9).

Every modification produces a new, immutable `GraphRevision` in an append-only
`GraphHistory`; nothing is ever overwritten. Revisions are content-addressed
(`content_hash`) and chained (`parent_id`), so any past graph can be reconstructed
and any two revisions compared.

  * ``GraphHistory.commit(graph, at)`` → a new history with an appended revision
    (idempotent: committing an unchanged graph returns the same history).
  * ``GraphHistory.reconstruct(revision_id)`` → the exact `MemoryGraph` at a revision.
  * ``diff_graphs(a, b)`` → the added/removed/modified nodes and edges (O(N + E)).

Complexity: ``commit`` is O(N + E) (content hash); ``diff_graphs`` is O(N + E).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import RevisionError
from .graph import MemoryGraph
from .ids import revision_id_for
from .labels import SafeLabel
from .limits import MAX_REVISION_NUMBER


class GraphDiff(BaseModel):
    """The immutable difference between two graph snapshots (ids only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    added_nodes: tuple[SafeLabel, ...] = ()
    removed_nodes: tuple[SafeLabel, ...] = ()
    modified_nodes: tuple[SafeLabel, ...] = ()
    added_edges: tuple[SafeLabel, ...] = ()
    removed_edges: tuple[SafeLabel, ...] = ()
    modified_edges: tuple[SafeLabel, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.added_nodes
            or self.removed_nodes
            or self.modified_nodes
            or self.added_edges
            or self.removed_edges
            or self.modified_edges
        )


def diff_graphs(before: MemoryGraph, after: MemoryGraph) -> GraphDiff:
    """Compute the node/edge-level difference from `before` to `after`. O(N + E)."""
    before_nodes = {n.node_id: n.model_dump_json() for n in before.nodes}
    after_nodes = {n.node_id: n.model_dump_json() for n in after.nodes}
    before_edges = {e.edge_id: e.model_dump_json() for e in before.edges}
    after_edges = {e.edge_id: e.model_dump_json() for e in after.edges}

    added_n = sorted(after_nodes.keys() - before_nodes.keys())
    removed_n = sorted(before_nodes.keys() - after_nodes.keys())
    modified_n = sorted(
        k for k in before_nodes.keys() & after_nodes.keys() if before_nodes[k] != after_nodes[k]
    )
    added_e = sorted(after_edges.keys() - before_edges.keys())
    removed_e = sorted(before_edges.keys() - after_edges.keys())
    modified_e = sorted(
        k for k in before_edges.keys() & after_edges.keys() if before_edges[k] != after_edges[k]
    )
    return GraphDiff(
        added_nodes=tuple(added_n),
        removed_nodes=tuple(removed_n),
        modified_nodes=tuple(modified_n),
        added_edges=tuple(added_e),
        removed_edges=tuple(removed_e),
        modified_edges=tuple(modified_e),
    )


class GraphRevision(BaseModel):
    """One immutable, content-addressed revision of the whole graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: SafeLabel
    revision_number: int = Field(ge=1, le=MAX_REVISION_NUMBER)
    parent_id: SafeLabel | None
    created_at: datetime
    content_hash: SafeLabel
    graph: MemoryGraph

    def diff_from(self, other: GraphRevision) -> GraphDiff:
        """The diff from `other`'s graph to this revision's graph."""
        return diff_graphs(other.graph, self.graph)


class GraphHistory(BaseModel):
    """An immutable, append-only chain of graph revisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revisions: tuple[GraphRevision, ...] = ()

    @field_validator("revisions")
    @classmethod
    def _validate_chain(cls, value: tuple[GraphRevision, ...]) -> tuple[GraphRevision, ...]:
        prev: GraphRevision | None = None
        for rev in value:
            expected_num = 1 if prev is None else prev.revision_number + 1
            expected_parent = None if prev is None else prev.revision_id
            if rev.revision_number != expected_num:
                raise ValueError("revision_number must increase by 1 from the parent")
            if rev.parent_id != expected_parent:
                raise ValueError("parent_id must reference the immediately prior revision")
            prev = rev
        return value

    def latest(self) -> GraphRevision | None:
        return self.revisions[-1] if self.revisions else None

    def get(self, revision_id: str) -> GraphRevision | None:
        for rev in self.revisions:
            if rev.revision_id == revision_id:
                return rev
        return None

    def at(self, revision_number: int) -> GraphRevision | None:
        for rev in self.revisions:
            if rev.revision_number == revision_number:
                return rev
        return None

    def reconstruct(self, revision_id: str) -> MemoryGraph:
        """The exact graph snapshot at a revision."""
        rev = self.get(revision_id)
        if rev is None:
            raise RevisionError(f"unknown revision: {revision_id}")
        return rev.graph

    def diff(self, from_revision_id: str, to_revision_id: str) -> GraphDiff:
        """The diff between two revisions by id."""
        a = self.get(from_revision_id)
        b = self.get(to_revision_id)
        if a is None or b is None:
            raise RevisionError("unknown revision id in diff")
        return diff_graphs(a.graph, b.graph)

    def commit(self, graph: MemoryGraph, *, at: datetime) -> GraphHistory:
        """Append a new revision for `graph`. Idempotent: if `graph` is identical
        (same content hash) to the latest revision, the history is returned
        unchanged (no empty revisions)."""
        content_hash = graph.content_hash()
        prev = self.latest()
        if prev is not None and prev.content_hash == content_hash:
            return self
        revision = GraphRevision(
            revision_id=revision_id_for(content_hash, prev.revision_id if prev else None),
            revision_number=1 if prev is None else prev.revision_number + 1,
            parent_id=prev.revision_id if prev else None,
            created_at=at,
            content_hash=content_hash,
            graph=graph,
        )
        return GraphHistory(revisions=(*self.revisions, revision))


EMPTY_HISTORY = GraphHistory()
