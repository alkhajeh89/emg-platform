"""Ingestion result model (FEAT-05-2)."""

from __future__ import annotations

from emg_common_types import CorrelationId
from pydantic import BaseModel, ConfigDict


class IngestionResult(BaseModel):
    """The typed outcome of an ingestion. Distinguishes newly-created ids from
    idempotently-skipped ones (already present, byte-identical), and lists the
    Module-6 audit-event ids emitted for the mutations. The correlation id is
    carried through for end-to-end tracing (ADR-015)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool = True
    correlation_id: CorrelationId
    created_entity_ids: tuple[str, ...] = ()
    created_relationship_ids: tuple[str, ...] = ()
    skipped_entity_ids: tuple[str, ...] = ()
    skipped_relationship_ids: tuple[str, ...] = ()
    emitted_audit_event_ids: tuple[str, ...] = ()

    @property
    def created_count(self) -> int:
        return len(self.created_entity_ids) + len(self.created_relationship_ids)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_entity_ids) + len(self.skipped_relationship_ids)
