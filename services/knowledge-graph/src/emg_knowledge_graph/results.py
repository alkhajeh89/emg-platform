"""Immutable results returned by knowledge-graph application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from emg_memory_graph import GraphDiff, MemoryGraph
from emg_platform_core import PrincipalRef, TenantId


@dataclass(frozen=True, slots=True)
class BuildRevisionResult:
    """Application DTO derived from a committed receipt and build statistics."""

    tenant: TenantId
    principal: PrincipalRef
    content_hash: str
    node_count: int
    edge_count: int
    nodes_created: int
    edges_created: int
    node_inputs_merged: int
    edge_inputs_merged: int


@dataclass(frozen=True, slots=True)
class RevisionSummary:
    """Canonical per-revision list/read item (ADR-023 §10, §12).

    A thin application-layer projection of the platform-core
    ``RevisionMetadata`` type — kept as its own type so the service package
    never exposes a platform-core (or persistence) type directly on its public
    surface."""

    tenant: TenantId
    revision_number: int
    content_hash: str
    parent_hash: str | None
    principal: PrincipalRef
    node_count: int
    edge_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RevisionDetails:
    """One fully-read historical revision: summary plus its exact graph
    (ADR-023 §10, §12)."""

    summary: RevisionSummary
    graph: MemoryGraph


@dataclass(frozen=True, slots=True)
class RevisionDiff:
    """The diff between two of a tenant's revisions (ADR-023 §12, §14).

    Wraps ``emg_memory_graph.versioning.GraphDiff`` unchanged, adding only
    tenant/revision context — no diff logic is duplicated here."""

    tenant: TenantId
    from_revision_number: int
    to_revision_number: int
    diff: GraphDiff


@dataclass(frozen=True, slots=True)
class RestoreRevisionResult:
    """Application DTO derived from a restore commit's receipt (ADR-023 §15,
    §16). ``revision_created`` is ``False`` for a no-op restore (restoring
    content identical to the current head); ``revision_number``/
    ``committed_at`` then identify the existing head, not a new commit."""

    tenant: TenantId
    principal: PrincipalRef
    source_revision_number: int
    revision_number: int
    content_hash: str
    node_count: int
    edge_count: int
    committed_at: datetime
    revision_created: bool
