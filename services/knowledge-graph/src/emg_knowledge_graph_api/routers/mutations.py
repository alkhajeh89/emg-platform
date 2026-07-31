"""Thin ADR-027 Revision 5 mutation transport adapter."""

from __future__ import annotations

from typing import Annotated, Any, cast

from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    InvalidMutationCommandError,
    MergeEntitiesCommand,
    MutationExecutionResult,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
)
from fastapi import APIRouter, Header, Response, status

from ..authn import TenantContextDep
from ..dependencies import (
    MutationKnowledgeGraphApplicationDep,
    MutationPrincipalRefDep,
    MutationRequestPreparerDep,
)
from ..mutation_mapping import MutationRequest
from ..mutation_preparation import PreparedMutation
from ..mutation_response_mapping import mutation_response
from ..mutation_schemas import (
    CloseRelationshipRequest,
    CreateEntityRequest,
    MergeEntitiesRequest,
    MutationResponse,
    ReplaceEntityRequest,
    ReplaceRelationshipRequest,
)

IdempotencyKeyHeader = Annotated[
    str,
    Header(alias="X-Idempotency-Key", min_length=1),
]
PreferredSchemaVersionHeader = Annotated[
    str,
    Header(alias="Preferred-Schema-Version", min_length=1),
]

router = APIRouter(prefix="/api/v1", tags=["knowledge-graph-mutations"])

_EFFECTIVE_SCHEMA_VERSION_RESPONSE: dict[str, Any] = {
    "headers": {
        "Effective-Schema-Version": {
            "description": "The accepted schema contract for the mutation request.",
            "schema": {"type": "string"},
        }
    }
}


def _prepare(
    request: MutationRequest,
    *,
    caller: TenantContextDep,
    principal: MutationPrincipalRefDep,
    idempotency_key: str,
    preferred_schema_version: str,
    preparer: MutationRequestPreparerDep,
) -> PreparedMutation:
    return preparer.prepare(
        request,
        tenant=caller.tenant,
        principal=principal,
        idempotency_key=idempotency_key,
        preferred_schema_version=preferred_schema_version,
    )


def _respond(
    result: MutationExecutionResult,
    *,
    prepared: PreparedMutation,
    response: Response,
) -> MutationResponse:
    response.headers["Effective-Schema-Version"] = prepared.effective_schema_version
    return mutation_response(result)


def _require_identity(path_value: str, body_value: str, *, field: str) -> None:
    if path_value != body_value:
        raise InvalidMutationCommandError(f"path {field} must match the request body")


@router.post(
    "/entities",
    response_model=MutationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: _EFFECTIVE_SCHEMA_VERSION_RESPONSE},
)
def create_entity(
    request: CreateEntityRequest,
    response: Response,
    caller: TenantContextDep,
    principal: MutationPrincipalRefDep,
    preparer: MutationRequestPreparerDep,
    app: MutationKnowledgeGraphApplicationDep,
    idempotency_key: IdempotencyKeyHeader,
    preferred_schema_version: PreferredSchemaVersionHeader,
) -> MutationResponse:
    prepared = _prepare(
        request,
        caller=caller,
        principal=principal,
        idempotency_key=idempotency_key,
        preferred_schema_version=preferred_schema_version,
        preparer=preparer,
    )
    result = app.create_entity(cast(CreateEntityCommand, prepared.command))
    return _respond(result, prepared=prepared, response=response)


@router.put(
    "/entities/{entity_id}",
    response_model=MutationResponse,
    responses={status.HTTP_200_OK: _EFFECTIVE_SCHEMA_VERSION_RESPONSE},
)
def replace_entity(
    entity_id: str,
    request: ReplaceEntityRequest,
    response: Response,
    caller: TenantContextDep,
    principal: MutationPrincipalRefDep,
    preparer: MutationRequestPreparerDep,
    app: MutationKnowledgeGraphApplicationDep,
    idempotency_key: IdempotencyKeyHeader,
    preferred_schema_version: PreferredSchemaVersionHeader,
) -> MutationResponse:
    _require_identity(entity_id, request.replacement.node_id, field="entity_id")
    prepared = _prepare(
        request,
        caller=caller,
        principal=principal,
        idempotency_key=idempotency_key,
        preferred_schema_version=preferred_schema_version,
        preparer=preparer,
    )
    result = app.replace_entity(cast(ReplaceEntityCommand, prepared.command))
    return _respond(result, prepared=prepared, response=response)


@router.put(
    "/relationships/{edge_id}",
    response_model=MutationResponse,
    responses={status.HTTP_200_OK: _EFFECTIVE_SCHEMA_VERSION_RESPONSE},
)
def replace_relationship(
    edge_id: str,
    request: ReplaceRelationshipRequest,
    response: Response,
    caller: TenantContextDep,
    principal: MutationPrincipalRefDep,
    preparer: MutationRequestPreparerDep,
    app: MutationKnowledgeGraphApplicationDep,
    idempotency_key: IdempotencyKeyHeader,
    preferred_schema_version: PreferredSchemaVersionHeader,
) -> MutationResponse:
    _require_identity(edge_id, request.replacement.edge_id, field="edge_id")
    prepared = _prepare(
        request,
        caller=caller,
        principal=principal,
        idempotency_key=idempotency_key,
        preferred_schema_version=preferred_schema_version,
        preparer=preparer,
    )
    result = app.replace_relationship(cast(ReplaceRelationshipCommand, prepared.command))
    return _respond(result, prepared=prepared, response=response)


@router.post(
    "/relationships/{edge_id}/close",
    response_model=MutationResponse,
    responses={status.HTTP_200_OK: _EFFECTIVE_SCHEMA_VERSION_RESPONSE},
)
def close_relationship(
    edge_id: str,
    request: CloseRelationshipRequest,
    response: Response,
    caller: TenantContextDep,
    principal: MutationPrincipalRefDep,
    preparer: MutationRequestPreparerDep,
    app: MutationKnowledgeGraphApplicationDep,
    idempotency_key: IdempotencyKeyHeader,
    preferred_schema_version: PreferredSchemaVersionHeader,
) -> MutationResponse:
    _require_identity(edge_id, request.edge_id, field="edge_id")
    prepared = _prepare(
        request,
        caller=caller,
        principal=principal,
        idempotency_key=idempotency_key,
        preferred_schema_version=preferred_schema_version,
        preparer=preparer,
    )
    result = app.close_relationship(cast(CloseRelationshipCommand, prepared.command))
    return _respond(result, prepared=prepared, response=response)


@router.post(
    "/entities/{survivor_id}/merge",
    response_model=MutationResponse,
    responses={status.HTTP_200_OK: _EFFECTIVE_SCHEMA_VERSION_RESPONSE},
)
def merge_entities(
    survivor_id: str,
    request: MergeEntitiesRequest,
    response: Response,
    caller: TenantContextDep,
    principal: MutationPrincipalRefDep,
    preparer: MutationRequestPreparerDep,
    app: MutationKnowledgeGraphApplicationDep,
    idempotency_key: IdempotencyKeyHeader,
    preferred_schema_version: PreferredSchemaVersionHeader,
) -> MutationResponse:
    _require_identity(survivor_id, request.survivor_id, field="survivor_id")
    prepared = _prepare(
        request,
        caller=caller,
        principal=principal,
        idempotency_key=idempotency_key,
        preferred_schema_version=preferred_schema_version,
        preparer=preparer,
    )
    result = app.merge_entities(cast(MergeEntitiesCommand, prepared.command))
    return _respond(result, prepared=prepared, response=response)
