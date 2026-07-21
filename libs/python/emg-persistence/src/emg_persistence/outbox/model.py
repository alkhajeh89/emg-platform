"""Outbox event model for Phase 2 Sprint 5."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from emg_platform_core import TenantId
from pydantic import BaseModel, ConfigDict, Field

HexHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyString = Annotated[str, Field(min_length=1)]


class OutboxEvent(BaseModel):
    """Immutable event stored with the authoritative transaction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID

    tenant: TenantId

    revision_number: int = Field(ge=1)

    content_hash: HexHash

    event_type: NonEmptyString

    schema_version: int = Field(ge=1)

    idempotency_key: NonEmptyString

    payload: dict[str, Any]

    created_at: datetime

    published_at: datetime | None = None
