"""Pure Phase 3 transport DTO to application-command mapping."""

from __future__ import annotations

from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    EntityReplacementAction,
    MergeEntitiesCommand,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
)
from emg_memory_graph import (
    EvidenceRef,
    MemoryEdge,
    MemoryNode,
    Metadata,
    TemporalFact,
    TemporalHistory,
    TemporalValidity,
)
from emg_ontology import Entity
from emg_platform_core import PrincipalRef, TenantId

from .mutation_schemas import (
    CloseRelationshipRequest,
    CreateEntityRequest,
    EvidenceRefInput,
    MemoryEdgeInput,
    MemoryNodeInput,
    MergeEntitiesRequest,
    ReplaceEntityRequest,
    ReplaceRelationshipRequest,
    TemporalFactInput,
    TemporalHistoryInput,
)

MutationRequest = (
    CreateEntityRequest
    | ReplaceEntityRequest
    | ReplaceRelationshipRequest
    | CloseRelationshipRequest
    | MergeEntitiesRequest
)


def _evidence(value: EvidenceRefInput) -> EvidenceRef:
    document = value.model_dump(exclude={"metadata"})
    return EvidenceRef.model_validate(
        {
            **document,
            "metadata": Metadata.from_mapping(value.metadata),
        }
    )


def _fact(value: TemporalFactInput) -> TemporalFact:
    return TemporalFact(
        value=value.value,
        validity=TemporalValidity.model_validate(value.validity.model_dump()),
        evidence=tuple(_evidence(item) for item in value.evidence),
        recorded_at=value.recorded_at,
        metadata=Metadata.from_mapping(value.metadata),
    )


def _history(value: TemporalHistoryInput) -> TemporalHistory:
    return TemporalHistory(
        attribute=value.attribute,
        facts=tuple(_fact(item) for item in value.facts),
    )


def _node(value: MemoryNodeInput) -> MemoryNode:
    document = value.model_dump(
        exclude={"evidence", "histories", "metadata"},
    )
    return MemoryNode.model_validate(
        {
            **document,
            "evidence": tuple(_evidence(item) for item in value.evidence),
            "histories": tuple(_history(item) for item in value.histories),
            "metadata": Metadata.from_mapping(value.metadata),
        }
    )


def _edge(value: MemoryEdgeInput) -> MemoryEdge:
    document = value.model_dump(exclude={"evidence", "metadata"})
    return MemoryEdge.model_validate(
        {
            **document,
            "evidence": tuple(_evidence(item) for item in value.evidence),
            "metadata": Metadata.from_mapping(value.metadata),
        }
    )


def map_mutation_request(
    request: MutationRequest,
    *,
    tenant: TenantId,
    principal: PrincipalRef,
    idempotency_key: str,
) -> (
    CreateEntityCommand
    | ReplaceEntityCommand
    | ReplaceRelationshipCommand
    | CloseRelationshipCommand
    | MergeEntitiesCommand
):
    """Map one validated transport DTO without executing application behavior."""
    if isinstance(request, CreateEntityRequest):
        entity = Entity.model_validate(
            {
                **request.entity.model_dump(),
                "owner": str(principal.principal_id),
            }
        )
        return CreateEntityCommand(
            tenant=tenant,
            principal=principal,
            entity=entity,
            idempotency_key=idempotency_key,
            as_of=request.as_of,
        )
    if isinstance(request, ReplaceEntityRequest):
        return ReplaceEntityCommand(
            tenant=tenant,
            principal=principal,
            replacement=_node(request.replacement),
            action=EntityReplacementAction(request.action),
            idempotency_key=idempotency_key,
            as_of=request.as_of,
            reason=request.reason,
        )
    if isinstance(request, ReplaceRelationshipRequest):
        return ReplaceRelationshipCommand(
            tenant=tenant,
            principal=principal,
            replacement=_edge(request.replacement),
            idempotency_key=idempotency_key,
            as_of=request.as_of,
        )
    if isinstance(request, CloseRelationshipRequest):
        return CloseRelationshipCommand(
            tenant=tenant,
            principal=principal,
            edge_id=request.edge_id,
            idempotency_key=idempotency_key,
            as_of=request.as_of,
            reason=request.reason,
        )
    if isinstance(request, MergeEntitiesRequest):
        return MergeEntitiesCommand(
            tenant=tenant,
            principal=principal,
            survivor_id=request.survivor_id,
            source_ids=request.source_ids,
            idempotency_key=idempotency_key,
            as_of=request.as_of,
            reason=request.reason,
        )
    raise TypeError(f"unsupported mutation request type: {type(request).__name__}")
