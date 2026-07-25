"""PostgreSQL projection checkpoint repository (Phase 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..projection.model import ProjectionCheckpoint

if TYPE_CHECKING:
    from psycopg import Connection


_EXISTS = """
SELECT 1
FROM projection_checkpoints
WHERE tenant_id = %(tenant_id)s AND revision_number = %(revision_number)s
LIMIT 1
"""

_INSERT = """
INSERT INTO projection_checkpoints (
    tenant_id,
    revision_number,
    event_id,
    processed_at
)
VALUES (
    %(tenant_id)s,
    %(revision_number)s,
    %(event_id)s,
    %(processed_at)s
)
ON CONFLICT (tenant_id, revision_number) DO NOTHING
"""

_LATEST = """
SELECT tenant_id, revision_number, event_id, processed_at
FROM projection_checkpoints
WHERE tenant_id = %(tenant_id)s
ORDER BY revision_number DESC
LIMIT 1
"""


class PostgresProjectionCheckpointRepository:
    """Tracks processed outbox revisions for idempotent projection workers."""

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    def exists(self, tenant_id: str, revision_number: int) -> bool:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(
                _EXISTS,
                {"tenant_id": tenant_id, "revision_number": revision_number},
            )
            return cur.fetchone() is not None

    def record(self, checkpoint: ProjectionCheckpoint) -> None:  # pragma: no cover - live DB
        with self._connection.cursor() as cur:
            cur.execute(
                _INSERT,
                {
                    "tenant_id": checkpoint.tenant.value,
                    "revision_number": checkpoint.revision_number,
                    "event_id": checkpoint.event_id,
                    "processed_at": checkpoint.processed_at,
                },
            )

    def latest(self, tenant_id: str) -> ProjectionCheckpoint | None:  # pragma: no cover
        from emg_platform_core import TenantId

        with self._connection.cursor() as cur:
            cur.execute(_LATEST, {"tenant_id": tenant_id})
            row = cur.fetchone()
        if row is None:
            return None
        return ProjectionCheckpoint(
            tenant=TenantId.of(row[0]),
            revision_number=row[1],
            event_id=row[2],
            processed_at=row[3],
        )
