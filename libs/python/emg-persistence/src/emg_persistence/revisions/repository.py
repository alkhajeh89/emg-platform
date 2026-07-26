"""The revision-repository contract (Phase 2, Sprint 3).

``RevisionRepository`` is the interface over the authoritative PostgreSQL
revision log + head pointer. It owns durability and optimistic concurrency
(compare-and-set on ``graph_head``) but **not** any GraphStore, projection,
outbox, or serialization logic — those belong to later sprints. Two
implementations satisfy it: an in-memory reference
(:class:`~emg_persistence.revisions.in_memory.InMemoryRevisionRepository`) for
deterministic unit tests, and the PostgreSQL-backed
:class:`~emg_persistence.postgres.revision_repository.PostgresRevisionRepository`.

Concurrency contract: ``create_first_revision`` and ``append_revision`` are
atomic (revision insert + head update in one transaction) and raise
:class:`~emg_persistence.errors.PersistenceConflictError` when the head has moved
(or already exists), so exactly one concurrent writer wins.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from emg_platform_core import TenantId
from emg_platform_core.ports import DEFAULT_REVISION_LIST_LIMIT

from .model import Revision, RevisionHead, RevisionRecord


@runtime_checkable
class RevisionRepository(Protocol):
    """Authoritative revision log + head pointer for tenant-scoped graphs."""

    def get_head(self, tenant: TenantId) -> RevisionHead | None:
        """Return the current head for ``tenant``, or ``None`` if it has no
        revisions yet."""
        ...

    def get_revision(self, tenant: TenantId, revision_number: int) -> Revision | None:
        """Return the revision ``revision_number`` for ``tenant``, or ``None``."""
        ...

    def revision_exists(self, tenant: TenantId, revision_number: int) -> bool:
        """Whether ``tenant`` has a revision numbered ``revision_number``."""
        ...

    def revision_count(self, tenant: TenantId) -> int:
        """Number of revisions recorded for ``tenant``."""
        ...

    def tenants(self) -> tuple[TenantId, ...]:
        """Return tenants with an authoritative head, sorted by identifier."""
        ...

    def revalidate_head(self, tenant: TenantId, expected: RevisionHead) -> bool:
        """Re-read and lock ``tenant``'s head, returning whether it still
        matches ``expected``.

        Persistent implementations keep the matching row locked until their
        surrounding transaction ends. This is the no-op write-path guard: a
        receipt may be returned only when the head captured at open is still
        authoritative at commit.
        """
        ...

    def compare_and_set_head(
        self, tenant: TenantId, expected: RevisionHead | None, desired: RevisionHead
    ) -> bool:
        """Atomically move ``tenant``'s head from ``expected`` to ``desired``.

        ``expected`` is ``None`` to create the very first head (succeeds only if
        no head exists). Returns ``True`` if the head was set, ``False`` if the
        current head did not match ``expected`` (lost the race). This is the raw
        CAS primitive; it does not insert a revision row.
        """
        ...

    def create_first_revision(self, revision: Revision) -> RevisionHead:
        """Atomically insert the first revision (number 1) and its head.

        Raises:
            PersistenceConflictError: a head already exists for the tenant
                (another writer created the first revision first).
        """
        ...

    def append_revision(self, revision: Revision) -> RevisionHead:
        """Atomically insert ``revision`` and advance the head via compare-and-set
        from ``(revision_number - 1, parent_hash)`` to this revision.

        Raises:
            PersistenceConflictError: the current head is not
                ``(revision_number - 1, parent_hash)`` (the head moved).
        """
        ...

    def list_revisions(
        self,
        tenant: TenantId,
        *,
        limit: int = DEFAULT_REVISION_LIST_LIMIT,
        before_revision_number: int | None = None,
    ) -> tuple[RevisionRecord, ...]:
        """Return up to ``limit`` revision records for ``tenant``, ordered
        strictly descending by ``revision_number``.

        When ``before_revision_number`` is given, only revisions with
        ``revision_number < before_revision_number`` are eligible. Never
        includes ``graph_json`` — this is a metadata-only listing (ADR-023
        §18) and never deserializes or hash-verifies a graph snapshot.
        """
        ...
