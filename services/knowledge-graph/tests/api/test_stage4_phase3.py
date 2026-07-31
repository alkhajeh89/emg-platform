"""Focused application-wiring tests for ADR-027 Stage 4 Phase 3."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from emg_auth_client import AuthorizationRequest, Decision
from emg_common_types import Classification
from emg_knowledge_graph import (
    AtomicMutationOutcome,
    CloseRelationshipCommand,
    CommittedMutation,
    CreateEntityCommand,
    IResourceMetadataReader,
    MergeEntitiesCommand,
    MutationAuthorizationContext,
    MutationAuthorizationPreflight,
    MutationExecutionRequest,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
    ResourceMetadata,
    SchemaNegotiationRequest,
    SchemaNegotiationResult,
)
from emg_knowledge_graph.atomic_mutation import MutationOperation
from emg_knowledge_graph.commands import MutationCommand
from emg_knowledge_graph_api.authn import ServicePrincipal
from emg_knowledge_graph_api.dependencies import (
    mutation_knowledge_graph_application_dependency,
    mutation_request_preparer_dependency,
    resource_metadata_reader_dependency,
)
from emg_knowledge_graph_api.mutation_authorization import (
    PepMutationAuthorizationEvaluator,
)
from emg_knowledge_graph_api.mutation_mapping import MutationRequest, map_mutation_request
from emg_knowledge_graph_api.mutation_preparation import MutationRequestPreparer
from emg_knowledge_graph_api.mutation_schemas import (
    CloseRelationshipRequest,
    CreateEntityRequest,
    MergeEntitiesRequest,
    ReplaceEntityRequest,
    ReplaceRelationshipRequest,
)
from emg_knowledge_graph_infrastructure import GraphResourceMetadataReader
from emg_memory_graph import MemoryGraph
from emg_platform_core import InMemoryGraphStore, PrincipalRef, TenantId

NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)
TENANT = TenantId.of("phase3-tenant")
PRINCIPAL = PrincipalRef.service("phase3-writer")


def _evidence() -> dict[str, object]:
    return {
        "evidence_id": "evidence-1",
        "source": "manual_entry",
        "locator": "case-1",
        "source_principal": "phase3-writer",
        "captured_at": NOW,
    }


def _node() -> dict[str, object]:
    return {
        "node_id": "entity-1",
        "node_type": "person",
        "label": "Entity One",
        "created_at": NOW,
        "updated_at": NOW,
        "source": "phase3-writer",
        "confidence": 0.9,
        "classification": "INTERNAL",
        "owner": "phase3-writer",
        "evidence": [_evidence()],
    }


def _edge() -> dict[str, object]:
    return {
        "edge_id": "relationship-1",
        "edge_type": "owns",
        "source_id": "entity-1",
        "target_id": "entity-2",
        "evidence": [_evidence()],
        "confidence": 0.9,
        "validity": {"valid_from": NOW},
        "created_at": NOW,
        "updated_at": NOW,
        "classification": "CONFIDENTIAL",
    }


def _create_request() -> CreateEntityRequest:
    return CreateEntityRequest.model_validate(
        {
            "entity": {
                "entity_id": "entity-1",
                "entity_type": "person",
                "classification": "INTERNAL",
                "trust_score": 0.9,
                "provenance_reference": {
                    "source_principal": "phase3-writer",
                    "event_id": "event-1",
                },
                "effective_from": NOW,
            },
            "as_of": NOW,
        }
    )


@pytest.mark.parametrize(
    ("transport_dto", "expected_type"),
    [
        (_create_request(), CreateEntityCommand),
        (
            ReplaceEntityRequest.model_validate(
                {
                    "replacement": _node(),
                    "action": "update",
                    "as_of": NOW,
                }
            ),
            ReplaceEntityCommand,
        ),
        (
            ReplaceRelationshipRequest.model_validate(
                {
                    "replacement": _edge(),
                    "as_of": NOW,
                }
            ),
            ReplaceRelationshipCommand,
        ),
        (
            CloseRelationshipRequest(
                edge_id="relationship-1",
                as_of=NOW,
                reason="relationship ended",
            ),
            CloseRelationshipCommand,
        ),
        (
            MergeEntitiesRequest(
                survivor_id="entity-1",
                source_ids=("entity-2",),
                as_of=NOW,
                reason="duplicate record",
            ),
            MergeEntitiesCommand,
        ),
    ],
)
def test_transport_requests_map_to_existing_application_commands(
    transport_dto: MutationRequest,
    expected_type: type[object],
) -> None:
    command = map_mutation_request(
        transport_dto,
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="phase3-key",
    )
    assert isinstance(command, expected_type)
    assert command.tenant == TENANT
    assert command.principal == PRINCIPAL
    assert command.idempotency_key == "phase3-key"


def test_create_mapping_assigns_owner_from_authenticated_principal() -> None:
    command = map_mutation_request(
        _create_request(),
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="phase3-key",
    )
    assert isinstance(command, CreateEntityCommand)
    assert command.entity.owner == str(PRINCIPAL.principal_id)


class _SchemaNegotiatorSpy:
    def __init__(self) -> None:
        self.requests: list[SchemaNegotiationRequest] = []

    def negotiate(self, request: SchemaNegotiationRequest) -> SchemaNegotiationResult:
        self.requests.append(request)
        return SchemaNegotiationResult(effective_version="1.0.0")


class _IdentityCompatibilityAdapters:
    def normalize(
        self,
        request: MutationRequest,
        *,
        source_version: str,
        target_version: str | None = None,
    ) -> MutationRequest:
        return request


def test_schema_negotiator_is_invoked_before_command_is_returned() -> None:
    negotiator = _SchemaNegotiatorSpy()
    preparer = MutationRequestPreparer(negotiator, _IdentityCompatibilityAdapters())

    prepared = preparer.prepare(
        _create_request(),
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="phase3-key",
        preferred_schema_version="1.0.0",
    )

    assert negotiator.requests == [SchemaNegotiationRequest(preferred_version="1.0.0")]
    assert prepared.effective_schema_version == "1.0.0"
    assert isinstance(prepared.command, CreateEntityCommand)


class _MetadataReaderSpy(IResourceMetadataReader):
    def __init__(self) -> None:
        self.entity_reads: list[tuple[TenantId, str]] = []

    def read_entity(self, tenant: TenantId, entity_id: str) -> ResourceMetadata | None:
        self.entity_reads.append((tenant, entity_id))
        return ResourceMetadata(
            resource_type="knowledge-graph.entity",
            resource_id=entity_id,
            classification=Classification.INTERNAL,
            owner="phase3-writer",
        )

    def read_relationship(self, tenant: TenantId, relationship_id: str) -> ResourceMetadata | None:
        raise AssertionError("relationship metadata was not expected")


class _PepSpy:
    def __init__(self) -> None:
        self.requests: list[AuthorizationRequest] = []

    def authorize(self, request: AuthorizationRequest) -> Decision:
        self.requests.append(request)
        return Decision(outcome="allow", reason="test allow")


def test_authorization_preflight_reads_metadata_and_invokes_pep() -> None:
    reader = _MetadataReaderSpy()
    pep = _PepSpy()
    principal = ServicePrincipal(
        client_id="phase3-writer",
        roles=("svc-knowledge-graph-writer",),
        attributes={"classification_clearance": "SECRET"},
    )
    preflight = MutationAuthorizationPreflight(
        reader,
        PepMutationAuthorizationEvaluator(pep, principal),
    )
    command = map_mutation_request(
        ReplaceEntityRequest.model_validate(
            {
                "replacement": _node(),
                "action": "update",
                "as_of": NOW,
            }
        ),
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="phase3-key",
    )

    preflight(command)

    assert reader.entity_reads == [(TENANT, "entity-1")]
    assert [item.resource_attributes["classification"] for item in pep.requests] == [
        "INTERNAL",
        "INTERNAL",
    ]
    assert all(
        item.resource_attributes["owner_matches_principal"] == "true" for item in pep.requests
    )


class _AllowEvaluator:
    def authorize(
        self,
        command: MutationCommand,
        context: MutationAuthorizationContext,
    ) -> None:
        assert context.proposed_classifications == (Classification.INTERNAL,)


class _AtomicPortSpy:
    def __init__(self) -> None:
        self.lookup_count = 0
        self.execute_count = 0

    def lookup(self, command: MutationCommand) -> AtomicMutationOutcome | None:
        self.lookup_count += 1
        return None

    def execute(
        self,
        request: MutationExecutionRequest,
        operation: MutationOperation,
    ) -> AtomicMutationOutcome:
        self.execute_count += 1
        committed: CommittedMutation = operation()
        return AtomicMutationOutcome(
            result=committed.result,
            mutation_id=UUID("11111111-1111-4111-8111-111111111111"),
            ledger_completed_at=NOW,
            replayed=False,
        )


def test_dependency_wiring_uses_preflight_and_atomic_mutation_port() -> None:
    store = InMemoryGraphStore()
    reader = _MetadataReaderSpy()
    preflight = MutationAuthorizationPreflight(reader, _AllowEvaluator())
    atomic = _AtomicPortSpy()
    application = mutation_knowledge_graph_application_dependency(
        store,
        atomic,
        preflight,
    )
    command = map_mutation_request(
        _create_request(),
        tenant=TENANT,
        principal=PRINCIPAL,
        idempotency_key="phase3-key",
    )
    assert isinstance(command, CreateEntityCommand)

    result = application.create_entity(command)

    assert result.tenant == TENANT
    assert atomic.lookup_count == 1
    assert atomic.execute_count == 1
    assert store.read(TENANT) != MemoryGraph()


def test_registered_dependency_factories_return_phase3_services() -> None:
    store = InMemoryGraphStore()
    metadata_reader = resource_metadata_reader_dependency(store)
    negotiator = _SchemaNegotiatorSpy()
    preparer = mutation_request_preparer_dependency(negotiator, _IdentityCompatibilityAdapters())

    assert isinstance(metadata_reader, GraphResourceMetadataReader)
    assert isinstance(preparer, MutationRequestPreparer)
