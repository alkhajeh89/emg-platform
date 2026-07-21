"""PostgreSQL transactional outbox repository for Phase 2 Sprint 5."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
