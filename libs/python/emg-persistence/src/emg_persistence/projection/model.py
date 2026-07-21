"""Projection models for Phase 2 Sprint 6."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from emg_platform_core import TenantId
from pydantic import BaseModel, ConfigDict


class ProjectionCheckpoint(BaseModel):
    """Immutable projection processing checkpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantId
    revision_number: int
    event_id: UUID
    processed_at: datetime
