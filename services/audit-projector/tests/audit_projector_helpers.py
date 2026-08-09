from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from emg_audit_projector.config import Settings
from emg_persistence.mutations import (
    DispatchBacklog,
    DispatchWorkItem,
    LedgerRecord,
)


def settings(*, tenants: tuple[str, ...] = ("tenant-a",), **overrides: object) -> Settings:
    credentials = [
        {
            "tenant_id": tenant,
            "client_id": f"emg-svc-audit-projector-{tenant}",
            "client_secret": f"secret-{tenant}",
        }
        for tenant in tenants
    ]
    values: dict[str, object] = {
        "deployment_environment": "test",
        "identity_inventory_json": json.dumps(
            {
                "version": 1,
                "projector_identities": [
                    {"tenant_id": item["tenant_id"], "client_id": item["client_id"]}
                    for item in credentials
                ],
            }
        ),
        "tenant_credentials_json": json.dumps(credentials),
        "poll_interval_seconds": 0.01,
        "telemetry_interval_seconds": 0.01,
    }
    values.update(overrides)
    return Settings(**values)


def ledger(
    *,
    mutation_id: UUID | None = None,
    tenant_id: str = "tenant-a",
    intent_count: int = 1,
) -> LedgerRecord:
    mutation_id = mutation_id or uuid4()
    intents = [
        {
            "tenant_id": tenant_id,
            "principal": {"principal_id": "service-principal", "kind": "service"},
            "idempotency_key": "must-not-project",
            "action": "create",
            "resource_type": "entity",
            "resource_id": f"entity-{ordinal}",
            "related_resource_ids": ["related-b", "related-a"],
            "classification": "INTERNAL",
            "reason": "approved",
            "revision_number": 7,
            "content_hash": "a" * 64,
        }
        for ordinal in range(intent_count)
    ]
    now = datetime.now(timezone.utc)
    return LedgerRecord(
        mutation_id=mutation_id,
        tenant_id=tenant_id,
        principal_id="service-principal",
        principal_kind="service",
        idempotency_key="must-not-project",
        command_fingerprint="f" * 64,
        fingerprint_version=1,
        command_schema_version=1,
        operation="create_entity",
        status="succeeded",
        graph_revision=7,
        graph_content_hash="a" * 64,
        write_receipt={},
        mutation_result={},
        audit_intents={"schema_version": 1, "intents": intents},
        requested_at=now,
        ledger_completed_at=now,
        graph_revision_at=now,
        replay_expires_at=now + timedelta(hours=1),
        resource_count=intent_count,
    )


def work_item(
    record: LedgerRecord,
    *,
    attempt_count: int = 1,
    owner: str = "audit-projector-1",
) -> DispatchWorkItem:
    now = datetime.now(timezone.utc)
    return DispatchWorkItem(
        mutation_id=record.mutation_id,
        tenant_id=record.tenant_id,
        channel="audit",
        available_at=now,
        attempt_count=attempt_count,
        claim_owner=owner,
        claim_expires_at=now + timedelta(seconds=30),
        source_position=None,
    )


class FakeTransactions:
    @contextmanager
    def transaction(self) -> Iterator[object]:
        yield object()


class FakeRepository:
    def __init__(self, records: dict[UUID, LedgerRecord]) -> None:
        self.records = records
        self.claims: dict[str, tuple[DispatchWorkItem, ...]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.backlog = DispatchBacklog(0, 0, 0, 0.0)
        self.complete_error: Exception | None = None

    def claim_dispatch(self, **kwargs: Any) -> tuple[DispatchWorkItem, ...]:
        self.calls.append(("claim", kwargs))
        return self.claims.get(str(kwargs["tenant_id"]), ())

    def get_ledger(self, **kwargs: Any) -> LedgerRecord | None:
        self.calls.append(("ledger", kwargs))
        return self.records.get(kwargs["mutation_id"])

    def complete_dispatch(self, **kwargs: Any) -> None:
        self.calls.append(("complete", kwargs))
        if self.complete_error is not None:
            raise self.complete_error

    def reschedule_dispatch(self, **kwargs: Any) -> None:
        self.calls.append(("reschedule", kwargs))

    def exhaust_dispatch(self, **kwargs: Any) -> None:
        self.calls.append(("exhaust", kwargs))

    def dispatch_backlog(self, **kwargs: Any) -> DispatchBacklog:
        self.calls.append(("backlog", kwargs))
        return self.backlog
