"""ADR-033 Phase 2 schema negotiation followed by pure command construction."""

from __future__ import annotations

from dataclasses import dataclass

from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CompatibilityAdapterRegistry,
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

    def __init__(
        self,
        schema_negotiator: SchemaNegotiator,
        compatibility_adapters: CompatibilityAdapterRegistry,
    ) -> None:
        self._schema_negotiator = schema_negotiator
        self._compatibility_adapters = compatibility_adapters

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
        canonical_request = self._compatibility_adapters.normalize(
            request,
            source_version=negotiated.effective_version,
        )
        command = map_mutation_request(
            canonical_request,
            tenant=tenant,
            principal=principal,
            idempotency_key=idempotency_key,
        )
        return PreparedMutation(
            command=command,
            effective_schema_version=negotiated.effective_version,
        )
