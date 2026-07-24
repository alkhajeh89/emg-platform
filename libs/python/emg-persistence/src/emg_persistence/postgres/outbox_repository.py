"""PostgreSQL transactional outbox repository for Phase 2 Sprint 5."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from emg_platform_core import TenantId

from ..outbox.model import OutboxEvent

if TYPE_CHECKING:
    from psycopg import Connection


_INSERT_OUTBOX = """
INSERT INTO outbox (
    event_id,
    tenant_id,
    revision_number,
    content_hash,
    event_type,
    schema_version,
    idempotency_key,
    payload,
    created_at,
    published_at
)
VALUES (
    %(event_id)s,
    %(tenant_id)s,
    %(revision_number)s,
    %(content_hash)s,
    %(event_type)s,
    %(schema_version)s,
    %(idempotency_key)s,
    %(payload)s,
    %(created_at)s,
    %(published_at)s
)
"""

_LIST_FOR_TENANT = """
SELECT
    event_id,
    tenant_id,
    revision_number,
    content_hash,
    event_type,
    schema_version,
    idempotency_key,
    payload,
    created_at,
    published_at
FROM outbox
WHERE tenant_id = %(tenant_id)s
  AND revision_number > %(after_revision)s
ORDER BY revision_number ASC
LIMIT %(limit)s
"""


class PostgresOutboxRepository:
    """PostgreSQL implementation of transactional outbox persistence."""

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    def append(self, event: OutboxEvent) -> None:
        """Append one immutable event."""

        from psycopg.types.json import Jsonb

        with self._connection.cursor() as cur:
            cur.execute(
                _INSERT_OUTBOX,
                {
                    "event_id": event.event_id,
                    "tenant_id": event.tenant.value,
                    "revision_number": event.revision_number,
                    "content_hash": event.content_hash,
                    "event_type": event.event_type,
                    "schema_version": event.schema_version,
                    "idempotency_key": event.idempotency_key,
                    "payload": Jsonb(event.payload),
                    "created_at": event.created_at,
                    "published_at": event.published_at,
                },
            )

    def list_for_tenant(
        self, tenant: TenantId, *, after_revision: int = 0, limit: int = 100
    ) -> tuple[OutboxEvent, ...]:  # pragma: no cover - live DB
        """Return ordered outbox events after ``after_revision`` for projection workers."""
        with self._connection.cursor() as cur:
            cur.execute(
                _LIST_FOR_TENANT,
                {
                    "tenant_id": tenant.value,
                    "after_revision": after_revision,
                    "limit": limit,
                },
            )
            rows = cur.fetchall()
        return tuple(
            OutboxEvent(
                event_id=row[0],
                tenant=TenantId.of(row[1]),
                revision_number=row[2],
                content_hash=row[3],
                event_type=row[4],
                schema_version=row[5],
                idempotency_key=row[6],
                payload=dict(row[7]) if row[7] is not None else {},
                created_at=row[8],
                published_at=row[9],
            )
            for row in rows
        )
