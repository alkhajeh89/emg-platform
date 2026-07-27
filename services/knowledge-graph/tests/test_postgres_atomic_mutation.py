from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from emg_common_types import Classification
from emg_knowledge_graph import (
    CommittedMutation,
    CreateEntityCommand,
    LegacyIdempotencyConflictError,
    MutationAuditIntent,
    MutationExecutionRequest,
    MutationReplayIntegrityError,
    MutationResult,
    UnsupportedFingerprintVersionError,
)
from emg_knowledge_graph_infrastructure.atomic_mutation import (
    PostgresAtomicMutationExecution,
)
from emg_ontology import Entity, ProvenanceReference
from emg_persistence.mutations import IdempotencyClaim, IdempotencyState
from emg_platform_core import PrincipalRef, TenantId, WriteReceipt

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
TENANT = TenantId.of("tenant-a")
PRINCIPAL = PrincipalRef.service("writer")
CONTENT_HASH = "a" * 64


def _command() -> CreateEntityCommand:
    return CreateEntityCommand(
        tenant=TENANT,
        principal=PRINCIPAL,
        entity=Entity(
            entity_id="entity-1",
            entity_type="person",
            classification=Classification.INTERNAL,
            trust_score=0.9,
            provenance_reference=ProvenanceReference(source_principal="source", event_id="event-1"),
            owner="owner-a",
            effective_from=T0,
        ),
        idempotency_key="batch-key",
        as_of=T0,
    )


def _intent(resource_id: str, ordinal: int) -> MutationAuditIntent:
    return MutationAuditIntent(
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="batch-key",
        action="update",
        resource_type="knowledge-graph.entity",
        resource_id=resource_id,
        related_resource_ids=(f"related-{ordinal}",),
        classification=Classification.INTERNAL,
        reason="batch",
        revision_number=3,
        content_hash=CONTENT_HASH,
    )


def test_batch_ledger_preserves_resource_order_and_allows_duplicate_shapes() -> None:
    duplicate = _intent("entity-1", 0)
    result = MutationResult(
        tenant=TENANT,
        principal=PRINCIPAL,
        revision_number=3,
        content_hash=CONTENT_HASH,
        node_count=2,
        edge_count=0,
        revision_created=True,
        nodes_created=0,
        edges_created=0,
        node_inputs_merged=2,
        edge_inputs_merged=0,
        audit_intents=(duplicate, duplicate),
    )
    receipt = WriteReceipt(
        tenant=TENANT,
        principal=PRINCIPAL,
        content_hash=CONTENT_HASH,
        node_count=2,
        edge_count=0,
        revision_number=3,
        committed_at=T0,
        revision_created=True,
    )
    request = MutationExecutionRequest(
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="batch-key",
        operation="entity.batch",
        command_fingerprint="b" * 64,
        fingerprint_version=1,
        command_schema_version=1,
    )

    ledger = PostgresAtomicMutationExecution._ledger(
        request, CommittedMutation(result=result, receipt=receipt)
    )

    assert ledger.resources == (
        ledger.resources[0],
        ledger.resources[1],
    )
    assert [resource.ordinal for resource in ledger.resources] == [0, 1]
    assert [resource.resource_id for resource in ledger.resources] == [
        "entity-1",
        "entity-1",
    ]
    assert ledger.mutation_result["schema_version"] == 1
    assert ledger.write_receipt["schema_version"] == 1
    assert ledger.audit_intents["schema_version"] == 1


class _LookupTransactions:
    @contextmanager
    def transaction(self):  # type: ignore[no-untyped-def]
        yield object()


class _LookupRepository:
    claim: IdempotencyClaim

    def __init__(self, connection: object) -> None:
        del connection

    def lookup_claim(self, **kwargs: object) -> IdempotencyClaim:
        del kwargs
        return self.claim


def _claim(
    state: IdempotencyState,
    *,
    fingerprint_version: int | None,
    command_schema_version: int | None,
) -> IdempotencyClaim:
    return IdempotencyClaim(
        tenant_id=TENANT.value,
        principal_id=str(PRINCIPAL.principal_id),
        idempotency_key="batch-key",
        operation="entity.create",
        state=state,
        requested_at=T0,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        command_fingerprint=None,
        fingerprint_version=fingerprint_version,
        command_schema_version=command_schema_version,
        mutation_id=None,
        mutation_result=None,
        acquired=False,
    )


def _adapter_with_claim(claim: IdempotencyClaim) -> PostgresAtomicMutationExecution:
    _LookupRepository.claim = claim
    return PostgresAtomicMutationExecution(
        _LookupTransactions(),  # type: ignore[arg-type]
        repository_factory=_LookupRepository,  # type: ignore[arg-type]
    )


def test_legacy_hit_fails_before_fingerprint_construction() -> None:
    adapter = _adapter_with_claim(
        _claim(
            IdempotencyState.LEGACY_SUCCEEDED,
            fingerprint_version=None,
            command_schema_version=None,
        )
    )
    with pytest.raises(LegacyIdempotencyConflictError):
        adapter.lookup(_command())


def test_unsupported_active_fingerprint_version_fails_closed() -> None:
    adapter = _adapter_with_claim(
        _claim(
            IdempotencyState.SUCCEEDED,
            fingerprint_version=99,
            command_schema_version=1,
        )
    )
    with pytest.raises(UnsupportedFingerprintVersionError):
        adapter.lookup(_command())


def test_committed_pending_claim_is_integrity_failure() -> None:
    command = _command()
    request = MutationExecutionRequest.from_command(command)
    claim = _claim(
        IdempotencyState.PENDING,
        fingerprint_version=1,
        command_schema_version=1,
    )
    claim = replace(claim, command_fingerprint=request.command_fingerprint)
    adapter = _adapter_with_claim(claim)
    with pytest.raises(MutationReplayIntegrityError, match="pending"):
        adapter.lookup(command)
