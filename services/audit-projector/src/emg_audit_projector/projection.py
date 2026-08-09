"""Pure ADR-028 projection from immutable ledger facts to audit contracts."""

from __future__ import annotations

import json
from typing import Literal

from emg_audit_client import SubmittedAuditEvent
from emg_common_types import Classification
from emg_persistence.mutations import LedgerRecord
from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import ProjectionError


class _StoredPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_id: str
    kind: str


class _StoredAuditIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    principal: _StoredPrincipal
    idempotency_key: str
    action: str
    resource_type: str
    resource_id: str
    related_resource_ids: tuple[str, ...]
    classification: Classification
    reason: str | None
    revision_number: int
    content_hash: str


def _audit_intents(ledger: LedgerRecord) -> tuple[_StoredAuditIntent, ...]:
    document = ledger.audit_intents
    if document.get("schema_version") != 1:
        raise ProjectionError("unsupported mutation audit-intent schema")
    values = document.get("intents")
    if not isinstance(values, list) or not values:
        raise ProjectionError("mutation audit-intent collection must be a non-empty array")
    try:
        intents = tuple(_StoredAuditIntent.model_validate(value) for value in values)
    except ValidationError as exc:
        raise ProjectionError("invalid immutable mutation audit intent") from exc
    if any(intent.tenant_id != ledger.tenant_id for intent in intents):
        raise ProjectionError("audit intent tenant does not match mutation ledger tenant")
    return intents


def project_audit_events(ledger: LedgerRecord) -> tuple[SubmittedAuditEvent, ...]:
    """Return byte-stable event inputs without mutating or enriching the ledger."""

    if ledger.status not in {"succeeded", "no_op"}:
        raise ProjectionError("unsupported mutation ledger status")
    outcome: Literal["success"] = "success"
    events: list[SubmittedAuditEvent] = []
    for ordinal, intent in enumerate(_audit_intents(ledger)):
        metadata = {
            "revision_number": str(intent.revision_number),
            "content_hash": intent.content_hash,
            "related_resource_ids": json.dumps(
                list(intent.related_resource_ids), ensure_ascii=False, separators=(",", ":")
            ),
            "ledger_status": ledger.status,
        }
        events.append(
            SubmittedAuditEvent(
                event_id=f"kg-mutation:{ledger.mutation_id}:{ordinal}",
                actor=intent.principal.principal_id,
                actor_type="service",
                module="knowledge-graph",
                action=intent.action,
                outcome=outcome,
                correlation_id=None,
                resource_type=intent.resource_type,
                resource_id=intent.resource_id,
                classification=intent.classification,
                source_system="knowledge-graph",
                reason=intent.reason or "",
                metadata=metadata,
                provenance=None,
            )
        )
    return tuple(events)
