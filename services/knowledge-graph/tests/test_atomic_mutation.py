from __future__ import annotations

import threading
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from emg_common_types import Classification
from emg_knowledge_graph import (
    AtomicMutationOutcome,
    CommittedMutation,
    CreateEntityCommand,
    IdempotencyMismatchError,
    InMemoryAtomicMutationExecution,
    KnowledgeGraphApplication,
    MergeEntitiesCommand,
    MutationAuditIntent,
    MutationExecutionRequest,
    MutationExecutionResult,
    MutationResult,
    mutation_audit_reference,
    project_mutation_replay,
)
from emg_knowledge_graph.fingerprint import (
    canonical_fingerprint_bytes,
    command_fingerprint,
)
from emg_ontology import Entity, ProvenanceReference
from emg_platform_core import InMemoryGraphStore, PrincipalRef, TenantId, WriteReceipt

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 2, 1, 12, 30, 45, 1234, tzinfo=timezone.utc)
TENANT = TenantId.of("tenant-a")
PRINCIPAL = PrincipalRef.service("writer")
CONTENT_HASH = "a" * 64


def _entity(*, correlation_id: str = "entity-correlation") -> Entity:
    return Entity(
        entity_id="entity-1",
        entity_type="person",
        classification=Classification.INTERNAL,
        trust_score=0.9,
        provenance_reference=ProvenanceReference(
            source_principal="source",
            event_id="event-1",
            correlation_id="ontology-correlation",
        ),
        owner="owner-a",
        effective_from=T0,
        correlation_id=correlation_id,
    )


def _command(
    *, idempotency_key: str = "transport-1", correlation_id: str = "entity-correlation"
) -> CreateEntityCommand:
    return CreateEntityCommand(
        tenant=TENANT,
        principal=PRINCIPAL,
        entity=_entity(correlation_id=correlation_id),
        idempotency_key=idempotency_key,
        as_of=T1,
    )


def _result() -> MutationResult:
    intent = MutationAuditIntent(
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="transport-1",
        action="create",
        resource_type="knowledge-graph.entity",
        resource_id="entity-1",
        related_resource_ids=(),
        classification=Classification.INTERNAL,
        reason=None,
        revision_number=1,
        content_hash=CONTENT_HASH,
    )
    return MutationResult(
        tenant=TENANT,
        principal=PRINCIPAL,
        revision_number=1,
        content_hash=CONTENT_HASH,
        node_count=1,
        edge_count=0,
        revision_created=True,
        nodes_created=1,
        edges_created=0,
        node_inputs_merged=0,
        edge_inputs_merged=0,
        audit_intents=(intent,),
    )


def _committed() -> CommittedMutation:
    return CommittedMutation(
        result=_result(),
        receipt=WriteReceipt(
            tenant=TENANT,
            principal=PRINCIPAL,
            content_hash=CONTENT_HASH,
            node_count=1,
            edge_count=0,
            revision_number=1,
            committed_at=T1,
            revision_created=True,
        ),
    )


def test_fingerprint_v1_golden_vector() -> None:
    canonical = canonical_fingerprint_bytes(_command()).decode("utf-8")
    assert canonical == (
        '{"as_of":"2026-02-01T12:30:45.001234Z",'
        '"fingerprint_version":1,"operation":"entity.create",'
        '"payload":{"entity":{'
        '"classification":"INTERNAL","correlation_id":"entity-correlation",'
        '"effective_from":"2026-01-01T00:00:00.000000Z","effective_to":null,'
        '"entity_id":"entity-1","entity_type":"person","lifecycle_status":"proposed",'
        '"owner":"owner-a","provenance_reference":{'
        '"correlation_id":"ontology-correlation","custody_event_id":null,'
        '"event_id":"event-1","provenance_record_id":null,'
        '"source_principal":"source"},"superseded_by":null,"supersedes":null,'
        '"trust_score":0.9,"version":1}},"principal":{'
        '"kind":"service","principal_id":"writer"},'
        '"schema":"emg.kg.mutation-command","schema_version":1,'
        '"tenant_id":"tenant-a"}'
    )
    assert command_fingerprint(_command()) == (
        "30cbce3e14a01120dd7c6ba3710f052013fb4d6abe5bead0949b038ac91d9e79"
    )


def test_transport_key_is_excluded_but_ontology_correlation_is_included() -> None:
    assert command_fingerprint(_command(idempotency_key="one")) == command_fingerprint(
        _command(idempotency_key="two")
    )
    assert command_fingerprint(_command(correlation_id="one")) != command_fingerprint(
        _command(correlation_id="two")
    )


def test_fingerprint_v1_preserves_unicode_and_normalizes_equivalent_instants() -> None:
    composed = _command(correlation_id="\u00e9")
    decomposed = _command(correlation_id="e\u0301")
    assert command_fingerprint(composed) != command_fingerprint(decomposed)

    same_instant = replace(
        composed,
        as_of=T1.astimezone(timezone(timedelta(hours=4))),
    )
    assert command_fingerprint(composed) == command_fingerprint(same_instant)


def test_merge_source_ids_are_the_only_set_normalized_collection() -> None:
    first = MergeEntitiesCommand(
        tenant=TENANT,
        principal=PRINCIPAL,
        survivor_id="survivor",
        source_ids=("source-b", "source-a"),
        idempotency_key="merge-key",
        as_of=T1,
        reason="same entity",
    )
    second = MergeEntitiesCommand(
        tenant=TENANT,
        principal=PRINCIPAL,
        survivor_id="survivor",
        source_ids=("source-a", "source-b"),
        idempotency_key="different-transport-key",
        as_of=T1,
        reason="same entity",
    )
    assert command_fingerprint(first) == command_fingerprint(second)


def test_application_replay_is_reauthorized_without_graph_execution() -> None:
    store = InMemoryGraphStore()
    authorized: list[CreateEntityCommand] = []
    app = KnowledgeGraphApplication(
        store,
        mutation_authorization_hook=lambda command: authorized.append(command),  # type: ignore[arg-type]
    )

    first = app.create_entity(_command())
    replay = app.create_entity(_command())

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.mutation_result == first.mutation_result
    assert replay.mutation_id == first.mutation_id
    assert replay.audit_reference == first.audit_reference
    assert replay.timestamp == first.timestamp
    assert authorized == [_command(), _command(), _command()]


def test_application_execution_projection_is_stable_immutable_and_preserves_result() -> None:
    mutation_id = UUID("11111111-1111-4111-8111-111111111111")
    atomic = InMemoryAtomicMutationExecution(
        clock=lambda: T1,
        mutation_id_factory=lambda: mutation_id,
    )
    app = KnowledgeGraphApplication(
        InMemoryGraphStore(),
        atomic_mutation_execution=atomic,
    )

    first = app.create_entity(_command())
    replay = app.create_entity(_command())

    assert isinstance(first, MutationExecutionResult)
    assert first.mutation_id == mutation_id
    assert first.audit_reference == mutation_audit_reference(mutation_id)
    assert first.audit_reference == "audit:11111111-1111-4111-8111-111111111111"
    assert first.timestamp == T1
    assert first.replayed is False
    assert replay.mutation_id == mutation_id
    assert replay.audit_reference == first.audit_reference
    assert replay.timestamp == T1
    assert replay.replayed is True
    assert replay.mutation_result == first.mutation_result
    with pytest.raises(FrozenInstanceError):
        first.replayed = True  # type: ignore[misc]


def test_mutation_result_contract_is_unchanged() -> None:
    assert [field.name for field in fields(MutationResult)] == [
        "tenant",
        "principal",
        "revision_number",
        "content_hash",
        "node_count",
        "edge_count",
        "revision_created",
        "nodes_created",
        "edges_created",
        "node_inputs_merged",
        "edge_inputs_merged",
        "audit_intents",
    ]


def test_same_key_with_different_command_is_rejected() -> None:
    adapter = InMemoryAtomicMutationExecution()
    first = MutationExecutionRequest.from_command(_command())
    adapter.execute(first, _committed)

    with pytest.raises(IdempotencyMismatchError):
        adapter.lookup(_command(correlation_id="different"))


def test_duplicate_request_race_executes_operation_once() -> None:
    adapter = InMemoryAtomicMutationExecution(claim_wait_seconds=2)
    request = MutationExecutionRequest.from_command(_command())
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    outcomes: list[AtomicMutationOutcome] = []

    def operation() -> CommittedMutation:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(2)
        return _committed()

    def worker() -> None:
        outcomes.append(adapter.execute(request, operation))

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert entered.wait(2)
    second.start()
    release.set()
    first.join(2)
    second.join(2)

    assert calls == 1
    assert sorted(outcome.replayed for outcome in outcomes) == [False, True]


def test_failed_operation_rolls_back_claim_and_can_be_retried() -> None:
    adapter = InMemoryAtomicMutationExecution()
    request = MutationExecutionRequest.from_command(_command())

    with pytest.raises(RuntimeError, match="injected"):
        adapter.execute(
            request,
            lambda: (_ for _ in ()).throw(RuntimeError("injected")),
        )

    assert adapter.lookup(_command()) is None
    assert adapter.execute(request, _committed).replayed is False


def test_expired_success_can_be_replaced_using_adapter_clock() -> None:
    now = [T1]
    adapter = InMemoryAtomicMutationExecution(
        replay_retention=timedelta(seconds=1),
        clock=lambda: now[0],
    )
    request = MutationExecutionRequest.from_command(_command())
    adapter.execute(request, _committed)
    now[0] += timedelta(seconds=2)

    assert adapter.lookup(_command()) is None
    assert adapter.execute(request, _committed).replayed is False


def test_replay_projection_is_frozen_and_excludes_internal_data() -> None:
    projection = project_mutation_replay(_result())
    assert projection.tenant_id == TENANT.value
    assert projection.content_hash == CONTENT_HASH
    assert not hasattr(projection, "principal")
    assert not hasattr(projection, "audit_intents")
    assert not hasattr(projection, "classification")
    with pytest.raises(FrozenInstanceError):
        projection.content_hash = "b" * 64  # type: ignore[misc]
