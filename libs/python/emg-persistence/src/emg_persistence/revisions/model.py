"""Revision + head value types for the revision repository (Phase 2, Sprint 3).

Immutable models for the authoritative PostgreSQL revision log (``graph_revisions``)
and head pointer (``graph_head``) described in PHASE2_ARCHITECTURE.md Revision 3
§11. These carry no I/O and no GraphStore dependency; ``graph_json`` is an opaque
JSON payload (serialized/deserialized by later sprints — the repository only
stores and returns it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from emg_platform_core import PrincipalRef, TenantId
from pydantic import BaseModel, ConfigDict, Field

# 64-char lowercase hex SHA-256 digest (a graph content hash).
HexHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RevisionHead(BaseModel):
    """The current head pointer for one tenant: the latest revision number and
    its content hash. This is the compare-and-set anchor (§7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    revision_number: int = Field(ge=1)
    content_hash: HexHash


class Revision(BaseModel):
    """One immutable, append-only revision of a tenant's graph.

    ``content_hash`` is graph identity (non-unique — a rollback may reproduce a
    prior hash, ADR-3). ``parent_hash`` is the content hash of the revision this
    one supersedes (``None`` for the first revision). ``graph_json`` is opaque to
    this layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    revision_number: int = Field(ge=1)
    content_hash: HexHash
    parent_hash: HexHash | None = None
    principal: PrincipalRef
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    graph_json: dict[str, Any]
    created_at: datetime

    def head(self) -> RevisionHead:
        """The :class:`RevisionHead` this revision establishes when committed."""
        return RevisionHead(
            tenant=self.tenant,
            revision_number=self.revision_number,
            content_hash=self.content_hash,
        )


class RevisionRecord(BaseModel):
    """Metadata-only view of one revision, deliberately excluding ``graph_json``
    (ADR-023 §18).

    Produced by :meth:`RevisionRepository.list_revisions` so listing a tenant's
    history never deserializes a graph snapshot it may not need. Every field is
    a direct, lossless projection of the corresponding :class:`Revision` field.
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
