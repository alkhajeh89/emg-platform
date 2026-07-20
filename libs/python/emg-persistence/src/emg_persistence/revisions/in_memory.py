"""In-memory reference RevisionRepository (Phase 2, Sprint 3).

A deterministic, thread-safe implementation of the :class:`RevisionRepository`
contract used to unit-test the compare-and-set / first-revision / atomicity
semantics without a database (and as a reusable fake for later sprints). It is
**not** a persistence backend and **not** a GraphStore — it models the same
concurrency contract the PostgreSQL repository provides, using a reentrant lock
for atomicity.
"""

from __future__ import annotations

import threading

from emg_platform_core import TenantId

from ..errors import PersistenceConflictError
from .model import Revision, RevisionHead


class InMemoryRevisionRepository:
    """A lock-guarded, in-memory :class:`RevisionRepository`."""

    def __init__(self) -> None:
        self._revisions: dict[str, dict[int, Revision]] = {}
        self._heads: dict[str, RevisionHead] = {}
        self._lock = threading.RLock()

    # --- reads ---------------------------------------------------------------
    def get_head(self, tenant: TenantId) -> RevisionHead | None:
        with self._lock:
            return self._heads.get(tenant.value)

    def get_revision(self, tenant: TenantId, revision_number: int) -> Revision | None:
        with self._lock:
            return self._revisions.get(tenant.value, {}).get(revision_number)

    def revision_exists(self, tenant: TenantId, revision_number: int) -> bool:
        with self._lock:
            return revision_number in self._revisions.get(tenant.value, {})

    def revision_count(self, tenant: TenantId) -> int:
        with self._lock:
            return len(self._revisions.get(tenant.value, {}))

    def tenants(self) -> tuple[TenantId, ...]:
        with self._lock:
            return tuple(self._heads[key].tenant for key in sorted(self._heads))

    def revalidate_head(self, tenant: TenantId, expected: RevisionHead) -> bool:
        with self._lock:
            return self._heads.get(tenant.value) == expected

    # --- compare-and-set primitive ------------------------------------------
    def compare_and_set_head(
        self, tenant: TenantId, expected: RevisionHead | None, desired: RevisionHead
    ) -> bool:
        with self._lock:
            if self._heads.get(tenant.value) == expected:
                self._heads[tenant.value] = desired
                return True
            return False

    # --- atomic revision + head operations ----------------------------------
    def create_first_revision(self, revision: Revision) -> RevisionHead:
        if revision.revision_number != 1 or revision.parent_hash is not None:
            raise ValueError(
                "create_first_revision requires revision_number == 1 and no parent_hash"
            )
        with self._lock:
            if revision.tenant.value in self._heads:
                raise PersistenceConflictError(
                    f"first revision already exists for tenant {revision.tenant.value!r}"
                )
            return self._store(revision)

    def append_revision(self, revision: Revision) -> RevisionHead:
        if revision.revision_number < 2 or revision.parent_hash is None:
            raise ValueError("append_revision requires revision_number >= 2 and a parent_hash")
        expected = RevisionHead(
            tenant=revision.tenant,
            revision_number=revision.revision_number - 1,
            content_hash=revision.parent_hash,
        )
        with self._lock:
            if self._heads.get(revision.tenant.value) != expected:
                raise PersistenceConflictError(
                    f"head advanced for tenant {revision.tenant.value!r}: "
                    f"expected revision {expected.revision_number}"
                )
            return self._store(revision)

    def _store(self, revision: Revision) -> RevisionHead:
        """Persist ``revision`` and set the head (caller holds the lock)."""
        head = revision.head()
        self._revisions.setdefault(revision.tenant.value, {})[revision.revision_number] = revision
        self._heads[revision.tenant.value] = head
        return head
