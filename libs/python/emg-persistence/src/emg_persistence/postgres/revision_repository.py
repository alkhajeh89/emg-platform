"""PostgreSQL RevisionRepository (Phase 2, Sprint 3).

Implements the :class:`~emg_persistence.revisions.repository.RevisionRepository`
contract against ``graph_revisions`` + ``graph_head`` (schema V001). Revision
insert and head compare-and-set happen in a **single transaction**; the head
operation is the CAS arbiter (performed first), so only the writer that wins the
head race inserts the revision row — no duplicate revisions, no lost updates.

PostgreSQL is the authoritative store (ADR-1); this layer performs no projection,
no serialization, and no GraphStore logic. The database-touching methods require
a live PostgreSQL and are integration-tested (CI ``persistence`` job), hence
``# pragma: no cover``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from emg_platform_core import PrincipalKind, PrincipalRef, TenantId
from emg_platform_core.ports import DEFAULT_REVISION_LIST_LIMIT, MAX_REVISION_LIST_LIMIT

from ..errors import PersistenceConflictError
from ..revisions.model import Revision, RevisionHead, RevisionRecord

if TYPE_CHECKING:
    from psycopg import Connection

_SELECT_HEAD = (
    "SELECT head_revision_number, head_content_hash FROM graph_head WHERE tenant_id = %(t)s"
)
_SELECT_REVISION = (
    "SELECT revision_number, content_hash, parent_hash, principal_id, principal_kind, "
    "node_count, edge_count, graph_json, created_at FROM graph_revisions "
    "WHERE tenant_id = %(t)s AND revision_number = %(n)s"
)
_EXISTS = (
    "SELECT 1 FROM graph_revisions WHERE tenant_id = %(t)s AND revision_number = %(n)s LIMIT 1"
)
_COUNT = "SELECT count(*) FROM graph_revisions WHERE tenant_id = %(t)s"
_SELECT_TENANTS = "SELECT tenant_id FROM graph_head ORDER BY tenant_id"
_SELECT_REVISION_LIST = (
    "SELECT revision_number, content_hash, parent_hash, principal_id, principal_kind, "
    "node_count, edge_count, created_at FROM graph_revisions "
    "WHERE tenant_id = %(t)s AND revision_number < %(before)s "
    "ORDER BY revision_number DESC LIMIT %(limit)s"
)
_SELECT_REVISION_LIST_NO_CURSOR = (
    "SELECT revision_number, content_hash, parent_hash, principal_id, principal_kind, "
    "node_count, edge_count, created_at FROM graph_revisions "
    "WHERE tenant_id = %(t)s "
    "ORDER BY revision_number DESC LIMIT %(limit)s"
)
_REVALIDATE_HEAD = (
    "SELECT head_revision_number, head_content_hash FROM graph_head "
    "WHERE tenant_id = %(t)s FOR UPDATE"
)
_INSERT_HEAD = (
    "INSERT INTO graph_head (tenant_id, head_revision_number, head_content_hash) "
    "VALUES (%(t)s, %(n)s, %(h)s) ON CONFLICT (tenant_id) DO NOTHING"
)
_UPDATE_HEAD = (
    "UPDATE graph_head SET head_revision_number = %(n)s, head_content_hash = %(h)s, "
    "updated_at = now() WHERE tenant_id = %(t)s AND head_revision_number = %(en)s "
    "AND head_content_hash = %(eh)s"
)
_INSERT_REVISION = (
    "INSERT INTO graph_revisions (tenant_id, revision_number, content_hash, parent_hash, "
    "principal_id, principal_kind, node_count, edge_count, graph_json, created_at) "
    "VALUES (%(t)s, %(n)s, %(h)s, %(ph)s, %(pid)s, %(pk)s, %(nc)s, %(ec)s, %(gj)s, %(ca)s)"
)


class PostgresRevisionRepository:
    """A :class:`RevisionRepository` backed by a PostgreSQL connection."""

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    def get_head(self, tenant: TenantId) -> RevisionHead | None:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(_SELECT_HEAD, {"t": tenant.value})
            row = cur.fetchone()
        if row is None:
            return None
        return RevisionHead(tenant=tenant, revision_number=row[0], content_hash=row[1])

    def get_revision(
        self, tenant: TenantId, revision_number: int
    ) -> Revision | None:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(_SELECT_REVISION, {"t": tenant.value, "n": revision_number})
            row = cur.fetchone()
        if row is None:
            return None
        return Revision(
            tenant=tenant,
            revision_number=row[0],
            content_hash=row[1],
            parent_hash=row[2],
            principal=PrincipalRef(principal_id=row[3], kind=PrincipalKind(row[4])),
            node_count=row[5],
            edge_count=row[6],
            graph_json=row[7],
            created_at=row[8],
        )

    def revision_exists(
        self, tenant: TenantId, revision_number: int
    ) -> bool:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(_EXISTS, {"t": tenant.value, "n": revision_number})
            return cur.fetchone() is not None

    def revision_count(self, tenant: TenantId) -> int:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(_COUNT, {"t": tenant.value})
            row = cur.fetchone()
        return int(row[0]) if row is not None else 0

    def tenants(self) -> tuple[TenantId, ...]:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(_SELECT_TENANTS)
            rows = cur.fetchall()
        return tuple(TenantId.of(row[0]) for row in rows)

    def revalidate_head(
        self, tenant: TenantId, expected: RevisionHead
    ) -> bool:  # pragma: no cover - live DB
        if expected.tenant != tenant:
            return False
        with self._connection.cursor() as cur:
            cur.execute(_REVALIDATE_HEAD, {"t": tenant.value})
            row = cur.fetchone()
        return (
            row is not None
            and row[0] == expected.revision_number
            and row[1] == expected.content_hash
        )

    def compare_and_set_head(
        self, tenant: TenantId, expected: RevisionHead | None, desired: RevisionHead
    ) -> bool:  # pragma: no cover - live DB
        with self._connection.transaction(), self._connection.cursor() as cur:
            if expected is None:
                cur.execute(
                    _INSERT_HEAD,
                    {"t": tenant.value, "n": desired.revision_number, "h": desired.content_hash},
                )
            else:
                cur.execute(
                    _UPDATE_HEAD,
                    {
                        "t": tenant.value,
                        "n": desired.revision_number,
                        "h": desired.content_hash,
                        "en": expected.revision_number,
                        "eh": expected.content_hash,
                    },
                )
            return cur.rowcount == 1

    def create_first_revision(self, revision: Revision) -> RevisionHead:  # pragma: no cover
        if revision.revision_number != 1 or revision.parent_hash is not None:
            raise ValueError(
                "create_first_revision requires revision_number == 1 and no parent_hash"
            )
        head = revision.head()
        # Raising inside the transaction rolls back the head insert, so nothing
        # is persisted when another writer created the first revision first.
        with self._connection.transaction(), self._connection.cursor() as cur:
            cur.execute(
                _INSERT_HEAD,
                {"t": revision.tenant.value, "n": 1, "h": revision.content_hash},
            )
            if cur.rowcount != 1:
                raise PersistenceConflictError(
                    f"first revision already exists for tenant {revision.tenant.value!r}"
                )
            cur.execute(_INSERT_REVISION, self._revision_params(revision))
        return head

    def append_revision(self, revision: Revision) -> RevisionHead:  # pragma: no cover - live DB
        if revision.revision_number < 2 or revision.parent_hash is None:
            raise ValueError("append_revision requires revision_number >= 2 and a parent_hash")
        head = revision.head()
        with self._connection.transaction(), self._connection.cursor() as cur:
            cur.execute(
                _UPDATE_HEAD,
                {
                    "t": revision.tenant.value,
                    "n": revision.revision_number,
                    "h": revision.content_hash,
                    "en": revision.revision_number - 1,
                    "eh": revision.parent_hash,
                },
            )
            if cur.rowcount != 1:
                raise PersistenceConflictError(
                    f"head advanced for tenant {revision.tenant.value!r}: "
                    f"expected revision {revision.revision_number - 1}"
                )
            cur.execute(_INSERT_REVISION, self._revision_params(revision))
        return head

    def list_revisions(
        self,
        tenant: TenantId,
        *,
        limit: int = DEFAULT_REVISION_LIST_LIMIT,
        before_revision_number: int | None = None,
    ) -> tuple[RevisionRecord, ...]:  # pragma: no cover - live DB
        """Metadata-only listing (ADR-023 §18): omits ``graph_json`` entirely,
        so this never deserializes or hash-verifies a graph snapshot."""
        if not 1 <= limit <= MAX_REVISION_LIST_LIMIT:
            raise ValueError(f"limit must be in [1, {MAX_REVISION_LIST_LIMIT}]: {limit!r}")
        with self._connection.cursor() as cur:
            if before_revision_number is None:
                cur.execute(_SELECT_REVISION_LIST_NO_CURSOR, {"t": tenant.value, "limit": limit})
            else:
                cur.execute(
                    _SELECT_REVISION_LIST,
                    {"t": tenant.value, "before": before_revision_number, "limit": limit},
                )
            rows = cur.fetchall()
        return tuple(
            RevisionRecord(
                tenant=tenant,
                revision_number=row[0],
                content_hash=row[1],
                parent_hash=row[2],
                principal=PrincipalRef(principal_id=row[3], kind=PrincipalKind(row[4])),
                node_count=row[5],
                edge_count=row[6],
                created_at=row[7],
            )
            for row in rows
        )

    @staticmethod
    def _revision_params(revision: Revision) -> dict[str, Any]:  # pragma: no cover - live DB
        from psycopg.types.json import Jsonb

        return {
            "t": revision.tenant.value,
            "n": revision.revision_number,
            "h": revision.content_hash,
            "ph": revision.parent_hash,
            "pid": revision.principal.principal_id,
            "pk": revision.principal.kind.value,
            "nc": revision.node_count,
            "ec": revision.edge_count,
            "gj": Jsonb(revision.graph_json),
            "ca": revision.created_at,
        }
