"""Read-only historical revision access — a companion to GraphStore (ADR-023).

``GraphRevisionReader`` is deliberately separate from ``GraphStore``: it has no
write methods, and an adapter may implement ``GraphStore`` without implementing
this port. Both existing adapters (``InMemoryGraphStore``,
``PostgresNeo4jGraphStore``) implement both Protocols. A caller (e.g.
``KnowledgeGraphApplication``) that is configured without a
``GraphRevisionReader`` must reject history operations itself rather than
assume one is always available.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..identity import TenantId
from .revision_metadata import HistoricalGraphRevision, RevisionMetadata

DEFAULT_REVISION_LIST_LIMIT = 50
MAX_REVISION_LIST_LIMIT = 200


@runtime_checkable
class GraphRevisionReader(Protocol):
    """Read-only access to a tenant's immutable revision history."""

    def list_revisions(
        self,
        tenant: TenantId,
        *,
        limit: int = DEFAULT_REVISION_LIST_LIMIT,
        before_revision_number: int | None = None,
    ) -> tuple[RevisionMetadata, ...]:
        """Return up to ``limit`` revisions for ``tenant``, newest first.

        Ordered strictly descending by ``revision_number``. When
        ``before_revision_number`` is given, only revisions with
        ``revision_number < before_revision_number`` are eligible (paging
        strictly further into the past). ``limit`` must be in
        ``[1, MAX_REVISION_LIST_LIMIT]``. Never deserializes ``graph_json``;
        returns an empty tuple for a tenant with no (matching) revisions.
        """
        ...

    def read_revision(self, tenant: TenantId, revision_number: int) -> HistoricalGraphRevision:
        """Return the exact metadata and MemoryGraph for one revision.

        Raises ``RevisionNotFoundError`` if ``tenant`` has no revision numbered
        ``revision_number``. Raises ``SnapshotIntegrityError`` if the stored
        payload's recomputed content hash does not match the stored
        ``content_hash``. Never raises a driver/database exception directly.
        """
        ...
