"""Phase 3 schema negotiation followed by pure command construction."""

from __future__ import annotations

from dataclasses import dataclass

from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    MergeEntitiesCommand,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
    SchemaNegotiationRequest,
    SchemaNegotiator,
)
from emg_platform_core import PrincipalRef, TenantId

from .mutation_mapping import MutationRequest, map_mutation_request

MutationApplicationCommand = (
    CreateEntityCommand
    | ReplaceEntityCommand
    | ReplaceRelationshipCommand
    | CloseRelationshipCommand
    | MergeEntitiesCommand
)


@dataclass(frozen=True, slots=True)
class PreparedMutation:
    command: MutationApplicationCommand
    effective_schema_version: str


class MutationRequestPreparer:
    """Negotiate first, then map the already-validated transport request."""

    def __init__(self, schema_negotiator: SchemaNegotiator) -> None:
        self._schema_negotiator = schema_negotiator

    def prepare(
        self,
        request: MutationRequest,
        *,
        tenant: TenantId,
        principal: PrincipalRef,
        idempotency_key: str,
        preferred_schema_version: str,
    ) -> PreparedMutation:
        negotiated = self._schema_negotiator.negotiate(
            SchemaNegotiationRequest(preferred_version=preferred_schema_version)
        )
        command = map_mutation_request(
            request,
            tenant=tenant,
            principal=principal,
            idempotency_key=idempotency_key,
        )
        return PreparedMutation(
            command=command,
            effective_schema_version=negotiated.effective_version,
        )
