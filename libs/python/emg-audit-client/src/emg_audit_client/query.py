"""The AuditQuery model — the minimal query surface US-04 requires
(FEAT-04-1): "events are queryable by actor, time range, and correlation
identifier."

This is deliberately minimal. The richer filtering, pagination UX, export,
and reporting surface is FEAT-04-4 (Audit Query & Reporting Interface), a
later Audit sprint — not Sprint 6.
"""

from __future__ import annotations

from datetime import datetime

from emg_common_types import CorrelationId
from pydantic import BaseModel, ConfigDict, Field


class AuditQuery(BaseModel):
    """Filter for reading audit events. All fields optional; an all-None query
    returns the most recent events up to `limit`. Filters combine with AND.

    `start_time`/`end_time` bound `AuditEvent.timestamp` (the server-assigned
    UTC capture time), inclusive of `start_time` and exclusive of `end_time`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str | None = None
    correlation_id: CorrelationId | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)
