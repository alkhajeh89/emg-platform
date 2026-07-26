"""Canonical, persistence-independent revision metadata (ADR-023).

``RevisionMetadata`` mirrors ``emg_persistence.revisions.model.Revision``'s
canonical fields exactly, minus ``graph_json`` — it is the one revision shape
permitted to cross the ``GraphRevisionReader`` port boundary into application
services. ``emg_persistence.revisions.Revision`` itself must never cross that
boundary (Freeze §32; ADR-023 §10).

``HistoricalGraphRevision`` binds one ``RevisionMetadata`` to the exact
``MemoryGraph`` it describes, for callers that need the full historical
snapshot (read, compare, restore) rather than just its metadata (list).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from emg_memory_graph import MemoryGraph
from pydantic import BaseModel, ConfigDict, Field

from ..identity import PrincipalRef, TenantId

# 64-char lowercase hex SHA-256 digest (a graph content hash). Mirrors
# emg_persistence.revisions.model.HexHash exactly; redefined here so
# platform-core has no dependency on emg-persistence.
HexHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RevisionMetadata(BaseModel):
    """Canonical, immutable metadata for one committed tenant revision.

    ``parent_hash`` is ``None`` if and only if ``revision_number == 1`` — the
    adapter producing this value is responsible for that invariant (mirroring
    ``emg_persistence.revisions.model.Revision``, which leaves the same
    invariant to its producer rather than a field validator).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    revision_number: int = Field(ge=1)
    content_hash: HexHash
    parent_hash: HexHash | None = None
    principal: PrincipalRef
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    created_at: datetime


class HistoricalGraphRevision(BaseModel):
    """One fully-read historical revision: metadata plus its exact graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: RevisionMetadata
    graph: MemoryGraph
